"""Parse the model's reply, validate it against the registry and State, and route it.

The parser does no repair. Validation runs four checks in order and stops at the
first failure; every message is written for the model and names the wrong thing
and the right things.
"""

import json
from dataclasses import dataclass
from math import isfinite
from typing import assert_never, cast

from outage_poc.models import (
    Accepted,
    ActionSpec,
    AreaId,
    Decision,
    Gap,
    ParameterSpec,
    ParameterValue,
    ParseFailure,
    Rejection,
    State,
)
from outage_poc.registry import Registry, precondition_failure
from outage_poc.state import STUDY_AREA, baseline_kpis, key_areas, summary_for

FINISH = "finish"
DECISION_FORMAT = (
    "action: <action name>\n"
    "parameters: <JSON object with the action's parameters>\n"
    'gap: <JSON object with "targets" (list of the area or cell ids the question is '
    "about; for finish, the key areas you leave unqueried, empty when there are "
    'none) and "question" (one sentence; for finish, the reason)>'
)
_LABELS = ("action:", "parameters:", "gap:")


@dataclass(frozen=True)
class Query:
    accepted: Accepted


@dataclass(frozen=True)
class Finish:
    # The reason for finishing is the gap question.
    gap: Gap


@dataclass(frozen=True)
class _Invalid:
    message: str


def _failure(problem: str) -> ParseFailure:
    return ParseFailure(
        f"{problem}. Reply with exactly three lines:\n{DECISION_FORMAT}"
    )


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not a JSON number")


def _json_object(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def parse(raw: str) -> Decision | ParseFailure:
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    for index, label in enumerate(_LABELS):
        if index >= len(lines):
            return _failure(
                f"Line {index + 1} must start with {label!r}, but the reply has "
                f"only {len(lines)} non-blank lines"
            )
        if not lines[index].startswith(label):
            return _failure(
                f"Line {index + 1} must start with {label!r}; found "
                f"{lines[index][:80]!r}"
            )
    if len(lines) > len(_LABELS):
        return _failure(f"Line 4 is extra text after the gap line: {lines[3][:80]!r}")
    action = lines[0].removeprefix("action:").strip()
    if not action:
        return _failure("Line 1 names no action")
    parameters = _json_object(lines[1].removeprefix("parameters:").strip())
    if parameters is None:
        return _failure("Line 2 is not a JSON object after 'parameters:'")
    gap = _json_object(lines[2].removeprefix("gap:").strip())
    if gap is None:
        return _failure("Line 3 is not a JSON object after 'gap:'")
    if set(gap) != {"targets", "question"}:
        return _failure(
            f"Line 3 must have exactly the keys 'targets' and 'question'; found {sorted(gap)}"
        )
    targets = gap["targets"]
    question = gap["question"]
    if not isinstance(targets, list) or not all(
        isinstance(target, str) for target in cast(list[object], targets)
    ):
        return _failure("Line 3: 'targets' must be a list of strings")
    if not isinstance(question, str) or not question.strip():
        return _failure("Line 3: 'question' must be a non-empty string")
    return Decision(
        action,
        parameters,
        Gap(tuple(cast(list[str], targets)), question.strip()),
        raw,
    )


def _convert_one(spec: ParameterSpec, value: object) -> ParameterValue | _Invalid:
    """The typed value, or what is wrong with it. Uses no State."""
    match spec.kind:
        case "area_id" | "cell_id" | "observation_id" | "str":
            if spec.set_valued:
                if not isinstance(value, list) or not all(
                    isinstance(item, str) and item for item in cast(list[object], value)
                ):
                    return _Invalid(
                        f"{spec.name} must be a list of {spec.kind} strings; got {value!r}"
                    )
                members = cast(list[str], value)
                if not members or len(members) > spec.max_members:
                    return _Invalid(
                        f"{spec.name} must list 1 to {spec.max_members} members; "
                        f"got {len(members)}"
                    )
                if len(set(members)) != len(members):
                    return _Invalid(f"{spec.name} lists a member twice: {members}")
                outside = [m for m in members if spec.choices and m not in spec.choices]
                if outside:
                    return _Invalid(
                        f"{spec.name} member {outside[0]!r} is not one of "
                        f"{list(spec.choices or ())}"
                    )
                return tuple(sorted(members))
            if not isinstance(value, str) or not value:
                return _Invalid(
                    f"{spec.name} must be a non-empty string; got {value!r}"
                )
            if spec.choices is not None and value not in spec.choices:
                return _Invalid(
                    f"{spec.name} must be one of {list(spec.choices)}; got {value!r}"
                )
            return value
        case "float":
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not isfinite(value)
            ):
                unit = f" in {spec.unit}" if spec.unit else ""
                return _Invalid(
                    f"{spec.name} must be a finite number{unit}; got {value!r}"
                )
            return float(value)
        case "int":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return _Invalid(
                    f"{spec.name} must be an integer of at least 0; got {value!r}"
                )
            return value
        case _ as unreachable:
            assert_never(unreachable)


