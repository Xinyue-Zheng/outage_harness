"""The investigation loop: the design's nodes run in order by a plain loop.

    START -> initialize -> render_context -> llm_call -> parse -> validate_action -> verifier
    verifier --query--> execute_query -> update_state -> write_step -> loop_guards
    verifier --finish--> completion_checks --all pass--> END: complete
    parse --does not parse--> record_error_obs; validate_action --invalid--> record_error_obs
    record_error_obs --retry or rejection cap--> END
    loop_guards --cap hit--> END; otherwise --next round--> render_context

Two nodes call a model: llm_call (the decision model) and verifier (the verifier
model). Every other node is program code. A refused finish and a recorded error
return to render_context through loop_guards, so the caps are checked in every
round. Each round leaves one Step, which is the checkpoint; nothing here catches
exceptions.
"""

import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, assert_never

from outage_poc import caps, checks
from outage_poc import decision as decisions
from outage_poc.context import render_context
from outage_poc.data_client import (
    DataClient,
    ToolDeclaration,
    ToolResult,
    tools_data_version,
)
from outage_poc.init import initialize
from outage_poc.model import ModelAdapter
from outage_poc.models import (
    Accepted,
    AreaId,
    Counters,
    Decision,
    EndReason,
    ExecutionSource,
    ImpactAnalysis,
    Inspection,
    KPIRows,
    Member,
    MemberError,
    Note,
    Observation,
    ObservationId,
    ParameterValue,
    ParseFailure,
    Rejection,
    Rendered,
    Review,
    RunConfig,
    RunRecord,
    RunResult,
    State,
    Step,
    StepDigest,
    StepId,
    TaskInput,
    Trace,
    UnreadableReview,
)
from outage_poc.observation import (
    coverage_member,
    impact_member,
    inspection_member,
    kpi_member,
    record_observation,
)
from outage_poc.persistence import (
    load_observations,
    read_json,
    read_observation,
    read_step,
    write_json,
    write_text,
)
from outage_poc.registry import Registry, build_registry
from outage_poc.render import render_map, render_page
from outage_poc.state import (
    STUDY_AREA,
    apply_coverage,
    apply_impact,
    apply_inspection,
    apply_kpi,
    apply_note,
    estimate_impact,
    load_parameters,
    summary_for,
)
from outage_poc.verifier import VerifierAdapter

INITIAL_STATE = "states/state_00.json"
PREFIX = "contexts/prefix.txt"


@dataclass(frozen=True)
class LoopState:
    """The loop state. Each node returns the fields it replaced; nothing merges.

    The outage State is one immutable field, replaced as a whole on every update.
    Earlier rounds are kept as digests; their full States are in the Step files.
    """

    task: TaskInput
    state: State | None
    counters: Counters
    history: tuple[StepDigest, ...]
    query_cache: tuple[ObservationId, ...]
    round: int
    # The State the current round started from.
    state_before: State | None
    rendered: Rendered | None
    raw_output: str | None
    decision: Decision | None
    validation: Accepted | Rejection | ParseFailure | None
    review: Review | UnreadableReview | None
    observation: Observation | None
    end_reason: EndReason | None


Update = dict[str, object]
Node = Literal[
    "initialize",
    "render_context",
    "llm_call",
    "parse",
    "validate_action",
    "verifier",
    "execute_query",
    "update_state",
    "write_step",
    "completion_checks",
    "record_error_obs",
    "loop_guards",
]


@dataclass(frozen=True)
class ResumePoint:
    """The first round of a resumed run starts from the corrected State."""

    round: int


@dataclass(frozen=True)
class RunEnv:
    """What the nodes need besides the loop state."""

    run_dir: Path
    config: RunConfig
    registry: Registry
    model: ModelAdapter
    verifier: VerifierAdapter
    client: DataClient
    data_version: str
    execution_source: ExecutionSource
    resume: ResumePoint | None
    elapsed_offset_s: float
    started_monotonic: float


def step_path(index: int) -> str:
    return f"steps/step_{index:02d}.json"


