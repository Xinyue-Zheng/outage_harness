"""The investigation loop with the transcript context method.

The nodes, edges and the harness are those of `loop.py`; this module reuses
its execution, State update, Step writing and run finishing. Two nodes differ:

    render_context  builds the transcript (append the last round's reply and
                    tool output, compact if too long) instead of rendering State
    llm_call        sends the transcript's messages to the model

The verifier is part of the harness and keeps reading the State rendering, so
the only difference between the two methods is what the deciding model reads.
Every round still leaves one Step; the Step's `context` file holds the exact
messages sent to the model, flattened, and `transcript/round_NN.json` holds
them as sent.
"""

import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, assert_never

from outage_poc import caps, checks
from outage_poc import decision as decisions
from outage_poc.context import render_context
from outage_poc.data_client import DataClient
from outage_poc.init import initialize
from outage_poc.loop import (
    INITIAL_STATE,
    PREFIX,
    LoopState,
    RunEnv,
    Update,
    _accepted,
    _current,
    _round_file,
    apply_observation,
    execute,
    finish_run,
    prepare_run_dir,
    record_step,
    resolve_data_version,
)
from outage_poc.models import (
    Accepted,
    Counters,
    EndReason,
    ExecutionSource,
    Note,
    ObservationId,
    ParseFailure,
    Rejection,
    Review,
    RunConfig,
    RunResult,
    TaskInput,
    UnreadableReview,
)
from outage_poc.persistence import write_json, write_text
from outage_poc.registry import build_registry
from outage_poc.state import STUDY_AREA, apply_note, summary_for
from outage_poc.transcript import (
    RoundResult,
    Summarizer,
    Transcript,
    TranscriptConfig,
    append,
    estimate_tokens,
    maybe_compact,
    notes_text,
    start,
    tool_output,
    write_messages,
)
from outage_poc.transcript_model import TranscriptModelAdapter
from outage_poc.verifier import VerifierAdapter

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
class TranscriptEnv:
    base: RunEnv
    model: TranscriptModelAdapter
    summarizer: Summarizer
    transcript_config: TranscriptConfig


@dataclass(frozen=True)
class TranscriptLoop:
    loop: LoopState
    transcript: Transcript | None


def _transcript_file(round_index: int) -> str:
    return f"transcript/round_{round_index:02d}.json"


def _compaction_file(round_index: int) -> str:
    return f"compactions/before_round_{round_index:02d}.txt"


def round_result(loop: LoopState, state_after: object) -> RoundResult:
    """What the finished round produced, read from the loop state after it."""
    if loop.raw_output is None:
        raise ValueError(f"Round {loop.round} has no model reply")
    current = _current(loop)
    error: str | None = None
    match loop.validation:
        case ParseFailure(reason=reason):
            error = f"your reply did not parse: {reason}"
        case Rejection(kind=kind, message=message):
            error = f"decision rejected ({kind}): {message}"
        case Accepted() | None:
            error = None
        case _ as unreachable:
            assert_never(unreachable)
    concern: str | None = None
    match loop.review:
        case Review(outcome="concern", reason=reason):
            concern = reason
        case Review() | UnreadableReview() | None:
            concern = None
        case _ as unreachable:
            assert_never(unreachable)
    return RoundResult(
        reply=loop.raw_output,
        observation=loop.observation,
        error=error,
        concern=concern,
        unmet=notes_text(current, loop.round, "unmet"),
    )