def convert(
    action: ActionSpec, parameters: dict[str, object]
) -> dict[str, ParameterValue] | str:
    """Check names and JSON types of the parameters; return typed values or a message."""
    expected = [spec.name for spec in action.parameters]
    unknown = sorted(set(parameters) - set(expected))
    if unknown:
        return f"{action.name} has no parameter {unknown[0]!r}; its parameters are {expected}"
    typed: dict[str, ParameterValue] = {}
    for spec in action.parameters:
        if spec.name not in parameters:
            return f"{action.name} needs parameter {spec.name!r}; its parameters are {expected}"
        result = _convert_one(spec, parameters[spec.name])
        if isinstance(result, _Invalid):
            return result.message
        typed[spec.name] = result
    return typed


def _members(value: ParameterValue) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, str):
        return (value,)
    raise ValueError(f"Expected ids, got {value!r}")


def _membership(
    action: ActionSpec, typed: dict[str, ParameterValue], state: State
) -> str | None:
    area_ids = [area.id for area in state.areas]
    for spec in action.parameters:
        match spec.allowed_values:
            case "any":
                continue
            case "areas_in_state":
                unknown = [m for m in _members(typed[spec.name]) if m not in area_ids]
                if unknown:
                    return (
                        f'area "{unknown[0]}" does not exist in State; known areas: '
                        f"{', '.join(area_ids)}"
                    )
            case "cells_in_state":
                unknown = [
                    m for m in _members(typed[spec.name]) if m not in state.cells_seen
                ]
                if unknown:
                    return (
                        f'cell "{unknown[0]}" has not been seen in any coverage '
                        f"record; cells seen: {', '.join(state.cells_seen)}"
                    )
            case "task_epoch":
                value = typed[spec.name]
                if value != state.task.coverage_epoch:
                    return (
                        f"{spec.name} must be the task's coverage epoch "
                        f'"{state.task.coverage_epoch}"; got {value!r}'
                    )
            case "observations_in_state":
                known = [link.observation_id for link in state.observations]
                unknown = [m for m in _members(typed[spec.name]) if m not in known]
                if unknown:
                    return (
                        f'observation "{unknown[0]}" is not in the evidence '
                        f"provenance; known observations: {', '.join(known)}"
                    )
            case _ as unreachable:
                assert_never(unreachable)
    return None


def _gap_rejection(action: ActionSpec, gap: Gap, state: State) -> Rejection | None:
    """Check 3, the targets agree with State, then check 4, the action can answer the gap.

    Every gap except a finish names its targets: the areas or cells it is about.
    A finish's targets are the key areas it leaves unqueried; empty when none.
    """
    area_ids = {area.id for area in state.areas}
    cell_ids = set(state.cells_seen)
    if action.name != FINISH and not gap.targets:
        return Rejection(
            "bad_parameter",
            f"the gap of {action.name} names no targets; list the area ids or cell "
            "ids the question is about",
        )
    for target in gap.targets:
        if target not in area_ids and target not in cell_ids:
            return Rejection(
                "bad_parameter",
                f'gap target "{target}" is neither a known area nor a cell seen; '
                f"known areas: {', '.join(sorted(area_ids))}; cells seen: "
                f"{', '.join(state.cells_seen)}",
            )
    areas = [target for target in gap.targets if target in area_ids]
    cells = [target for target in gap.targets if target not in area_ids]
    match action.result:
        case "coverage_rows":
            for target in areas:
                region = summary_for(state, AreaId(target))
                if not region.unqueried_ids and not region.missing_ids:
                    return Rejection(
                        "gap_contradicted",
                        f"gap target {target} is already answered: all "
                        f"{len(region.total_ids)} locations are queried and none "
                        "has missing data",
                    )
            if cells:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} returns coverage of areas; it cannot answer a "
                    f"question about cell {cells[0]}; use kpi.query for cell KPI",
                )
        case "kpi_rows":
            complete = set(baseline_kpis(state))
            for target in cells:
                if target in complete:
                    return Rejection(
                        "gap_contradicted",
                        f"gap target {target} is already answered: State holds both "
                        "of its pre-outage KPI indicators",
                    )
            if areas:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} returns KPI of cells; it cannot answer a question "
                    f"about area {areas[0]}; use coverage.query for areas",
                )
        case "impact":
            if gap.targets and (len(gap.targets) != 1 or cells):
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} answers a question about one scope area; the gap "
                    f"targets are {list(gap.targets)}",
                )
        case "observation_rows":
            if cells:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} shows coverage rows of an area; it cannot answer a "
                    f"question about cell {cells[0]}; use kpi.query for cell KPI",
                )
        case "none":
            open_areas = {
                area_id
                for area_id in key_areas(state)
                if summary_for(state, area_id).unqueried_ids
            }
            for target in gap.targets:
                if target not in open_areas:
                    return Rejection(
                        "gap_contradicted",
                        f"finish lists {target} as left unqueried, but the key areas "
                        f"with unqueried locations are: {', '.join(sorted(open_areas)) or 'none'}",
                    )
        case "cell_metadata" | "geography":
            pass
        case _ as unreachable:
            assert_never(unreachable)
    return None


