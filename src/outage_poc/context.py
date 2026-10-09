"""Text rendered from State for the model. Every number comes from State.

The prefix (skill, task, geography, areas, actions) does not change during a
run. The variable part describes progress, evidence, feedback and what is
allowed now.
"""

import json
from importlib.resources import files
from typing import assert_never

from outage_poc.checks import budget_blocks_boundary
from outage_poc.models import (
    ActionSpec,
    CoverageRecord,
    Note,
    ParameterSpec,
    RegionSummary,
    Rendered,
    RunConfig,
    State,
    StepDigest,
)
from outage_poc.registry import Registry, current_phase
from outage_poc.state import (
    STUDY_AREA,
    backup_candidates,
    d0_border_count,
    key_areas,
    summary_for,
)

SKILL = (
    files("outage_poc")
    .joinpath("resources/investigation_skill.txt")
    .read_text(encoding="utf-8")
)


def _number(value: float) -> str:
    return f"{value:g}"


def _region_lines(region: RegionSummary, down_cell_id: str) -> list[str]:
    total = len(region.total_ids)
    queried = len(region.queried_ids)
    valid = len(region.valid_ids)
    lines = [
        (
            f"- {region.area_id} contains {total} analysis grid locations: "
            f"{queried} queried, {len(region.unqueried_ids)} not queried."
        ),
    ]
    if queried:
        if valid == queried:
            lines.append(f"  All {queried} queried locations have valid data.")
        else:
            lines.append(
                f"  {valid} queried locations have valid data; "
                f"{len(region.missing_ids)} have missing data."
            )
        lines.append(
            f"  Valid records: {len(region.valid_covered_ids)} have cell coverage; "
            f"{len(region.no_coverage_ids)} have no cell coverage; "
            f"{len(region.other_cells_only_ids)} have other cells but no {down_cell_id}."
        )
    return lines


def _coverage_lines(region: RegionSummary, down_cell_id: str) -> list[str]:
    queried = len(region.queried_ids)
    if not queried:
        return [f"- {region.area_id}: coverage is unknown; no locations queried."]
    lines = [
        (
            f"- {region.area_id}: {down_cell_id} is present at "
            f"{len(region.target_ids)} of the {queried} queried locations."
        )
    ]
    if region.target_ids:
        if region.target_rsrp_min_dbm is None or region.target_rsrp_max_dbm is None:
            raise ValueError(
                "Target signal bounds are required for observed target cells."
            )
        lines.append(
            "  Its RSRP at these locations ranges from "
            f"{_number(region.target_rsrp_min_dbm)} to "
            f"{_number(region.target_rsrp_max_dbm)} dBm."
        )
    lines.extend(_cell_lines(region, down_cell_id))
    if region.boundary_ids:
        lines.append(
            "  Along the query boundary facing the unqueried interior, "
            f"{down_cell_id} is present at {len(region.boundary_target_ids)} "
            f"of {len(region.boundary_ids)} boundary locations "
            f"({len(region.boundary_valid_ids)} valid, "
            f"{len(region.boundary_missing_ids)} missing)."
        )
    else:
        lines.append("  No queried/unqueried interior boundary exists in this area.")
    if region.unqueried_ids:
        lines.append("  Coverage in the unqueried interior remains unknown.")
    if region.missing_ids:
        lines.append("  Coverage at locations with missing data also remains unknown.")
    return lines


def _cell_lines(region: RegionSummary, down_cell_id: str) -> list[str]:
    """Every cell the area's valid records list: where present, strongest, with the down cell."""
    lines: list[str] = []
    valid = len(region.valid_ids)
    for cell in region.cells:
        if cell.cell_id == down_cell_id:
            lines.append(
                f"  {down_cell_id} is the strongest cell at {len(cell.strongest_ids)} "
                f"of these {len(cell.present_ids)} locations."
            )
            continue
        lines.append(
            f"  {cell.cell_id} is present at {len(cell.present_ids)} of the {valid} "
            f"valid locations, strongest at {len(cell.strongest_ids)}, together with "
            f"{down_cell_id} at {len(cell.with_down_cell_ids)}; RSRP "
            f"{_number(cell.rsrp_min_dbm)} to {_number(cell.rsrp_max_dbm)} dBm."
        )
    return lines


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


def _prefix(state: State, registry: Registry, config: RunConfig) -> str:
    task = state.task
    down = task.down_cell_id
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
            f"Coordinate system: {state.coordinate_system}; grid spacing "
            f"{_number(state.grid_spacing_m)} m. Coordinates are not latitude/longitude."
        ),
    ]
    for item in state.geography:
        lines.append(f"- {item.id} is a {item.kind}. {item.description}")
        if item.geometry.kind == "polyline":
            lines.append(
                f"  {item.id} has a known road centerline, not an area boundary."
            )
        else:
            lines.append(f"  Geographic geometry is available for {item.id}.")
    for relation in state.relations:
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
    for area in state.areas:
        parent = f" Part of {area.parent_id}." if area.parent_id else ""
        lines.append(
            f"- {area.id}: {area.description} Resolves to {len(area.grid_ids)} "
            f"analysis grid locations.{parent}"
        )
        if area.geometry.kind == "buffer":
            width = area.geometry.buffer_width_m
            if width is None or width <= 0:
                raise ValueError("Road buffer areas require a positive full width.")
            lines.append(
                f"  Coverage query area: road-centerline buffer with full width "
                f"{_number(width)} m (distance <= {_number(width / 2)} m from "
                "the centerline, including round end caps)."
            )
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


