"""Export one run as a JavaScript data file for the workflow UI.

Run with: uv run python -m outage_poc.export_ui --run outputs/run_recorded --out <ui>/js/data/case.js

The UI is a static page, so it cannot fetch JSON from disk. This module reads the
trace, States, contexts and observations of one run and writes them as one
`window.OUTAGE_CASE = {...}` assignment. It copies facts; it does not compute new
ones. Per step it carries the decision, the validation and review outcomes, the
Notes the step added, and the counters; per run, the typed end reason.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal, TypedDict

from outage_poc.models import (
    CoverageObservation,
    ImpactAnalysis,
    Member,
    Observation,
    RegionSummary,
    State,
    Step,
    Trace,
)
from outage_poc.persistence import read_json, read_observation, read_state, read_step
from outage_poc.state import STUDY_AREA, summary_for

GridClass = Literal["u", "m", "e", "o", "t"]


class GridExport(TypedDict):
    columns: int
    rows: int
    spacing_m: float
    ids: list[str]
    x_m: list[float]
    y_m: list[float]


class RegionExport(TypedDict):
    area_id: str
    total: int
    queried: int
    unqueried: int
    valid: int
    missing: int
    covered: int
    no_coverage: int
    other_only: int
    target: int
    rsrp_min: float | None
    rsrp_max: float | None
    boundary: int
    boundary_target: int
    boundary_valid: int
    boundary_missing: int
    boundary_ids: list[str]


class BackupLoadExport(TypedDict):
    cell_id: str
    assigned_locations: int
    location_share: float
    transferred_mbps: float
    traffic_share: float
    baseline_prb_percent: float
    capacity_mbps: float
    estimated_prb_percent: float
    exceeds_capacity: bool


class ImpactExport(TypedDict):
    scope_area_id: str
    scope_queried: int
    excluded_missing: int
    excluded_unqueried: int
    target_location_count: int
    total_target_traffic_mbps: float
    unserved_traffic_mbps: float
    minimum_rsrp_dbm: float
    minimum_rsrq_db: float
    selection_rule: str
    load_formula: str
    assignment: dict[str, str]
    backup_loads: list[BackupLoadExport]
    limitations: list[str]


class NoteExport(TypedDict):
    kind: str
    round: int
    text: str


class StateExport(TypedDict):
    id: str
    classes: str
    regions: list[RegionExport]
    unknowns: list[str]
    observation_ids: list[str]
    cells_seen: list[str]
    kpis: list[dict[str, object]]
    notes: list[NoteExport]
    impact: ImpactExport | None
    context: str
    context_bytes: int


class MemberExport(TypedDict):
    member_id: str
    status: str
    result_status: str | None
    # Coverage members only: counts over the member's records.
    requested: int | None
    valid: int | None
    missing: int | None
    target: int | None
    rsrp_min: float | None
    rsrp_max: float | None
    bytes: int | None


class ObservationExport(TypedDict):
    id: str
    action: str
    status: str
    duration_ms: int
    members: list[MemberExport]


class DecisionExport(TypedDict):
    action: str
    parameters: dict[str, object]
    gap_targets: list[str]
    gap_question: str


class StepExport(TypedDict):
    id: str
    index: int
    execution_source: str
    decision: DecisionExport | None
    raw_output: str
    validation: str
    validation_message: str | None
    review: str
    review_reason: str | None
    notes_added: list[NoteExport]
    outcome: str
    observation: ObservationExport | None
    counters: dict[str, object]
    state_before: str
    state_after: str
    input_bytes: int


class RunExport(TypedDict):
    run_id: str
    end_reason: str
    config: dict[str, object]


class CaseExport(TypedDict):
    task: dict[str, object]
    coordinate_system: str
    grid: GridExport
    geography: list[dict[str, object]]
    relations: list[dict[str, object]]
    areas: list[dict[str, object]]
    prefix: str
    run: RunExport
    states: list[StateExport]
    steps: list[StepExport]


def _grid(state: State) -> GridExport:
    points = sorted(state.grid, key=lambda point: (point.row, point.column))
    columns = max(point.column for point in points) + 1
    rows = max(point.row for point in points) + 1
    if columns * rows != len(points):
        raise ValueError("Grid is not a full rectangle")
    return GridExport(
        columns=columns,
        rows=rows,
        spacing_m=state.grid_spacing_m,
        ids=[point.id for point in points],
        x_m=[point.x_m for point in points],
        y_m=[point.y_m for point in points],
    )


def _region(region: RegionSummary) -> RegionExport:
    return RegionExport(
        area_id=region.area_id,
        total=len(region.total_ids),
        queried=len(region.queried_ids),
        unqueried=len(region.unqueried_ids),
        valid=len(region.valid_ids),
        missing=len(region.missing_ids),
        covered=len(region.valid_covered_ids),
        no_coverage=len(region.no_coverage_ids),
        other_only=len(region.other_cells_only_ids),
        target=len(region.target_ids),
        rsrp_min=region.target_rsrp_min_dbm,
        rsrp_max=region.target_rsrp_max_dbm,
        boundary=len(region.boundary_ids),
        boundary_target=len(region.boundary_target_ids),
        boundary_valid=len(region.boundary_valid_ids),
        boundary_missing=len(region.boundary_missing_ids),
        boundary_ids=list(region.boundary_ids),
    )


def _classes(state: State, grid_ids: list[str]) -> str:
    """One character per grid location, in grid order, from the Study_area summary."""
    study = summary_for(state, STUDY_AREA)
    sets: dict[GridClass, set[str]] = {
        "u": set(study.unqueried_ids),
        "m": set(study.missing_ids),
        "e": set(study.no_coverage_ids),
        "o": set(study.other_cells_only_ids),
        "t": set(study.target_ids),
    }
    out: list[str] = []
    for grid_id in grid_ids:
        matches = [name for name, members in sets.items() if grid_id in members]
        if len(matches) != 1:
            raise ValueError(f"Grid {grid_id} has {len(matches)} classifications")
        out.append(matches[0])
    return "".join(out)


def _impact(impact: ImpactAnalysis | None) -> ImpactExport | None:
    if impact is None:
        return None
    parameters = impact.parameters
    return ImpactExport(
        scope_area_id=parameters.scope_area_id,
        scope_queried=len(impact.scope_queried_ids),
        excluded_missing=len(impact.excluded_missing_ids),
        excluded_unqueried=len(impact.excluded_unqueried_ids),
        target_location_count=impact.target_location_count,
        total_target_traffic_mbps=impact.total_target_traffic_mbps,
        unserved_traffic_mbps=impact.unserved_traffic_mbps,
        minimum_rsrp_dbm=parameters.minimum_rsrp_dbm,
        minimum_rsrq_db=parameters.minimum_rsrq_db,
        selection_rule=parameters.selection_rule,
        load_formula=parameters.load_formula,
        assignment={
            item.grid_id: "none" if item.backup_cell_id is None else item.backup_cell_id
            for item in impact.assignments
        },
        backup_loads=[
            BackupLoadExport(
                cell_id=load.cell_id,
                assigned_locations=load.assigned_locations,
                location_share=load.location_share,
                transferred_mbps=load.transferred_mbps,
                traffic_share=load.traffic_share,
                baseline_prb_percent=load.baseline_prb_percent,
                capacity_mbps=load.capacity_mbps,
                estimated_prb_percent=load.estimated_prb_percent,
                exceeds_capacity=load.exceeds_capacity,
            )
            for load in impact.backup_loads
        ],
        limitations=list(impact.limitations),
    )


def _notes(state: State, since: int) -> list[NoteExport]:
    return [
        NoteExport(kind=note.kind, round=note.step_index, text=note.text)
        for note in state.notes[since:]
    ]


def _state(run: Path, state: State, grid_ids: list[str]) -> StateExport:
    context = (run / "contexts" / f"{state.id}.txt").read_text(encoding="utf-8")
    return StateExport(
        id=state.id,
        classes=_classes(state, grid_ids),
        regions=[_region(region) for region in state.regions],
        unknowns=list(state.unknowns),
        observation_ids=[link.observation_id for link in state.observations],
        cells_seen=list(state.cells_seen),
        kpis=[asdict(record) for record in state.kpis],
        notes=_notes(state, 0),
        impact=_impact(state.impact),
        context=context,
        context_bytes=len(context.encode("utf-8")),
    )


def _member(run: Path, member: Member, down_cell_id: str) -> MemberExport:
    export = MemberExport(
        member_id=member.member_id,
        status=member.status,
        result_status=member.result_status,
        requested=None,
        valid=None,
        missing=None,
        target=None,
        rsrp_min=None,
        rsrp_max=None,
        bytes=None,
    )
    if member.result_status is None or member.records_path is None:
        return export
    observation: CoverageObservation = read_observation(run / member.records_path)
    valid = [record for record in observation.records if record.status == "valid"]
    rsrp = [
        signal.rsrp_dbm
        for record in valid
        for signal in record.cells
        if signal.cell_id == down_cell_id
    ]
    export.update(
        requested=len(observation.parameters.grid_ids),
        valid=len(valid),
        missing=len(observation.records) - len(valid),
        target=len(rsrp),
        rsrp_min=min(rsrp) if rsrp else None,
        rsrp_max=max(rsrp) if rsrp else None,
        bytes=(run / member.records_path).stat().st_size,
    )
    return export


def _observation(
    run: Path, observation: Observation | None, down_cell_id: str
) -> ObservationExport | None:
    if observation is None:
        return None
    return ObservationExport(
        id=observation.id,
        action=observation.action,
        status=observation.status,
        duration_ms=observation.duration_ms,
        members=[_member(run, member, down_cell_id) for member in observation.members],
    )


def _step(run: Path, step: Step, down_cell_id: str) -> StepExport:
    decision = step.decision
    return StepExport(
        id=step.id,
        index=step.index,
        execution_source=step.execution_source,
        decision=(
            None
            if decision is None
            else DecisionExport(
                action=decision.action,
                parameters=decision.parameters,
                gap_targets=list(decision.gap.targets),
                gap_question=decision.gap.question,
            )
        ),
        raw_output=step.raw_output,
        validation=step.validation,
        validation_message=step.validation_message,
        review=step.review,
        review_reason=step.review_reason,
        notes_added=_notes(step.state_after, len(step.state_before.notes)),
        outcome=step.outcome,
        observation=_observation(run, step.observation, down_cell_id),
        counters=dict(asdict(step.counters)),
        state_before=step.state_before.id,
        state_after=step.state_after.id,
        input_bytes=(run / step.context).stat().st_size,
    )


def export_case(run: Path) -> CaseExport:
    trace = read_json(Trace, run / "trace.json")
    initial = read_state(run / trace.initial_state)
    grid = _grid(initial)
    steps = [read_step(run / path) for path in trace.steps]
    # States in order: State 0, a corrected State where a run resumed, each Step's State.
    states: dict[str, State] = {initial.id: initial}
    for step in steps:
        states.setdefault(step.state_before.id, step.state_before)
        states[step.state_after.id] = step.state_after
    down_cell_id = initial.task.down_cell_id
    exported = [_step(run, step, down_cell_id) for step in steps]
    return CaseExport(
        task=dict(asdict(initial.task)),
        coordinate_system=initial.coordinate_system,
        grid=grid,
        geography=[asdict(item) for item in initial.geography],
        relations=[asdict(item) for item in initial.relations],
        areas=[
            {
                "id": area.id,
                "description": area.description,
                "geometry_kind": area.geometry.kind,
                "buffer_width_m": area.geometry.buffer_width_m,
                "grid_count": len(area.grid_ids),
                "grid_ids": [] if area.id == STUDY_AREA else list(area.grid_ids),
                "parent_id": area.parent_id,
            }
            for area in initial.areas
        ],
        prefix=(run / trace.prefix).read_text(encoding="utf-8"),
        run=RunExport(
            run_id=trace.run_id,
            end_reason=trace.end_reason,
            config=dict(asdict(trace.config)),
        ),
        states=[_state(run, state, grid["ids"]) for state in states.values()],
        steps=exported,
    )


def write_case_js(case: CaseExport, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(case, indent=1, allow_nan=False)
    out.write_text(
        "/* Generated by outage_poc.export_ui from a recorded run. Do not edit. */\n"
        f"window.OUTAGE_CASE = {body};\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a recorded run for the UI.")
    parser.add_argument("--run", required=True, type=Path, help="Run output directory")
    parser.add_argument("--out", required=True, type=Path, help="Target case.js path")
    arguments = parser.parse_args()
    run = arguments.run
    out = arguments.out
    if not isinstance(run, Path) or not isinstance(out, Path):
        raise TypeError("--run and --out must be filesystem paths")
    case = export_case(run)
    write_case_js(case, out)
    print(
        f"Exported {len(case['steps'])} steps and {len(case['states'])} states "
        f"(end reason {case['run']['end_reason']}) to {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
