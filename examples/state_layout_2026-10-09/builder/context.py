"""Text rendered from State for the model. Every number comes from State.

The prefix (skill, task, geography, areas, actions, completion checks) does not
change during a run. The variable part describes progress, evidence, feedback
and what is allowed now.

The builder reads one State object. Persistence assembles it from the snapshot
(state_NN.json) and the geometry file the snapshot names (geography.json):

- Known geography and Areas come from the snapshot's geography section. No
  coordinate is rendered; the model never reads geometry.
- Investigation progress, Coverage observations and the per-cell lines come
  from the count-only summaries.
- The drill-down rows and the returned-location counts come from the coverage
  table, which holds every queried location with every cell and its signal.
"""

import json
from importlib.resources import files
from typing import Protocol, assert_never

from outage_poc.models import (
    ActionSpec,
    AreaId,
    Note,
    ParameterSpec,
    Rendered,
    RunConfig,
    StepDigest,
)

from state_model import (
    STUDY_AREA,
    AreaEntry,
    AreaSummary,
    CellSummary,
    CoverageEntry,
    GeoObjectEntry,
    State,
    allowed_actions,
    backup_candidates,
    budget_blocks_boundary,
    current_phase,
    d0_border_count,
    key_areas,
    observation_ref,
    observation_rows,
    summary_for,
)

SKILL = (
    files("outage_poc")
    .joinpath("resources/investigation_skill.txt")
    .read_text(encoding="utf-8")
)


class ActionList(Protocol):
    """What the builder needs from the registry: the joined action list."""

    @property
    def actions(self) -> tuple[ActionSpec, ...]: ...


def _number(value: float) -> str:
    return f"{value:g}"


# Prefix.


def _object_lines(item: GeoObjectEntry) -> list[str]:
    lines = [f"- {item.id} is a {item.kind}. {item.description}"]
    if item.corridor is not None:
        if item.width_m is None or item.width_m <= 0:
            raise ValueError(f"{item.id} names a corridor but no positive width.")
        lines.append(
            f"  {item.id} has a known road centerline, not an area boundary; "
            f"its query corridor is {item.corridor} (full width "
            f"{_number(item.width_m)} m)."
        )
    elif item.locations is not None:
        lines.append(
            f"  {item.id} has a known boundary and contains {item.locations} "
            "analysis grid locations."
        )
    else:
        raise ValueError(f"{item.id} has neither a location count nor a corridor.")
    return lines


def _area_line(area: AreaEntry) -> list[str]:
    match area.kind:
        case "study_area":
            return [
                (
                    f"- {area.id}: the whole study area. Resolves to "
                    f"{area.locations} analysis grid locations."
                )
            ]
        case "sub_area":
            return [
                (
                    f"- {area.id}: part of {area.parent}. Resolves to "
                    f"{area.locations} analysis grid locations."
                )
            ]
        case "corridor":
            if area.width_m is None or area.width_m <= 0:
                raise ValueError("Road corridors require a positive full width.")
            return [
                (
                    f"- {area.id}: corridor of {area.parent}. Resolves to "
                    f"{area.locations} analysis grid locations."
                ),
                (
                    "  Coverage query area: road-centerline buffer with full width "
                    f"{_number(area.width_m)} m (distance <= "
                    f"{_number(area.width_m / 2)} m from the centerline, including "
                    "round end caps)."
                ),
            ]
        case _ as unreachable:
            assert_never(unreachable)


def _parameter_text(spec: ParameterSpec, epoch: str) -> str:
    if spec.allowed_values == "task_epoch":
        return f'{spec.name}: "{epoch}"'
    if spec.set_valued and spec.choices is not None:
        values = ", ".join(f'"{choice}"' for choice in spec.choices)
        return f"{spec.name}: list of 1 to {spec.max_members} of {values}"
    if spec.choices is not None:
        return (
            f'{spec.name}: "{spec.choices[0]}"'
            if len(spec.choices) == 1
            else (f"{spec.name}: one of {', '.join(spec.choices)}")
        )
    if spec.set_valued:
        return f"{spec.name}: list of 1 to {spec.max_members} {spec.kind}"
    if spec.unit is not None:
        return f"{spec.name}: {spec.kind} {spec.unit}"
    return f"{spec.name}: {spec.kind}"