def new_locations(state: State, areas: tuple[str, ...]) -> int:
    """The cost of a coverage query: study-area locations it would query for the first time."""
    queried = set(summary_for(state, STUDY_AREA).queried_ids)
    selected = {
        grid_id for area in state.areas if area.id in areas for grid_id in area.grid_ids
    }
    return len(selected - queried)


def _cost_rejection(
    action: ActionSpec, typed: dict[str, ParameterValue], state: State, budget: int
) -> Rejection | None:
    """A query whose cost would exceed the remaining budget is refused before it runs."""
    match action.cost:
        case "zero":
            return None
        case "locations_in_areas":
            spent = len(summary_for(state, STUDY_AREA).queried_ids)
            areas = _members(typed["areas"])
            cost = new_locations(state, areas)
            if spent + cost <= budget:
                return None
            each = ", ".join(
                f"{area} {new_locations(state, (area,))}" for area in areas
            )
            return Rejection(
                "budget_exceeded",
                f"{action.name}: the query would add {cost} new locations ({each}), "
                f"but only {budget - spent} of the budget of {budget} locations remain",
            )
        case _ as unreachable:
            assert_never(unreachable)


def _rows_rejection(typed: dict[str, ParameterValue], state: State) -> Rejection | None:
    """inspect_observation must start inside the observation."""
    observation = _members(typed["observation"])[0]
    first_row = typed["first_row"]
    link = next(
        link for link in state.observations if link.observation_id == observation
    )
    if isinstance(first_row, int) and first_row < len(link.grid_ids):
        return None
    return Rejection(
        "bad_parameter",
        f"first_row {first_row} is outside {observation}, which has "
        f"{len(link.grid_ids)} rows (0 to {len(link.grid_ids) - 1})",
    )


def validate(
    decision: Decision, state: State, registry: Registry, budget: int
) -> Accepted | Rejection:
    """Four checks in order: action exists; parameters; precondition and cost; gap."""
    action = registry.get(decision.action)
    if action is None:
        names = ", ".join(spec.name for spec in registry.actions)
        return Rejection(
            "unknown_action",
            f'action "{decision.action}" does not exist; known actions: {names}',
        )
    typed = convert(action, decision.parameters)
    if isinstance(typed, str):
        return Rejection("bad_parameter", typed)
    unknown_member = _membership(action, typed, state)
    if unknown_member is not None:
        return Rejection("bad_parameter", unknown_member)
    if action.result == "observation_rows":
        rows_rejection = _rows_rejection(typed, state)
        if rows_rejection is not None:
            return rows_rejection
    blocked = precondition_failure(action, state)
    if blocked is not None:
        return Rejection("precondition_unmet", f"{action.name}: {blocked}")
    if action.result == "impact":
        scope = _members(typed["scope"])[0]
        if not summary_for(state, AreaId(scope)).queried_ids:
            return Rejection(
                "precondition_unmet",
                f"{action.name}: scope area {scope} has no queried locations; "
                "query its coverage first or choose a queried scope",
            )
    cost_rejection = _cost_rejection(action, typed, state, budget)
    if cost_rejection is not None:
        return cost_rejection
    gap_rejection = _gap_rejection(action, decision.gap, state)
    if gap_rejection is not None:
        return gap_rejection
    return Accepted(action, typed, decision.gap)


def route(accepted: Accepted) -> Query | Finish:
    """Route by action: finish to the completion checks, anything else to execution."""
    if accepted.action.name == FINISH:
        return Finish(accepted.gap)
    return Query(accepted)