def _round_file(kind: Literal["inputs", "outputs"], round_index: int) -> str:
    return f"{kind}/round_{round_index:02d}.txt"


def _current(loop: LoopState) -> State:
    if loop.state is None:
        raise ValueError("The graph has no State before initialize")
    return loop.state


def _accepted(loop: LoopState) -> Accepted:
    if not isinstance(loop.validation, Accepted):
        raise ValueError(f"Round {loop.round} has no accepted decision")
    return loop.validation


def _ids(value: ParameterValue) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"Expected a set of ids, got {value!r}")
    return value


def _text(value: ParameterValue) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Expected a string, got {value!r}")
    return value


def _float(value: ParameterValue) -> float:
    if not isinstance(value, float):
        raise ValueError(f"Expected a float, got {value!r}")
    return value


def _int(value: ParameterValue) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Expected an integer, got {value!r}")
    return value


def _call_each(
    env: RunEnv,
    name: str,
    members: tuple[str, ...],
    arguments: Callable[[str], dict[str, object]],
) -> list[ToolResult]:
    """One call per member, concurrently; at most max_members members exist."""
    with ThreadPoolExecutor(max_workers=len(members)) as pool:
        return list(
            pool.map(
                lambda member: env.client.call(
                    name, arguments(member), env.config.query_timeout_s
                ),
                members,
            )
        )


def execute(
    accepted: Accepted,
    state: State,
    env: RunEnv,
    obs_id: ObservationId,
    round_index: int,
) -> Observation:
    """Run the action and wrap its result as one Observation."""
    started = time.monotonic()
    action = accepted.action
    parameters = accepted.parameters
    match action.result:
        case "coverage_rows":
            areas = _ids(parameters["areas"])
            epoch = _text(parameters["epoch"])
            results = _call_each(
                env, action.name, areas, lambda area: {"areas": [area], "epoch": epoch}
            )
            members = tuple(
                coverage_member(state, area, result, obs_id, env.run_dir)
                for area, result in zip(areas, results, strict=True)
            )
        case "kpi_rows":
            cells = _ids(parameters["cells"])
            window = _text(parameters["window"])
            indicators = _ids(parameters["indicators"])
            results = _call_each(
                env,
                action.name,
                cells,
                lambda cell: {
                    "cells": [cell],
                    "window": window,
                    "indicators": list(indicators),
                },
            )
            members = tuple(
                kpi_member(cell, indicators, result, obs_id, env.run_dir)
                for cell, result in zip(cells, results, strict=True)
            )
        case "impact":
            impact = estimate_impact(
                state,
                load_observations(state, env.run_dir),
                load_parameters(
                    AreaId(_text(parameters["scope"])),
                    _float(parameters["min_rsrp_dbm"]),
                    _float(parameters["min_rsrq_db"]),
                ),
            )
            members = (impact_member(impact, obs_id, env.run_dir),)
        case "observation_rows":
            members = (
                inspection_member(
                    state,
                    _text(parameters["observation"]),
                    _int(parameters["first_row"]),
                    env.config.inspect_max_rows,
                    round_index,
                    obs_id,
                    env.run_dir,
                ),
            )
        case "cell_metadata" | "geography" | "none":
            raise ValueError(f"{action.name} does not run inside the loop")
        case _ as unreachable:
            assert_never(unreachable)
    duration_ms = round((time.monotonic() - started) * 1000)
    return record_observation(
        obs_id,
        action.name,
        parameters,
        members,
        duration_ms,
        env.data_version,
        env.run_dir,
    )


def _failure_note(
    observation: Observation, member: Member, round_index: int, run_dir: Path
) -> Note | None:
    match member.status:
        case "ok" | "missing":
            return None
        case "empty":
            detail = "returned no rows"
        case "timeout":
            detail = "timed out; no result"
        case "error":
            if member.records_path is None:
                raise ValueError("An error member needs its records file")
            message = read_json(MemberError, run_dir / member.records_path).error
            detail = f"returned an error: {message}"
        case _ as unreachable:
            assert_never(unreachable)
    return Note(
        "query_failed",
        round_index,
        f"{observation.action} member {member.member_id} {detail}",
    )