def action_line(action: ActionSpec, epoch: str) -> str:
    parameters = ", ".join(_parameter_text(spec, epoch) for spec in action.parameters)
    return f"- {action.name}({parameters}). Phase: {action.phase}. {action.description}"


def _prefix(state: State, registry: ActionList, config: RunConfig) -> str:
    task = state.task
    down = task.down_cell_id
    geography = state.geography
    lines = [
        SKILL.rstrip(),
        "",
        "Task:",
        f"Investigate the outage impact of cell {down}.",
        f"Outage time: {task.outage_time}.",
        (
            f"Coverage epoch: {task.coverage_epoch}. Coverage and KPI queries use "
            "evidence from before the outage time only."
        ),
        f"Analysis objective: {task.objective}",
        f"Site of {down}: x {_number(task.site_x_m)} m, y {_number(task.site_y_m)} m.",
        (
            "This is a synthetic investigation. Coverage describes the pre-outage network; "
            f"{down} is unavailable after the outage."
        ),
        "",
        "Known geography:",
        (
            f"Coordinate system: {state.geometry.coordinate_system}; grid spacing "
            f"{_number(state.geometry.grid_spacing_m)} m."
        ),
        (
            "Source: "
            + ", ".join(
                f"{action} observation {obs}"
                for action, obs in geography.source.items()
            )
            + "."
        ),
    ]
    for item in geography.objects:
        lines.extend(_object_lines(item))
    for relation in geography.relations:
        lines.append(
            f"- {relation.subject_id} {relation.predicate} {relation.object_id}. "
            f"Spatial evidence: {relation.evidence}"
        )
    lines.extend(
        [
            (
                "Land-use labels identify mapped types only: they do not establish "
                "population, complete network demand, or zero demand in farmland/forest."
            ),
            "",
            "Areas:",
        ]
    )
    for area in geography.areas:
        lines.extend(_area_line(area))
    lines.extend(["", "Available actions:"])
    lines.extend(
        action_line(action, task.coverage_epoch) for action in registry.actions
    )
    lines.extend(
        [
            "",
            "Completion checks, applied when you choose finish:",
            (
                f"- boundary: at most {config.boundary_d0_max_share:g} of the study "
                f"area's query-boundary locations show {down}."
            ),
            (
                f"- key_areas: {', '.join(key_areas(state))} are each fully queried, "
                "or listed in the finish gap targets as left unqueried, with the "
                "reason in the question. An area whose unqueried locations border "
                f"no queried {down} location can be left unqueried this way; one "
                "that does border such a location also fails the boundary check."
            ),
            "- labels: every queried location has exactly one coverage class.",
            (
                "- backup_load: impact.estimate is computed after the last coverage "
                "query, with both KPI indicators for every backup candidate."
            ),
            (
                f"A coverage query is refused when it would exceed the query budget "
                f"of {config.query_budget_locations} locations. When the remaining "
                f"budget cannot cover the cheapest key area that borders {down}, the "
                "boundary check can no longer be met and the run ends as query_budget."
            ),
        ]
    )
    return "\n".join(lines)


# Variable part.


def _progress_lines(summary: AreaSummary, down: str) -> list[str]:
    total = summary.queried + summary.unqueried
    lines = [
        (
            f"- {summary.area_id} contains {total} analysis grid locations: "
            f"{summary.queried} queried, {summary.unqueried} not queried."
        ),
    ]
    if summary.queried:
        if summary.valid == summary.queried:
            lines.append(f"  All {summary.queried} queried locations have valid data.")
        else:
            lines.append(
                f"  {summary.valid} queried locations have valid data; "
                f"{summary.missing} have missing data."
            )
        covered = summary.valid - summary.no_coverage
        lines.append(
            f"  Valid records: {covered} have cell coverage; "
            f"{summary.no_coverage} have no cell coverage; "
            f"{summary.other_cells_only} have other cells but no {down}."
        )
    return lines