def _impact_lines(state: State) -> list[str]:
    candidates = backup_candidates(state)
    lines = [
        (
            f"Backup candidates seen in coverage records: {', '.join(candidates)}."
            if candidates
            else "No backup candidate has been seen in a coverage record yet."
        )
    ]
    study = summary_for(state, STUDY_AREA)
    for cell in study.cells:
        if cell.cell_id == state.task.down_cell_id or cell.cell_id not in candidates:
            continue
        lines.append(
            f"- {cell.cell_id}: present at {len(cell.present_ids)} queried locations, "
            f"together with {state.task.down_cell_id} at {len(cell.with_down_cell_ids)}, "
            f"strongest at {len(cell.strongest_ids)}; RSRP "
            f"{_number(cell.rsrp_min_dbm)} to {_number(cell.rsrp_max_dbm)} dBm."
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


def _record_line(record: CoverageRecord) -> str:
    if record.status == "missing":
        return f"- {record.grid_id}: missing data"
    if not record.cells:
        return f"- {record.grid_id}: valid, no cell coverage"
    signals = ", ".join(
        f"{signal.cell_id} {_number(signal.rsrp_dbm)} dBm / {_number(signal.rsrq_db)} dB"
        for signal in record.cells
    )
    return (
        f"- {record.grid_id}: valid, {signals}; synthetic down-cell traffic "
        f"{_number(record.down_cell_traffic_mbps or 0.0)} Mbps"
    )


def _inspection_lines(state: State, last_round: int) -> list[str]:
    """The drill-down rows, shown in the round right after the request only."""
    inspection = state.inspection
    if inspection is None or inspection.step_index != last_round:
        return []
    last = inspection.first_row + len(inspection.records) - 1
    return [
        "",
        (
            f"Inspected rows {inspection.first_row} to {last} of "
            f"{inspection.total_rows} in {inspection.observation_id} "
            f"(area {inspection.area_id}), in grid order:"
        ),
        *(_record_line(record) for record in inspection.records),
    ]


def _open_key_area_lines(state: State) -> list[str]:
    """Key areas with unqueried locations, and whether those border observed down-cell
    coverage: the facts the key-area completion rule and a finish decision rest on."""
    down = state.task.down_cell_id
    open_areas = [
        area_id
        for area_id in key_areas(state)
        if summary_for(state, area_id).unqueried_ids
    ]
    if not open_areas:
        return ["", "Key areas with unqueried locations: none."]
    lines = ["", "Key areas with unqueried locations:"]
    for area_id in open_areas:
        unqueried = len(summary_for(state, area_id).unqueried_ids)
        bordering = d0_border_count(state, area_id)
        lines.append(
            f"- {area_id}: {unqueried} unqueried locations; {bordering} of them "
            f"border a queried location where {down} is present."
        )
    return lines


def _variable(
    state: State,
    registry: Registry,
    config: RunConfig,
    history: tuple[StepDigest, ...],
) -> str:
    down = state.task.down_cell_id
    lines = [
        "Investigation progress:",
        "Counts are per area; overlapping areas must not be added together.",
    ]
    for region in state.regions:
        lines.extend(_region_lines(region, down))
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
    for region in state.regions:
        lines.extend(_coverage_lines(region, down))
    lines.extend(_inspection_lines(state, len(history)))
    lines.extend(["", "Impact and backup analysis:"])
    lines.extend(_impact_lines(state))
    lines.extend(["", "Remaining unknowns:"])
    lines.extend(f"- {unknown}" for unknown in state.unknowns)
    allowed = ", ".join(action.name for action in registry.allowed(state))
    spent = len(summary_for(state, STUDY_AREA).queried_ids)
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
    lines.extend(["", "Evidence provenance:"])
    for observation in state.observations:
        lines.append(
            f"- {observation.observation_id}: {observation.path}; "
            f"area {observation.area_id}; {len(observation.grid_ids)} returned locations."
        )
    lines.append(
        "The state evidence index maps each queried location to its observation; "
        "full cell lists and measurements remain in those query results."
    )
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
    registry: Registry,
    config: RunConfig,
    history: tuple[StepDigest, ...],
) -> Rendered:
    """Describe facts, scope, evidence and feedback without choosing an action."""
    return Rendered(
        _prefix(state, registry, config), _variable(state, registry, config, history)
    )
