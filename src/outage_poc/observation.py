"""Parse the result of each member of a call and wrap the call as one Observation.

Each member's rows are written to observations/<obs_id>_<member>.json before
State changes. Coverage rows must satisfy the coverage contract of
`validate_observation`; a violation raises.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import assert_never

from outage_poc.data_client import Rows, ToolFailure, ToolResult, ToolTimeout
from outage_poc.init import resolve_area
from outage_poc.models import (
    CoverageObservation,
    CoverageRecord,
    GridId,
    ImpactAnalysis,
    Inspection,
    KPIRecord,
    KPIRows,
    Member,
    MemberError,
    Observation,
    ObservationId,
    ObservationStatus,
    ParameterValue,
    State,
)
from outage_poc.persistence import decode, read_observation, write_json
from outage_poc.state import validate_observation

# Worst first: the status of an Observation is the worst status of its members.
_SEVERITY: tuple[ObservationStatus, ...] = (
    "timeout",
    "error",
    "missing",
    "empty",
    "ok",
)


def member_path(obs_id: ObservationId, member_id: str) -> str:
    return f"observations/{obs_id}_{member_id}.json"


def _failed(
    member_id: str, result: ToolTimeout | ToolFailure, path: str, run_dir: Path
) -> Member:
    match result:
        case ToolTimeout():
            return Member(member_id, "timeout", None, None)
        case ToolFailure(message=message):
            write_json(run_dir / path, MemberError(message))
            return Member(member_id, "error", None, path)
        case _ as unreachable:
            assert_never(unreachable)


def coverage_member(
    state: State, area_id: str, result: ToolResult, obs_id: ObservationId, run_dir: Path
) -> Member:
    """Parse one area's rows into one record per requested grid location.

    A requested location without a row has missing data. A row for a location
    that was not requested, or a second row for one location, breaks the contract.
    """
    path = member_path(obs_id, area_id)
    if not isinstance(result, Rows):
        return _failed(area_id, result, path, run_dir)
    parameters = resolve_area(state.grid, state.areas, area_id)
    rows: dict[GridId, CoverageRecord] = {}
    for row in result.rows:
        if row.get("area_id") != area_id:
            raise ValueError(
                f"coverage.query member {area_id} returned a row for {row.get('area_id')!r}"
            )
        record = decode(
            CoverageRecord,
            {key: value for key, value in row.items() if key != "area_id"},
        )
        if record.grid_id not in parameters.grid_ids or record.grid_id in rows:
            raise ValueError(
                f"coverage.query member {area_id} returned an unrequested or repeated "
                f"row for {record.grid_id}"
            )
        rows[record.grid_id] = record
    records = tuple(
        rows.get(grid_id, CoverageRecord(grid_id, "missing", (), None))
        for grid_id in parameters.grid_ids
    )
    missing = sum(record.status == "missing" for record in records)
    result_status = (
        "all_missing"
        if missing == len(records)
        else "partial_missing"
        if missing
        else "complete"
    )
    observation = CoverageObservation(
        ObservationId(f"{obs_id}_{area_id}"),
        "synthetic",
        parameters,
        result_status,
        records,
    )
    validate_observation(observation, state)
    write_json(run_dir / path, observation)
    status: ObservationStatus = "missing" if result_status == "all_missing" else "ok"
    return Member(area_id, status, result_status, path)


def kpi_member(
    cell_id: str,
    indicators: tuple[str, ...],
    result: ToolResult,
    obs_id: ObservationId,
    run_dir: Path,
) -> Member:
    path = member_path(obs_id, cell_id)
    if not isinstance(result, Rows):
        return _failed(cell_id, result, path, run_dir)
    if not result.rows:
        return Member(cell_id, "empty", None, None)
    records = tuple(decode(KPIRecord, row) for row in result.rows)
    if {record.cell_id for record in records} != {cell_id} or sorted(
        record.indicator for record in records
    ) != sorted(indicators):
        raise ValueError(
            f"kpi.query member {cell_id} returned rows for "
            f"{[(r.cell_id, r.indicator) for r in records]}, not {list(indicators)}"
        )
    write_json(run_dir / path, KPIRows(records))
    return Member(cell_id, "ok", None, path)


def inspection_member(
    state: State,
    observation_id: str,
    first_row: int,
    max_rows: int,
    step_index: int,
    obs_id: ObservationId,
    run_dir: Path,
) -> Member:
    """The drill-down: rows of one linked coverage observation, read from disk."""
    links = [
        link for link in state.observations if link.observation_id == observation_id
    ]
    if len(links) != 1:
        raise ValueError(f"{observation_id} is not linked in State")
    link = links[0]
    source = read_observation(run_dir / link.path)
    records = source.records[first_row : first_row + max_rows]
    if not records:
        raise ValueError(f"first_row {first_row} is outside {observation_id}")
    path = member_path(obs_id, observation_id)
    write_json(
        run_dir / path,
        Inspection(
            step_index,
            link.observation_id,
            link.area_id,
            first_row,
            len(source.records),
            records,
        ),
    )
    return Member(observation_id, "ok", None, path)


def impact_member(
    impact: ImpactAnalysis, obs_id: ObservationId, run_dir: Path
) -> Member:
    scope = impact.parameters.scope_area_id
    path = member_path(obs_id, scope)
    write_json(run_dir / path, impact)
    return Member(scope, "ok", None, path)


def observation_status(members: tuple[Member, ...]) -> ObservationStatus:
    if not members:
        raise ValueError("An observation needs at least one member")
    return min(
        (member.status for member in members),
        key=lambda status: _SEVERITY.index(status),
    )


def record_observation(
    obs_id: ObservationId,
    action: str,
    parameters: dict[str, ParameterValue],
    members: tuple[Member, ...],
    duration_ms: int,
    data_version: str,
    run_dir: Path,
) -> Observation:
    observation = Observation(
        id=obs_id,
        action=action,
        parameters=parameters,
        status=observation_status(members),
        members=members,
        duration_ms=duration_ms,
        recorded_at=datetime.now(UTC).isoformat(),
        data_version=data_version,
    )
    write_json(run_dir / f"observations/{obs_id}.json", observation)
    return observation