def _cell_of(summary: AreaSummary, cell_id: str) -> CellSummary | None:
    matches = [cell for cell in summary.cells if cell.cell_id == cell_id]
    if len(matches) > 1:
        raise ValueError(f"{summary.area_id} lists {cell_id} twice.")
    return matches[0] if matches else None


def _cell_lines(summary: AreaSummary, down: str) -> list[str]:
    """Every cell the area's valid records list: where present, strongest, with the down cell."""
    lines: list[str] = []
    for cell in summary.cells:
        if cell.cell_id == down:
            lines.append(
                f"  {down} is the strongest cell at {cell.strongest} "
                f"of these {cell.present} locations."
            )
            continue
        lines.append(
            f"  {cell.cell_id} is present at {cell.present} of the {summary.valid} "
            f"valid locations, strongest at {cell.strongest}, together with "
            f"{down} at {cell.with_down_cell}; RSRP "
            f"{_number(cell.rsrp_min_dbm)} to {_number(cell.rsrp_max_dbm)} dBm."
        )
    return lines


def _coverage_lines(summary: AreaSummary, down: str) -> list[str]:
    if not summary.queried:
        return [f"- {summary.area_id}: coverage is unknown; no locations queried."]
    lines = [
        (
            f"- {summary.area_id}: {down} is present at "
            f"{summary.down_cell_present} of the {summary.queried} queried locations."
        )
    ]
    down_cell = _cell_of(summary, down)
    if (down_cell is None) != (summary.down_cell_present == 0):
        raise ValueError(
            f"{summary.area_id}: down-cell count and per-cell summary disagree."
        )
    if down_cell is not None:
        lines.append(
            "  Its RSRP at these locations ranges from "
            f"{_number(down_cell.rsrp_min_dbm)} to "
            f"{_number(down_cell.rsrp_max_dbm)} dBm."
        )
    lines.extend(_cell_lines(summary, down))
    if summary.boundary:
        lines.append(
            "  Along the query boundary facing the unqueried interior, "
            f"{down} is present at {summary.boundary_with_down_cell} "
            f"of {summary.boundary} boundary locations "
            f"({summary.boundary - summary.boundary_missing} valid, "
            f"{summary.boundary_missing} missing)."
        )
    else:
        lines.append("  No queried/unqueried interior boundary exists in this area.")
    if summary.unqueried:
        lines.append("  Coverage in the unqueried interior remains unknown.")
    if summary.missing:
        lines.append("  Coverage at locations with missing data also remains unknown.")
    return lines


def _open_key_area_lines(state: State) -> list[str]:
    """Key areas with unqueried locations, and whether those border observed down-cell
    coverage: the facts the key-area completion rule and a finish decision rest on."""
    down = state.task.down_cell_id
    open_areas = [a for a in key_areas(state) if summary_for(state, a).unqueried]
    if not open_areas:
        return ["", "Key areas with unqueried locations: none."]
    lines = ["", "Key areas with unqueried locations:"]
    for area_id in open_areas:
        lines.append(
            f"- {area_id}: {summary_for(state, area_id).unqueried} unqueried "
            f"locations; {d0_border_count(state, area_id)} of them border a "
            f"queried location where {down} is present."
        )
    return lines


def _row_line(entry: CoverageEntry) -> str:
    if entry.status == "missing":
        return f"- {entry.grid_id}: missing data"
    if not entry.cells:
        return f"- {entry.grid_id}: valid, no cell coverage"
    signals = ", ".join(
        f"{s.cell_id} {_number(s.rsrp_dbm)} dBm / {_number(s.rsrq_db)} dB"
        for s in entry.cells
    )
    traffic = entry.down_cell_traffic_mbps
    if traffic is None:
        raise ValueError(f"{entry.grid_id}: a valid record needs a traffic value.")
    return (
        f"- {entry.grid_id}: valid, {signals}; synthetic down-cell traffic "
        f"{_number(traffic)} Mbps"
    )