def apply_observation(
    state: State,
    accepted: Accepted,
    observation: Observation,
    round_index: int,
    run_dir: Path,
) -> State:
    """Apply what the persisted member files hold; failed members become Notes."""
    state_id = f"state_{round_index:02d}"
    paths = [
        member.records_path
        for member in observation.members
        if member.status in ("ok", "missing") and member.records_path is not None
    ]
    match accepted.action.result:
        case "coverage_rows":
            if paths:
                members = tuple(
                    (read_observation(run_dir / path), path) for path in paths
                )
                registered = load_observations(state, run_dir)
                registered.update({item.id: item for item, _ in members})
                state = apply_coverage(state, members, state_id, registered)
        case "kpi_rows":
            if paths:
                records = tuple(
                    record
                    for path in paths
                    for record in read_json(KPIRows, run_dir / path).records
                )
                state = apply_kpi(state, records, state_id)
        case "impact":
            (path,) = paths
            impact = read_json(ImpactAnalysis, run_dir / path)
            state = apply_impact(
                state, impact, state_id, load_observations(state, run_dir)
            )
        case "observation_rows":
            (path,) = paths
            state = apply_inspection(
                state, read_json(Inspection, run_dir / path), state_id
            )
        case "cell_metadata" | "geography" | "none":
            raise ValueError(f"{accepted.action.name} has no State update")
        case _ as unreachable:
            assert_never(unreachable)
    for member in observation.members:
        note = _failure_note(observation, member, round_index, run_dir)
        if note is not None:
            state = apply_note(state, note)
    return state


def _outcome(loop: LoopState, current: State, end_reason: EndReason | None) -> str:
    match loop.validation:
        case ParseFailure(reason=reason):
            return f"parse failure: {reason.splitlines()[0]}"
        case Rejection(kind=kind):
            return f"rejected: {kind}"
        case Accepted():
            observation = loop.observation
            if observation is not None:
                members = ", ".join(
                    f"{member.member_id} {member.status}"
                    for member in observation.members
                )
                return f"{observation.id} {observation.status} ({members})"
            if end_reason == "complete":
                return "finish accepted: completion checks passed"
            unmet = [
                note.text.split(":", 1)[0]
                for note in current.notes
                if note.kind == "unmet" and note.step_index == loop.round
            ]
            return f"finish refused: {', '.join(unmet)}"
        case None:
            raise ValueError(f"Round {loop.round} ended without a validation result")
        case _ as unreachable:
            assert_never(unreachable)


def record_step(
    env: RunEnv, loop: LoopState, current: State, end_reason: EndReason | None
) -> Update:
    """Write the round as a Step with its full State: the checkpoint unit."""
    round_index = loop.round
    state_id = f"state_{round_index:02d}"
    if current.id != state_id:
        current = replace(current, id=state_id)
    if loop.raw_output is None or loop.state_before is None:
        raise ValueError(
            "A Step needs the model's output and the State it started from"
        )
    counters = replace(
        loop.counters,
        step=round_index,
        elapsed_s=env.elapsed_offset_s + (time.monotonic() - env.started_monotonic),
    )
    match loop.validation:
        case Accepted():
            status: Literal["accepted", "rejected", "parse_failure"] = "accepted"
            message = None
        case Rejection(message=rejection):
            status, message = "rejected", rejection
        case ParseFailure(reason=reason):
            status, message = "parse_failure", reason
        case None:
            raise ValueError("A Step needs a validation result")
        case _ as unreachable:
            assert_never(unreachable)
    match loop.review:
        case Review(outcome=outcome, reason=review_reason):
            review: Literal["agree", "concern", "not_run"] = outcome
        case UnreadableReview(reply=reply, problem=problem):
            review = "not_run"
            review_reason = f"unreadable verifier reply ({problem}): {reply}"
        case None:
            review, review_reason = "not_run", None
        case _ as unreachable:
            assert_never(unreachable)
    observation = loop.observation
    query_cache = loop.query_cache + (() if observation is None else (observation.id,))
    context_path = f"contexts/{state_id}.txt"
    visualization = (
        f"maps/step_{round_index:02d}.svg" if env.config.write_maps else None
    )
    resumed = env.resume is not None and env.resume.round == round_index
    step = Step(
        id=StepId(f"step_{round_index:02d}"),
        index=round_index,
        execution_source="resume" if resumed else env.execution_source,
        state_before=loop.state_before,
        context=_round_file("inputs", round_index),
        raw_output=loop.raw_output,
        decision=loop.decision,
        validation=status,
        validation_message=message,
        review=review,
        review_reason=review_reason,
        observation=observation,
        state_after=current,
        context_after=context_path,
        outcome=_outcome(loop, current, end_reason),
        counters=counters,
        data_version=env.data_version,
        query_cache=query_cache,
        registry_version=env.registry.version,
        visualization=visualization,
    )
    history = (*loop.history, StepDigest.of(step))
    write_text(
        env.run_dir / context_path,
        render_context(current, env.registry, env.config, history).variable,
    )
    if visualization is not None:
        write_text(env.run_dir / visualization, render_map(current))
    write_json(env.run_dir / step_path(round_index), step)
    return {
        "state": current,
        "history": history,
        "counters": counters,
        "query_cache": query_cache,
        "end_reason": end_reason,
    }