def run_rounds(
    env: TranscriptEnv, start_state: TranscriptLoop, entry: Node
) -> TranscriptLoop:
    """The same loop as `loop.run_rounds`, with the transcript in place of the rendering."""
    base = env.base
    config = base.config
    registry = base.registry
    run_dir = base.run_dir
    current_loop = start_state

    def initialize_node(state: TranscriptLoop) -> TranscriptLoop:
        initial = initialize(state.loop.task, base.client, config)
        rendered = render_context(initial, registry, config, ())
        write_json(run_dir / INITIAL_STATE, initial)
        write_text(run_dir / PREFIX, rendered.prefix)
        write_text(run_dir / "contexts/state_00.txt", rendered.variable)
        return TranscriptLoop(
            replace(state.loop, state=initial),
            start(rendered.prefix, initial.task),
        )

    def render_context_node(state: TranscriptLoop) -> TranscriptLoop:
        loop = state.loop
        transcript = state.transcript
        if transcript is None:
            raise ValueError("render_context needs a started transcript")
        current = _current(loop)
        round_index = len(loop.history) + 1
        if loop.round >= 1:
            result = round_result(loop, current)
            transcript = append(
                transcript,
                loop.round,
                result.reply,
                tool_output(result, run_dir, env.transcript_config),
            )
        transcript, compacted = maybe_compact(
            transcript, env.transcript_config, env.summarizer
        )
        if compacted is not None:
            write_text(
                run_dir / _compaction_file(round_index),
                f"[summarized by {env.summarizer.name}]\n\n{compacted}\n\n"
                f"[summary]\n{transcript.summary}\n",
            )
        messages = transcript.messages()
        write_messages(run_dir / _transcript_file(round_index), messages)
        write_text(run_dir / _round_file("inputs", round_index), transcript.flattened())
        # The verifier still reads the State rendering: it is part of the harness.
        rendered = render_context(current, registry, config, loop.history)
        return TranscriptLoop(
            replace(
                loop,
                round=round_index,
                state_before=current,
                rendered=rendered,
                raw_output=None,
                decision=None,
                validation=None,
                review=None,
                observation=None,
            ),
            transcript,
        )

    def llm_call(state: TranscriptLoop) -> Update:
        if state.transcript is None:
            raise ValueError("llm_call needs the transcript")
        raw = env.model.propose_from(state.transcript.messages())
        write_text(run_dir / _round_file("outputs", state.loop.round), raw)
        return {"raw_output": raw}

    def parse(loop: LoopState) -> Update:
        if loop.raw_output is None:
            raise ValueError("parse needs the model's output")
        parsed = decisions.parse(loop.raw_output)
        if isinstance(parsed, ParseFailure):
            return {"validation": parsed}
        return {"decision": parsed, "counters": replace(loop.counters, retries=0)}

    def validate_action(loop: LoopState) -> Update:
        if loop.decision is None:
            raise ValueError("validate_action needs a parsed decision")
        return {
            "validation": decisions.validate(
                loop.decision, _current(loop), registry, config.query_budget_locations
            )
        }

    def verifier(loop: LoopState) -> Update:
        if loop.rendered is None:
            raise ValueError("verifier needs the rendered context")
        review = base.verifier.review(_accepted(loop), loop.rendered)
        current = _current(loop)
        match review:
            case Review(outcome="concern", reason=reason):
                current = apply_note(current, Note("concern", loop.round, reason))
            case Review() | UnreadableReview():
                pass
            case _ as unreachable:
                assert_never(unreachable)
        return {"review": review, "state": current}

    def execute_query(loop: LoopState) -> Update:
        obs_id = ObservationId(f"obs_{loop.round:02d}")
        return {
            "observation": execute(
                _accepted(loop), _current(loop), base, obs_id, loop.round
            )
        }

    def update_state(loop: LoopState) -> Update:
        if loop.observation is None:
            raise ValueError("update_state needs an observation")
        current = apply_observation(
            _current(loop), _accepted(loop), loop.observation, loop.round, run_dir
        )
        queried = len(summary_for(current, STUDY_AREA).queried_ids)
        return {
            "state": current,
            "counters": replace(loop.counters, queried_locations=queried),
        }

    def write_step(loop: LoopState) -> Update:
        return record_step(base, loop, _current(loop), None)

    def completion_checks(loop: LoopState) -> Update:
        finish = decisions.route(_accepted(loop))
        if not isinstance(finish, decisions.Finish):
            raise ValueError("completion_checks needs a finish decision")
        current = _current(loop)
        unmet = checks.run(current, config, finish)
        for item in unmet:
            current = apply_note(current, Note("unmet", loop.round, item.text))
        end_reason: EndReason | None = None if unmet else "complete"
        blocked = checks.budget_blocks_boundary(current, config) if unmet else None
        if blocked is not None:
            current = apply_note(current, Note("unmet", loop.round, blocked))
            end_reason = "query_budget"
        return record_step(base, loop, current, end_reason)

    def record_error_obs(loop: LoopState) -> Update:
        counters = loop.counters
        end_reason: EndReason | None = None
        match loop.validation:
            case ParseFailure(reason=reason):
                counters = replace(counters, retries=counters.retries + 1)
                note = Note("parse_failure", loop.round, reason)
                if counters.retries >= config.retry_cap:
                    end_reason = "retry_cap"
            case Rejection(kind=kind, message=message):
                counters = replace(counters, rejections=counters.rejections + 1)
                note = Note("rejected", loop.round, f"{kind}: {message}")
                if counters.rejections >= config.rejection_cap:
                    end_reason = "rejection_cap"
            case other:
                raise ValueError(f"record_error_obs got {other!r}")
        return record_step(
            base,
            replace(loop, counters=counters),
            apply_note(_current(loop), note),
            end_reason,
        )

    def loop_guards(loop: LoopState) -> Update:
        if caps.repeated(loop.history, registry, config):
            return {"end_reason": "repeated_query"}
        if (
            isinstance(loop.validation, Rejection)
            and loop.validation.kind == "budget_exceeded"
            and checks.budget_blocks_boundary(_current(loop), config) is not None
        ):
            return {"end_reason": "query_budget"}
        return {"end_reason": caps.hit(loop.counters, config)}

    def after_parse(loop: LoopState) -> Literal["record_error_obs", "validate_action"]:
        if isinstance(loop.validation, ParseFailure):
            return "record_error_obs"
        return "validate_action"

    def after_validate(loop: LoopState) -> Literal["record_error_obs", "verifier"]:
        if isinstance(loop.validation, Rejection):
            return "record_error_obs"
        return "verifier"

    def route(loop: LoopState) -> Literal["completion_checks", "execute_query"]:
        match decisions.route(_accepted(loop)):
            case decisions.Finish():
                return "completion_checks"
            case decisions.Query():
                return "execute_query"
            case _ as unreachable:
                assert_never(unreachable)

    def apply(update: Update) -> None:
        nonlocal current_loop
        current_loop = replace(current_loop, loop=replace(current_loop.loop, **update))

    node: Node = entry
    while True:
        current: Node = node
        match current:
            case "initialize":
                current_loop = initialize_node(current_loop)
                node = "render_context"
            case "render_context":
                current_loop = render_context_node(current_loop)
                node = "llm_call"
            case "llm_call":
                apply(llm_call(current_loop))
                node = "parse"
            case "parse":
                apply(parse(current_loop.loop))
                node = after_parse(current_loop.loop)
            case "validate_action":
                apply(validate_action(current_loop.loop))
                node = after_validate(current_loop.loop)
            case "verifier":
                apply(verifier(current_loop.loop))
                node = route(current_loop.loop)
            case "execute_query":
                apply(execute_query(current_loop.loop))
                node = "update_state"
            case "update_state":
                apply(update_state(current_loop.loop))
                node = "write_step"
            case "write_step":
                apply(write_step(current_loop.loop))
                node = "loop_guards"
            case "completion_checks":
                apply(completion_checks(current_loop.loop))
                if current_loop.loop.end_reason is not None:
                    return current_loop
                node = "loop_guards"
            case "record_error_obs":
                apply(record_error_obs(current_loop.loop))
                if current_loop.loop.end_reason is not None:
                    return current_loop
                node = "loop_guards"
            case "loop_guards":
                apply(loop_guards(current_loop.loop))
                if current_loop.loop.end_reason is not None:
                    return current_loop
                node = "render_context"
            case _ as unreachable:
                assert_never(unreachable)