def _inspection_lines(state: State, last_round: int) -> list[str]:
    """The drill-down rows, shown in the round right after the request only.
    The rows are read from the coverage table in grid order."""
    inspection = state.inspection
    if inspection is None or inspection.step_index != last_round:
        return []
    rows = observation_rows(state, inspection.observation_id)
    shown = rows[inspection.first_row : inspection.first_row + inspection.row_count]
    area = observation_ref(state, inspection.observation_id).area_id
    last = inspection.first_row + len(shown) - 1
    return [
        "",
        (
            f"Inspected rows {inspection.first_row} to {last} of {len(rows)} in "
            f"{inspection.observation_id} (area {area}), in grid order:"
        ),
        *(_row_line(entry) for entry in shown),
    ]


def _impact_lines(state: State) -> list[str]:
    down = state.task.down_cell_id
    candidates = backup_candidates(state)
    lines = [
        (
            f"Backup candidates seen in coverage records: {', '.join(candidates)}."
            if candidates
            else "No backup candidate has been seen in a coverage record yet."
        )
    ]
    for cell in summary_for(state, STUDY_AREA).cells:
        if cell.cell_id == down:
            continue
        lines.append(
            f"- {cell.cell_id}: present at {cell.present} queried locations, "
            f"together with {down} at {cell.with_down_cell}, strongest at "
            f"{cell.strongest}; RSRP {_number(cell.rsrp_min_dbm)} to "
            f"{_number(cell.rsrp_max_dbm)} dBm."
        )
    if state.kpis:
        lines.append("KPI records:")
        lines.extend(
            f"- {kpi.cell_id} ({kpi.window}): {kpi.indicator} "
            f"{_number(kpi.value)} {kpi.unit}."
            for kpi in state.kpis
        )
    impact = state.impact
    if impact is None:
        lines.append(
            "Backup selection, traffic transfer, and load estimation have not been performed."
        )
        return lines
    lines.extend(
        [
            (
                f"Scope: {impact.parameters.scope_area_id}, "
                f"{len(impact.scope_queried_ids)} queried locations; "
                f"{len(impact.excluded_unqueried_ids)} unqueried and "
                f"{len(impact.excluded_missing_ids)} missing locations excluded."
            ),
            (
                f"Observed target locations: {impact.target_location_count}; synthetic "
                f"target traffic: {_number(impact.total_target_traffic_mbps)} Mbps; "
                f"unserved: {_number(impact.unserved_traffic_mbps)} Mbps."
            ),
            f"Backup selection: {impact.parameters.selection_rule}",
            (
                f"Eligibility thresholds: RSRP >= {_number(impact.parameters.minimum_rsrp_dbm)} "
                f"dBm and RSRQ >= {_number(impact.parameters.minimum_rsrq_db)} dB."
            ),
            f"Load formula: {impact.parameters.load_formula}",
            "Location share and traffic share have separate denominators and need not agree.",
        ]
    )
    for backup in impact.backup_loads:
        lines.append(
            f"- {backup.cell_id}: {backup.assigned_locations} assigned locations "
            f"({backup.location_share:.2%} of observed target locations), "
            f"{_number(backup.transferred_mbps)} Mbps transferred "
            f"({backup.traffic_share:.2%} of observed target traffic); "
            f"baseline PRB {_number(backup.baseline_prb_percent)}%, "
            f"capacity {_number(backup.capacity_mbps)} Mbps, "
            f"estimated PRB {_number(backup.estimated_prb_percent)}%; "
            f"exceeds capacity: {str(backup.exceeds_capacity).lower()}."
        )
    lines.extend(f"- Limitation: {limitation}" for limitation in impact.limitations)
    return lines


def _step_line(step: StepDigest) -> str:
    if step.decision is None:
        return f"- round {step.index}: unparsed reply; {step.outcome}"
    parameters = json.dumps(step.decision.parameters, sort_keys=True)
    return (
        f"- round {step.index}: {step.decision.action}({parameters}); "
        f"{step.decision.gap.question}; {step.outcome}"
    )