def run_rounds(env: RunEnv, loop: LoopState, entry: Node) -> LoopState:
    """Run the design's nodes from `entry` until a node sets a typed end reason.

    Each node is a function of the loop state that returns the fields it
    replaced. The conditional edges are the three `after_*` and `route`
    functions. A run starts at initialize; a resumed run starts at loop_guards
    with the corrected State of the Step it resumes from.
    """
    config = env.config
    registry = env.registry

    def initialize_node(state: LoopState) -> Update:
        """Fixed program logic: two lookups, the areas and relations, State 0."""
        initial = initialize(state.task, env.client, config)
        rendered = render_context(initial, registry, config, ())
        write_json(env.run_dir / INITIAL_STATE, initial)
        write_text(env.run_dir / PREFIX, rendered.prefix)
        write_text(env.run_dir / "contexts/state_00.txt", rendered.variable)
        return {"state": initial}

    def render_context_node(state: LoopState) -> Update:
        current = _current(state)
        round_index = len(state.history) + 1
        rendered = render_context(current, registry, config, state.history)
        write_text(env.run_dir / _round_file("inputs", round_index), rendered.text)
        return {
            "round": round_index,
            "state_before": current,
            "rendered": rendered,
            "raw_output": None,
            "decision": None,
            "validation": None,
            "review": None,
            "observation": None,
        }

    def llm_call(state: LoopState) -> Update:
        """Model node: the decision model proposes action, parameters and gap."""
        if state.rendered is None:
            raise ValueError("llm_call needs a rendered context")
        raw = env.model.propose(state.rendered)
        write_text(env.run_dir / _round_file("outputs", state.round), raw)
        return {"raw_output": raw}

    def parse(state: LoopState) -> Update:
        if state.raw_output is None:
            raise ValueError("parse needs the model's output")
        parsed = decisions.parse(state.raw_output)
        if isinstance(parsed, ParseFailure):
            return {"validation": parsed}
        return {"decision": parsed, "counters": replace(state.counters, retries=0)}

    def validate_action(state: LoopState) -> Update:
        if state.decision is None:
            raise ValueError("validate_action needs a parsed decision")
        return {
            "validation": decisions.validate(
                state.decision,
                _current(state),
                registry,
                config.query_budget_locations,
            )
        }

    def verifier(state: LoopState) -> Update:
        """Model node: the verifier reviews the gap; a concern becomes a fact in State."""
        if state.rendered is None:
            raise ValueError("verifier needs the rendered context")
        review = env.verifier.review(_accepted(state), state.rendered)
        current = _current(state)
        match review:
            case Review(outcome="concern", reason=reason):
                current = apply_note(current, Note("concern", state.round, reason))
            case Review() | UnreadableReview():
                pass
            case _ as unreachable:
                assert_never(unreachable)
        return {"review": review, "state": current}

    def execute_query(state: LoopState) -> Update:
        obs_id = ObservationId(f"obs_{state.round:02d}")
        return {
            "observation": execute(
                _accepted(state), _current(state), env, obs_id, state.round
            )
        }

    def update_state(state: LoopState) -> Update:
        if state.observation is None:
            raise ValueError("update_state needs an observation")
        current = apply_observation(
            _current(state),
            _accepted(state),
            state.observation,
            state.round,
            env.run_dir,
        )
        queried = len(summary_for(current, STUDY_AREA).queried_ids)
        return {
            "state": current,
            "counters": replace(state.counters, queried_locations=queried),
        }

    def write_step(state: LoopState) -> Update:
        return record_step(env, state, _current(state), None)

    def completion_checks(state: LoopState) -> Update:
        """The model asks to stop; these four program rules decide."""
        finish = decisions.route(_accepted(state))
        if not isinstance(finish, decisions.Finish):
            raise ValueError("completion_checks needs a finish decision")
        current = _current(state)
        unmet = checks.run(current, config, finish)
        for item in unmet:
            current = apply_note(current, Note("unmet", state.round, item.text))
        end_reason: EndReason | None = None if unmet else "complete"
        blocked = checks.budget_blocks_boundary(current, config) if unmet else None
        if blocked is not None:
            # The model asked to stop and the program agrees that it cannot do
            # better within the budget: a typed end, never confused with complete.
            current = apply_note(current, Note("unmet", state.round, blocked))
            end_reason = "query_budget"
        return record_step(env, state, current, end_reason)

    def record_error_obs(state: LoopState) -> Update:
        """The parse failure or rejection becomes a fact in State and counts against its cap."""
        counters = state.counters
        end_reason: EndReason | None = None
        match state.validation:
            case ParseFailure(reason=reason):
                counters = replace(counters, retries=counters.retries + 1)
                note = Note("parse_failure", state.round, reason)
                if counters.retries >= config.retry_cap:
                    end_reason = "retry_cap"
            case Rejection(kind=kind, message=message):
                counters = replace(counters, rejections=counters.rejections + 1)
                note = Note("rejected", state.round, f"{kind}: {message}")
                if counters.rejections >= config.rejection_cap:
                    end_reason = "rejection_cap"
            case other:
                raise ValueError(f"record_error_obs got {other!r}")
        return record_step(
            env,
            replace(state, counters=counters),
            apply_note(_current(state), note),
            end_reason,
        )

    def loop_guards(state: LoopState) -> Update:
        """Caps, not judgment: repeated query, step cap, query budget, wall time.

        A query refused for budget while no affordable area borders the down cell
        also ends the run: the boundary rule can no longer be met.
        """
        if caps.repeated(state.history, registry, config):
            return {"end_reason": "repeated_query"}
        if (
            isinstance(state.validation, Rejection)
            and state.validation.kind == "budget_exceeded"
            and checks.budget_blocks_boundary(_current(state), config) is not None
        ):
            return {"end_reason": "query_budget"}
        return {"end_reason": caps.hit(state.counters, config)}

    def after_parse(state: LoopState) -> Literal["record_error_obs", "validate_action"]:
        if isinstance(state.validation, ParseFailure):
            return "record_error_obs"
        return "validate_action"

    def after_validate(state: LoopState) -> Literal["record_error_obs", "verifier"]:
        if isinstance(state.validation, Rejection):
            return "record_error_obs"
        return "verifier"

    def route(state: LoopState) -> Literal["completion_checks", "execute_query"]:
        match decisions.route(_accepted(state)):
            case decisions.Finish():
                return "completion_checks"
            case decisions.Query():
                return "execute_query"
            case _ as unreachable:
                assert_never(unreachable)

    def apply(update: Update) -> None:
        nonlocal loop
        loop = replace(loop, **update)

    node: Node = entry
    while True:
        current: Node = node
        match current:
            case "initialize":
                apply(initialize_node(loop))
                node = "render_context"
            case "render_context":
                apply(render_context_node(loop))
                node = "llm_call"
            case "llm_call":
                apply(llm_call(loop))
                node = "parse"
            case "parse":
                apply(parse(loop))
                node = after_parse(loop)
            case "validate_action":
                apply(validate_action(loop))
                node = after_validate(loop)
            case "verifier":
                apply(verifier(loop))
                node = route(loop)
            case "execute_query":
                apply(execute_query(loop))
                node = "update_state"
            case "update_state":
                apply(update_state(loop))
                node = "write_step"
            case "write_step":
                apply(write_step(loop))
                node = "loop_guards"
            case "completion_checks":
                apply(completion_checks(loop))
                if loop.end_reason is not None:
                    return loop
                node = "loop_guards"
            case "record_error_obs":
                apply(record_error_obs(loop))
                if loop.end_reason is not None:
                    return loop
                node = "loop_guards"
            case "loop_guards":
                apply(loop_guards(loop))
                if loop.end_reason is not None:
                    return loop
                node = "render_context"
            case _ as unreachable:
                assert_never(unreachable)