def _final_transcript(env: TranscriptEnv, final: TranscriptLoop) -> None:
    """Record the transcript with the last round appended, and its size."""
    transcript = final.transcript
    if transcript is None:
        raise ValueError("The run ended without a transcript")
    loop = final.loop
    result = replace(round_result(loop, _current(loop)), end_reason=loop.end_reason)
    transcript = append(
        transcript,
        loop.round,
        result.reply,
        tool_output(result, env.base.run_dir, env.transcript_config),
    )
    messages = transcript.messages()
    write_messages(env.base.run_dir / "transcript/final.json", messages)
    write_text(
        env.base.run_dir / "transcript/summary.txt",
        (
            f"rounds {loop.round}\n"
            f"compactions {transcript.compactions}\n"
            f"final_messages {len(messages)}\n"
            f"final_estimated_tokens {estimate_tokens(messages)}\n"
            f"summarizer {env.summarizer.name}\n"
        ),
    )


def run(
    config: RunConfig,
    transcript_config: TranscriptConfig,
    task: TaskInput,
    model: TranscriptModelAdapter,
    summarizer: Summarizer,
    verifier: VerifierAdapter,
    client: DataClient,
    run_dir: Path,
    execution_source: ExecutionSource,
) -> RunResult:
    """Register the tools, then run the loop with the transcript method until a typed end."""
    prepare_run_dir(run_dir)
    started_at = datetime.now(UTC).isoformat()
    tools = client.list_tools()
    base = RunEnv(
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
    env = TranscriptEnv(base, model, summarizer, transcript_config)
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    initial = TranscriptLoop(
        LoopState(
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
        ),
        None,
    )
    final = run_rounds(env, initial, "initialize")
    _final_transcript(env, final)
    write_text(
        run_dir / "transcript/config.txt",
        (
            f"context_method transcript\n"
            f"output_cap_bytes {transcript_config.output_cap_bytes}\n"
            f"compact_threshold_tokens {transcript_config.compact_threshold_tokens}\n"
            f"keep_recent_rounds {transcript_config.keep_recent_rounds}\n"
        ),
    )
    return finish_run(base, run_id, final.loop, started_at, resumed_from=None)