def _feedback_line(note: Note, history: tuple[StepDigest, ...]) -> str:
    """One Note, saying who reported it and about which decision."""
    decisions = {digest.index: digest.decision for digest in history}
    decision = decisions.get(note.step_index)
    action = f" ({decision.action})" if decision is not None else ""
    round_text = f"round {note.step_index}"
    match note.kind:
        case "parse_failure":
            return f"- Your reply in {round_text} did not parse: {note.text}"
        case "rejected":
            return f"- Your decision in {round_text}{action} was rejected: {note.text}"
        case "concern":
            return (
                f"- The verifier questioned your decision in {round_text}{action}; "
                f"its reason, which may be wrong: {note.text}"
            )
        case "unmet":
            return f"- Your finish in {round_text} was refused: {note.text}"
        case "query_failed":
            return f"- A query in {round_text}{action} failed: {note.text}"
        case _ as unreachable:
            assert_never(unreachable)


def _provenance_lines(state: State) -> list[str]:
    returned: dict[str, int] = {}
    for entry in state.coverage.values():
        returned[entry.observation] = returned.get(entry.observation, 0) + 1
    lines = ["", "Evidence provenance:"]
    for observation in state.observations:
        lines.append(
            f"- {observation.id}: {observation.path}; area {observation.area_id}; "
            f"{returned.get(observation.id, 0)} returned locations."
        )
    lines.append(
        "The state coverage table maps each queried location to its observation, "
        "its cells and their signal levels; inspect_observation shows those rows."
    )
    return lines


def _variable(
    state: State,
    registry: ActionList,
    config: RunConfig,
    history: tuple[StepDigest, ...],
) -> str:
    down = state.task.down_cell_id
    areas: list[AreaId] = [area.id for area in state.geography.areas]
    lines = [
        "Investigation progress:",
        "Counts are per area; overlapping areas must not be added together.",
    ]
    for area_id in areas:
        lines.extend(_progress_lines(summary_for(state, area_id), down))
    lines.extend(_open_key_area_lines(state))
    lines.extend(
        [
            "",
            "Coverage observations:",
            (
                "Query boundary rule: within each area, a queried grid location is on "
                "the query boundary if at least one of its four orthogonal grid "
                "neighbors in the same area is unqueried. Signal presence never "
                "selects the boundary."
            ),
            "Missing boundary records are unknown, not target-absent observations.",
        ]
    )
    for area_id in areas:
        lines.extend(_coverage_lines(summary_for(state, area_id), down))
    lines.extend(_inspection_lines(state, len(history)))
    lines.extend(["", "Impact and backup analysis:"])
    lines.extend(_impact_lines(state))
    lines.extend(["", "Remaining unknowns:"])
    lines.extend(f"- {unknown}" for unknown in state.unknowns)
    allowed = ", ".join(a.name for a in allowed_actions(registry.actions, state))
    spent = summary_for(state, STUDY_AREA).queried
    lines.extend(
        [
            "",
            f"Actions allowed now (phase {current_phase(state)}): {allowed}.",
            (
                f"Query budget: {spent} of {config.query_budget_locations} locations "
                f"used; {config.query_budget_locations - spent} remain. A coverage "
                "query costs the locations it adds for the first time."
            ),
        ]
    )
    blocked = budget_blocks_boundary(state, config)
    if blocked is not None:
        lines.append(
            f"Budget limit reached for completion: {blocked}. A finish now ends the "
            "run as query_budget, which is not complete."
        )
    lines.extend(_provenance_lines(state))
    if config.include_recent_steps:
        lines.extend(["", "Recent steps:"])
        recent = history[-config.recent_steps :] if config.recent_steps else ()
        lines.extend(_step_line(step) for step in recent)
        if not recent:
            lines.append("- No steps yet.")
    # Feedback comes last, next to the request, so the model reads it before deciding.
    next_round = len(history) + 1
    recent_notes = [note for note in state.notes if note.step_index >= next_round - 2]
    lines.extend(["", "Feedback from the last two rounds:"])
    lines.extend(_feedback_line(note, history) for note in recent_notes)
    if not recent_notes:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "Reply with your next decision in the three-line decision format of the skill.",
            "",
        ]
    )
    return "\n".join(lines)


def render_context(
    state: State,
    registry: ActionList,
    config: RunConfig,
    history: tuple[StepDigest, ...],
) -> Rendered:
    """Describe facts, scope, evidence and feedback without choosing an action."""
    return Rendered(
        _prefix(state, registry, config), _variable(state, registry, config, history)
    )