def resolve_data_version(config: RunConfig, tools: tuple[ToolDeclaration, ...]) -> str:
    if config.data_version is None:
        return tools_data_version(tools)
    reported = {tool.data_version for tool in tools} - {None}
    if reported and reported != {config.data_version}:
        raise ValueError(
            f"Configured data version {config.data_version} differs from the "
            f"tools' {sorted(str(version) for version in reported)}"
        )
    return config.data_version


def prepare_run_dir(run_dir: Path) -> None:
    if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
        raise ValueError(f"Output must be a new or empty directory: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)


def finish_run(
    env: RunEnv,
    run_id: str,
    final: LoopState,
    started_at: str,
    resumed_from: str | None,
) -> RunResult:
    """Check the final loop state, then write trace.json and run.json."""
    if final.end_reason is None:
        raise ValueError("The loop ended without a typed end reason")
    reason = final.end_reason
    steps = tuple(step_path(digest.index) for digest in final.history)
    trace = Trace(
        run_id=run_id,
        config=env.config,
        initial_state=INITIAL_STATE,
        prefix=PREFIX,
        steps=steps,
        end_reason=reason,
    )
    write_json(env.run_dir / "trace.json", trace)
    write_json(
        env.run_dir / "run.json",
        RunRecord(
            run_id=run_id,
            config=env.config,
            decision_model=env.model.name,
            verifier_model=env.verifier.name,
            end_reason=reason,
            counters=final.counters,
            last_step=steps[-1] if steps else None,
            started_at=started_at,
            ended_at=datetime.now(UTC).isoformat(),
            resumed_from=resumed_from,
        ),
    )
    if env.config.write_maps:
        write_text(
            env.run_dir / "index.html",
            render_page(
                env.run_dir, trace, [read_step(env.run_dir / path) for path in steps]
            ),
        )
    return RunResult(run_id, reason, final.counters, "trace.json")


def run(
    config: RunConfig,
    task: TaskInput,
    model: ModelAdapter,
    verifier: VerifierAdapter,
    client: DataClient,
    run_dir: Path,
    execution_source: ExecutionSource,
) -> RunResult:
    """Register the tools, then run the loop from initialize until a typed end."""
    prepare_run_dir(run_dir)
    started_at = datetime.now(UTC).isoformat()
    tools = client.list_tools()
    env = RunEnv(
        run_dir=run_dir,
        config=config,
        registry=build_registry(tools),
        model=model,
        verifier=verifier,
        client=client,
        data_version=resolve_data_version(config, tools),
        execution_source=execution_source,
        resume=None,
        elapsed_offset_s=0.0,
        started_monotonic=time.monotonic(),
    )
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    initial = LoopState(
        task=task,
        state=None,
        counters=Counters(0, 0, 0, 0, 0.0),
        history=(),
        query_cache=(),
        round=0,
        state_before=None,
        rendered=None,
        raw_output=None,
        decision=None,
        validation=None,
        review=None,
        observation=None,
        end_reason=None,
    )
    final = run_rounds(env, initial, "initialize")
    return finish_run(env, run_id, final, started_at, resumed_from=None)
