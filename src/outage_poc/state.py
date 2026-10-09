"""Deterministic evidence accumulation; this module never reads hidden coverage."""

from dataclasses import replace
from datetime import datetime
from math import isfinite

from outage_poc.geometry import query_boundary, select_grid
from outage_poc.models import (
    KPI_UNITS,
    Area,
    AreaId,
    BackupAssignment,
    BackupLoad,
    BaselineKPI,
    CellCoverage,
    CellId,
    CoverageObservation,
    CoverageRecord,
    GeoObject,
    GridEvidence,
    GridId,
    GridPoint,
    ImpactAnalysis,
    Inspection,
    KPIRecord,
    LoadParameters,
    Note,
    ObservationId,
    ObservationLink,
    RegionSummary,
    SpatialRelation,
    State,
    Task,
)

COORDINATE_SYSTEM = (
    "synthetic local planar coordinates in metres; not latitude/longitude"
)
STUDY_AREA = AreaId("Study_area")
BACKUP_SELECTION_RULE = "strongest eligible RSRP; ties by cell ID; exclude down cell"
LOAD_FORMULA = "estimated_prb_percent = baseline_prb_percent + 100 * transferred_mbps / capacity_mbps"


def load_parameters(
    scope_area_id: AreaId, minimum_rsrp_dbm: float, minimum_rsrq_db: float
) -> LoadParameters:
    return LoadParameters(
        scope_area_id=scope_area_id,
        minimum_rsrp_dbm=minimum_rsrp_dbm,
        minimum_rsrq_db=minimum_rsrq_db,
        selection_rule=BACKUP_SELECTION_RULE,
        load_formula=LOAD_FORMULA,
    )


def summary_for(state: State, area_id: AreaId) -> RegionSummary:
    matches = [region for region in state.regions if region.area_id == area_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one summary for area {area_id!r}")
    return matches[0]


def key_areas(state: State) -> tuple[AreaId, ...]:
    """The task-relevant areas: every area initialization derived around the cell,
    except the study area itself and sub-areas such as S2_roadside."""
    return tuple(area.id for area in state.areas if area.parent_id == STUDY_AREA)


def d0_border_count(state: State, area_id: AreaId) -> int:
    """How many unqueried locations of the area share an edge with a queried
    study-area location where the down cell is present.

    A program fact for the key-area rule: an area whose unqueried locations do
    not border any observed down-cell location can be left unqueried if the
    finish names it. A border with the down cell present is also a study-area
    query-boundary location with the down cell, so the boundary rule fails there.
    """
    region = summary_for(state, area_id)
    present = set(summary_for(state, STUDY_AREA).target_ids)
    positions = {(point.column, point.row): point for point in state.grid}
    by_id = {point.id: point for point in state.grid}
    count = 0
    for grid_id in region.unqueried_ids:
        point = by_id[grid_id]
        if any(
            (neighbour := positions.get((point.column + dx, point.row + dy)))
            is not None
            and neighbour.id in present
            for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0))
        ):
            count += 1
    return count


def queried_d0_present(state: State) -> bool:
    """The backup phase starts once a queried location lists the down cell."""
    return bool(summary_for(state, STUDY_AREA).target_ids)


def backup_candidates(state: State) -> tuple[CellId, ...]:
    """Cells seen in valid records, other than the down cell."""
    return tuple(cell for cell in state.cells_seen if cell != state.task.down_cell_id)


def baseline_kpis(state: State) -> dict[CellId, BaselineKPI]:
    """Cells with both pre-outage indicators, as the values the load formula uses."""
    values = {(record.cell_id, record.indicator): record.value for record in state.kpis}
    return {
        cell: BaselineKPI(
            cell, values[(cell, "prb_utilization")], values[(cell, "capacity")]
        )
        for cell in sorted({record.cell_id for record in state.kpis})
        if (cell, "prb_utilization") in values and (cell, "capacity") in values
    }


def candidates_without_kpi(state: State) -> tuple[str, ...]:
    """One line per backup candidate that lacks a KPI indicator."""
    held = {(record.cell_id, record.indicator) for record in state.kpis}
    lines: list[str] = []
    for cell in backup_candidates(state):
        missing = [name for name in KPI_UNITS if (cell, name) not in held]
        if missing:
            lines.append(f"{cell} has no {' or '.join(missing)}")
    return tuple(lines)


def _summarize(
    area: Area,
    grid: tuple[GridPoint, ...],
    records: dict[GridId, CoverageRecord],
    evidence: dict[GridId, ObservationId],
    target_cell: CellId,
) -> RegionSummary:
    total = set(area.grid_ids)
    queried = total & records.keys()
    unqueried = total - queried
    valid = {point_id for point_id in queried if records[point_id].status == "valid"}
    missing = queried - valid
    covered = {point_id for point_id in valid if records[point_id].cells}
    target_signals = {
        point_id: signal
        for point_id in valid
        for signal in records[point_id].cells
        if signal.cell_id == target_cell
    }
    target = set(target_signals)
    rsrp = [signal.rsrp_dbm for signal in target_signals.values()]
    boundary = set(query_boundary(queried, unqueried, grid))
    cells = _cell_coverage(
        {point_id: records[point_id] for point_id in valid}, target_cell
    )
    return RegionSummary(
        area_id=area.id,
        total_ids=tuple(sorted(total)),
        queried_ids=tuple(sorted(queried)),
        unqueried_ids=tuple(sorted(unqueried)),
        valid_ids=tuple(sorted(valid)),
        missing_ids=tuple(sorted(missing)),
        valid_covered_ids=tuple(sorted(covered)),
        no_coverage_ids=tuple(sorted(valid - covered)),
        other_cells_only_ids=tuple(sorted(covered - target)),
        target_ids=tuple(sorted(target)),
        target_rsrp_min_dbm=min(rsrp) if rsrp else None,
        target_rsrp_max_dbm=max(rsrp) if rsrp else None,
        boundary_ids=tuple(sorted(boundary)),
        boundary_valid_ids=tuple(sorted(boundary & valid)),
        boundary_missing_ids=tuple(sorted(boundary & missing)),
        boundary_target_ids=tuple(sorted(boundary & target)),
        observation_ids=tuple(sorted({evidence[point_id] for point_id in queried})),
        cells=cells,
    )


def _cell_coverage(
    valid: dict[GridId, CoverageRecord], down_cell_id: CellId
) -> tuple[CellCoverage, ...]:
    """Per cell: where it is present, where it is strongest, where it overlaps the down cell."""
    present: dict[CellId, list[GridId]] = {}
    strongest: dict[CellId, list[GridId]] = {}
    with_down: dict[CellId, list[GridId]] = {}
    rsrp: dict[CellId, list[float]] = {}
    for point_id in sorted(valid):
        signals = valid[point_id].cells
        if not signals:
            continue
        listed = {signal.cell_id for signal in signals}
        best = min(signals, key=lambda signal: (-signal.rsrp_dbm, signal.cell_id))
        strongest.setdefault(best.cell_id, []).append(point_id)
        for signal in signals:
            present.setdefault(signal.cell_id, []).append(point_id)
            rsrp.setdefault(signal.cell_id, []).append(signal.rsrp_dbm)
            if signal.cell_id != down_cell_id and down_cell_id in listed:
                with_down.setdefault(signal.cell_id, []).append(point_id)
    return tuple(
        CellCoverage(
            cell_id=cell_id,
            present_ids=tuple(present[cell_id]),
            strongest_ids=tuple(strongest.get(cell_id, [])),
            with_down_cell_ids=tuple(with_down.get(cell_id, [])),
            rsrp_min_dbm=min(rsrp[cell_id]),
            rsrp_max_dbm=max(rsrp[cell_id]),
            rsrp_mean_dbm=sum(rsrp[cell_id]) / len(rsrp[cell_id]),
        )
        for cell_id in sorted(present)
    )


def _cells_seen(
    records: dict[GridId, CoverageRecord], down_cell_id: CellId
) -> tuple[CellId, ...]:
    listed = {
        signal.cell_id
        for record in records.values()
        if record.status == "valid"
        for signal in record.cells
    }
    return tuple(sorted(listed | {down_cell_id}))


def _unknowns(
    regions: tuple[RegionSummary, ...],
    has_impact: bool,
    without_kpi: tuple[str, ...],
) -> tuple[str, ...]:
    notes: list[str] = []
    for region in regions:
        if region.unqueried_ids:
            notes.append(
                f"{region.area_id}: coverage at {len(region.unqueried_ids)} "
                "unqueried locations is unknown."
            )
        if region.missing_ids:
            notes.append(
                f"{region.area_id}: coverage at {len(region.missing_ids)} "
                "queried locations with missing data is unknown."
            )
    if without_kpi:
        notes.append(
            f"Pre-outage KPI is incomplete for backup candidates: {'; '.join(without_kpi)}."
        )
    if not has_impact:
        notes.append(
            "Backup selection, traffic transfer and load have not been computed."
        )
    notes.extend(
        (
            "Coverage beyond the study area is unknown.",
            "Land-use labels do not establish population or complete network demand.",
            "Investigation sufficiency is unknown until a finish passes the completion checks.",
        )
    )
    return tuple(notes)


def _refresh_unknowns(state: State) -> State:
    return replace(
        state,
        unknowns=_unknowns(
            state.regions, state.impact is not None, candidates_without_kpi(state)
        ),
    )


def initial_state(
    task: Task,
    grid_spacing_m: float,
    grid: tuple[GridPoint, ...],
    geography: tuple[GeoObject, ...],
    relations: tuple[SpatialRelation, ...],
    areas: tuple[Area, ...],
) -> State:
    """State 0: task, geography and areas only; no coverage, KPI or backup cells."""
    if not task.down_cell_id or not task.objective:
        raise ValueError("Task requires a down cell and objective")
    outage_time = datetime.fromisoformat(task.outage_time)
    if outage_time.tzinfo is None:
        raise ValueError("Outage time must include a timezone")
    if not isfinite(task.site_x_m) or not isfinite(task.site_y_m):
        raise ValueError("The down cell site position must be finite")
    if not isfinite(grid_spacing_m) or grid_spacing_m <= 0:
        raise ValueError("Grid spacing must be finite and positive")
    grid_ids = {point.id for point in grid}
    if not grid_ids or len(grid_ids) != len(grid):
        raise ValueError("Grid IDs must be nonempty and unique")
    coordinates = {(point.column, point.row) for point in grid}
    if len(coordinates) != len(grid):
        raise ValueError("Grid row/column addresses must be unique")
    area_ids = [area.id for area in areas]
    if len(set(area_ids)) != len(area_ids) or STUDY_AREA not in area_ids:
        raise ValueError("Unique areas including Study_area are required")
    for area in areas:
        if not area.grid_ids or len(set(area.grid_ids)) != len(area.grid_ids):
            raise ValueError(f"Empty or duplicate grid set in area {area.id}")
        if set(select_grid(grid, area.geometry)) != set(area.grid_ids):
            raise ValueError(f"Area geometry and grid set disagree: {area.id}")
        if area.parent_id is not None and area.parent_id not in area_ids:
            raise ValueError(f"Unknown parent area: {area.parent_id}")
    regions = tuple(_summarize(area, grid, {}, {}, task.down_cell_id) for area in areas)
    if set(next(r for r in regions if r.area_id == STUDY_AREA).total_ids) != grid_ids:
        raise ValueError("Study_area must contain the complete analysis grid")
    return State(
        id="state_00",
        source="synthetic",
        task=task,
        coordinate_system=COORDINATE_SYSTEM,
        grid_spacing_m=grid_spacing_m,
        grid=grid,
        geography=geography,
        relations=relations,
        areas=areas,
        regions=regions,
        observations=(),
        evidence=(),
        impact=None,
        unknowns=_unknowns(regions, has_impact=False, without_kpi=()),
        kpis=(),
        inspection=None,
        notes=(),
        cells_seen=(task.down_cell_id,),
    )


def validate_observation(observation: CoverageObservation, state: State) -> None:
    """Validate the tool contract, including a record for every requested point."""
    if not observation.id or observation.source != "synthetic":
        raise ValueError("Expected an identified synthetic observation")
    parameters = observation.parameters
    areas = {area.id: area for area in state.areas}
    if parameters.area_id not in areas:
        raise ValueError(f"Unknown area {parameters.area_id}")
    area = areas[parameters.area_id]
    if parameters.geometry != area.geometry:
        raise ValueError("Observation query geometry differs from the named area")
    if len(set(parameters.grid_ids)) != len(parameters.grid_ids):
        raise ValueError("Duplicate requested grid IDs")
    if set(parameters.grid_ids) != set(area.grid_ids):
        raise ValueError("Observation grid set differs from the named area")
    if parameters.coordinate_system != state.coordinate_system:
        raise ValueError("Query coordinate system does not match state")
    if parameters.coverage_epoch != "pre_outage":
        raise ValueError("This investigation requires pre-outage coverage evidence")
    record_ids = [record.grid_id for record in observation.records]
    if len(set(record_ids)) != len(record_ids) or set(record_ids) != set(
        parameters.grid_ids
    ):
        raise ValueError(
            "Coverage result must contain exactly one record per requested grid ID"
        )
    missing = 0
    for record in observation.records:
        if record.status == "missing":
            missing += 1
            if record.cells or record.down_cell_traffic_mbps is not None:
                raise ValueError(
                    "Missing data cannot contain signals or demand estimates"
                )
        elif record.status == "valid":
            traffic = record.down_cell_traffic_mbps
            if traffic is None or not isfinite(traffic) or traffic < 0:
                raise ValueError(
                    "Valid synthetic records require finite nonnegative demand"
                )
            if len({signal.cell_id for signal in record.cells}) != len(record.cells):
                raise ValueError("A coverage record cannot list duplicate cell IDs")
            for signal in record.cells:
                if (
                    not signal.cell_id
                    or not isfinite(signal.rsrp_dbm)
                    or not isfinite(signal.rsrq_db)
                ):
                    raise ValueError("Signals require a cell ID and finite RSRP/RSRQ")
            if (
                not any(s.cell_id == state.task.down_cell_id for s in record.cells)
                and traffic != 0
            ):
                raise ValueError(
                    "Synthetic down-cell demand requires down-cell coverage evidence"
                )
        else:
            raise ValueError(f"Invalid coverage status: {record.status}")
    expected_status = (
        "all_missing"
        if missing == len(record_ids)
        else "partial_missing"
        if missing
        else "complete"
    )
    if observation.result_status != expected_status:
        raise ValueError("Result status disagrees with point records")


def records_from_state(
    state: State, observations: dict[ObservationId, CoverageObservation]
) -> dict[GridId, CoverageRecord]:
    """Resolve observed points through state provenance, ignoring unlinked results."""
    index: dict[ObservationId, dict[GridId, CoverageRecord]] = {}
    links: dict[ObservationId, ObservationLink] = {}
    for link in state.observations:
        if link.observation_id in links:
            raise ValueError("Duplicate observation links in state")
        links[link.observation_id] = link
        if link.observation_id not in observations:
            raise ValueError(f"Missing source observation: {link.observation_id}")
        observation = observations[link.observation_id]
        validate_observation(observation, state)
        if observation.id != link.observation_id:
            raise ValueError("Observation index key does not match result ID")
        if observation.parameters.area_id != link.area_id:
            raise ValueError("Observation link does not match query area")
        if set(link.grid_ids) != set(observation.parameters.grid_ids):
            raise ValueError("Observation link does not match query grid")
        index[observation.id] = {
            record.grid_id: record for record in observation.records
        }
    records: dict[GridId, CoverageRecord] = {}
    for evidence in state.evidence:
        if evidence.grid_id in records:
            raise ValueError("Duplicate point evidence in state")
        if (
            evidence.observation_id not in index
            or evidence.grid_id not in index[evidence.observation_id]
        ):
            raise ValueError(f"Unresolvable observation evidence: {evidence.grid_id}")
        records[evidence.grid_id] = index[evidence.observation_id][evidence.grid_id]
    linked_grid_ids = {
        grid_id for link in state.observations for grid_id in link.grid_ids
    }
    if records.keys() != linked_grid_ids:
        raise ValueError("State evidence does not match queried grid union")
    expected_owners = {
        grid_id: link.observation_id
        for link in state.observations
        for grid_id in link.grid_ids
    }
    if any(
        evidence.observation_id != expected_owners[evidence.grid_id]
        for evidence in state.evidence
    ):
        raise ValueError("State evidence must use the latest observation for each grid")
    expected_regions = tuple(
        _summarize(area, state.grid, records, expected_owners, state.task.down_cell_id)
        for area in state.areas
    )
    if expected_regions != state.regions:
        raise ValueError(
            "State summaries disagree with the linked observation evidence"
        )
    if _cells_seen(records, state.task.down_cell_id) != state.cells_seen:
        raise ValueError("State cells_seen disagrees with the linked records")
    return records


def apply_coverage(
    state: State,
    members: tuple[tuple[CoverageObservation, str], ...],
    state_id: str,
    observations: dict[ObservationId, CoverageObservation],
) -> State:
    """Apply the members of one coverage call, in member order, as one new snapshot.

    Each member is a parsed coverage result and the relative path of its file.
    Where members or earlier observations overlap, the newest record wins.
    """
    if not state_id or state_id == state.id or not members:
        raise ValueError("A new state ID and at least one member are required")
    records = records_from_state(state, observations)
    evidence = {item.grid_id: item.observation_id for item in state.evidence}
    links = list(state.observations)
    for observation, path in members:
        if not path:
            raise ValueError("Each member requires the path of its records file")
        if any(link.observation_id == observation.id for link in links):
            raise ValueError("Each query execution requires a new observation ID")
        if (
            observation.id not in observations
            or observations[observation.id] != observation
        ):
            raise ValueError("The observation must be registered before applying it")
        validate_observation(observation, state)
        records.update({record.grid_id: record for record in observation.records})
        evidence.update(
            {record.grid_id: observation.id for record in observation.records}
        )
        links.append(
            ObservationLink(
                observation.id,
                path,
                observation.parameters.area_id,
                observation.parameters.grid_ids,
            )
        )
    regions = tuple(
        _summarize(area, state.grid, records, evidence, state.task.down_cell_id)
        for area in state.areas
    )
    return _refresh_unknowns(
        replace(
            state,
            id=state_id,
            regions=regions,
            observations=tuple(links),
            evidence=tuple(
                GridEvidence(grid_id, evidence[grid_id]) for grid_id in sorted(evidence)
            ),
            # A new spatial observation invalidates any derived load estimate.
            impact=None,
            cells_seen=_cells_seen(records, state.task.down_cell_id),
        )
    )


def apply_kpi(state: State, records: tuple[KPIRecord, ...], state_id: str) -> State:
    """Add KPI rows; a newer row for the same cell, window and indicator replaces the older."""
    if not state_id or state_id == state.id or not records:
        raise ValueError("A new state ID and at least one KPI record are required")
    merged = {
        (record.cell_id, record.window, record.indicator): record
        for record in state.kpis
    }
    for record in records:
        _validate_kpi(record)
        merged[(record.cell_id, record.window, record.indicator)] = record
    return _refresh_unknowns(
        replace(
            state,
            id=state_id,
            kpis=tuple(merged[key] for key in sorted(merged)),
            # New KPI evidence invalidates any derived load estimate.
            impact=None,
        )
    )


def apply_inspection(state: State, inspection: Inspection, state_id: str) -> State:
    """Record the rows the model asked to see; the next context shows them once."""
    if not state_id or state_id == state.id:
        raise ValueError("A new state ID is required")
    links = {link.observation_id: link for link in state.observations}
    link = links.get(inspection.observation_id)
    if link is None or link.area_id != inspection.area_id:
        raise ValueError(f"{inspection.observation_id} is not linked in State")
    if len(link.grid_ids) != inspection.total_rows or not inspection.records:
        raise ValueError("Inspection rows disagree with the linked observation")
    return replace(state, id=state_id, inspection=inspection)


def apply_note(state: State, note: Note) -> State:
    """Append a feedback fact. The round's State id is set when its Step is written."""
    if note.step_index < 1 or not note.text:
        raise ValueError("A note requires a round number and text")
    return replace(state, notes=(*state.notes, note))


def _validate_kpi(record: KPIRecord) -> None:
    if not record.cell_id or not isfinite(record.value):
        raise ValueError(f"Invalid KPI row for cell {record.cell_id}")
    if record.unit != KPI_UNITS[record.indicator]:
        raise ValueError(
            f"KPI {record.indicator} of {record.cell_id} is in {record.unit}, "
            f"expected {KPI_UNITS[record.indicator]}"
        )
    if record.indicator == "prb_utilization" and not 0 <= record.value <= 100:
        raise ValueError(f"PRB utilization of {record.cell_id} is outside 0 to 100")
    if record.indicator == "capacity" and record.value <= 0:
        raise ValueError(f"Capacity of {record.cell_id} must be positive")


def estimate_impact(
    state: State,
    observations: dict[ObservationId, CoverageObservation],
    parameters: LoadParameters,
) -> ImpactAnalysis:
    if (
        parameters.selection_rule != BACKUP_SELECTION_RULE
        or parameters.load_formula != LOAD_FORMULA
    ):
        raise ValueError("Unsupported backup selection rule or load formula")
    if not isfinite(parameters.minimum_rsrp_dbm) or not isfinite(
        parameters.minimum_rsrq_db
    ):
        raise ValueError("Backup thresholds must be finite")
    scope = summary_for(state, parameters.scope_area_id)
    if not scope.queried_ids:
        raise ValueError("Impact estimation requires queried spatial evidence")
    records = records_from_state(state, observations)
    for record in state.kpis:
        _validate_kpi(record)
    kpis = baseline_kpis(state)
    missing_kpi = candidates_without_kpi(state)
    if missing_kpi:
        raise ValueError(f"Backup candidates lack KPI: {'; '.join(missing_kpi)}")
    assignments: list[BackupAssignment] = []
    for grid_id in scope.target_ids:
        record = records[grid_id]
        traffic = record.down_cell_traffic_mbps
        if record.status != "valid" or traffic is None:
            raise ValueError(
                "Target summary must resolve to valid coverage and traffic evidence"
            )
        eligible = [
            signal
            for signal in record.cells
            if signal.cell_id != state.task.down_cell_id
            and signal.rsrp_dbm >= parameters.minimum_rsrp_dbm
            and signal.rsrq_db >= parameters.minimum_rsrq_db
        ]
        winner = sorted(eligible, key=lambda signal: (-signal.rsrp_dbm, signal.cell_id))
        backup_id = winner[0].cell_id if winner else None
        if backup_id is not None and backup_id not in kpis:
            raise ValueError(f"No baseline KPI for selected backup {backup_id}")
        assignments.append(
            BackupAssignment(
                grid_id,
                backup_id,
                "transferred" if backup_id is not None else "no_eligible_backup",
                traffic,
            )
        )
    total_traffic = sum(assignment.traffic_mbps for assignment in assignments)
    loads: list[BackupLoad] = []
    for cell_id, kpi in sorted(kpis.items()):
        if cell_id == state.task.down_cell_id:
            continue
        assigned = [
            assignment
            for assignment in assignments
            if assignment.backup_cell_id == cell_id
        ]
        transferred = sum(assignment.traffic_mbps for assignment in assigned)
        estimated_prb = kpi.baseline_prb_percent + 100 * transferred / kpi.capacity_mbps
        loads.append(
            BackupLoad(
                cell_id=cell_id,
                assigned_locations=len(assigned),
                location_share=len(assigned) / len(assignments) if assignments else 0.0,
                transferred_mbps=transferred,
                traffic_share=transferred / total_traffic if total_traffic > 0 else 0.0,
                baseline_prb_percent=kpi.baseline_prb_percent,
                capacity_mbps=kpi.capacity_mbps,
                estimated_prb_percent=estimated_prb,
                exceeds_capacity=estimated_prb > 100,
            )
        )
    return ImpactAnalysis(
        source="synthetic",
        parameters=parameters,
        scope_queried_ids=scope.queried_ids,
        excluded_missing_ids=scope.missing_ids,
        excluded_unqueried_ids=scope.unqueried_ids,
        target_location_count=len(assignments),
        total_target_traffic_mbps=total_traffic,
        unserved_traffic_mbps=sum(
            a.traffic_mbps for a in assignments if a.backup_cell_id is None
        ),
        assignments=tuple(assignments),
        backup_loads=tuple(loads),
        baseline_kpis=tuple(kpis[cell] for cell in sorted(kpis)),
        limitations=(
            "Scope: only queried valid target-present locations in the named area; not complete outage impact.",
            "Target presence is used as a synthetic affected-demand proxy, not proof of real serving-cell assignment.",
            "Location shares divide by valid target-present locations; traffic shares divide by their synthetic offered Mbps.",
            "A zero denominator is reported as share 0 with the zero denominator retained explicitly.",
            "Pre-outage locations with no coverage are not newly attributed to this outage.",
            "Missing and unqueried demand is excluded, not assumed to be zero.",
            "PRB-only linear demonstration; no RRC input, radio scheduling, mobility or calibrated network model.",
            "Estimated PRB above 100 percent flags potential overload and is not clamped.",
        ),
    )


def apply_impact(
    state: State,
    impact: ImpactAnalysis,
    state_id: str,
    observations: dict[ObservationId, CoverageObservation],
) -> State:
    if not state_id or state_id == state.id:
        raise ValueError("A new state ID is required")
    expected = estimate_impact(state, observations, impact.parameters)
    if impact != expected:
        raise ValueError(
            "Impact is invalid or stale for the current observation evidence"
        )
    return _refresh_unknowns(replace(state, id=state_id, impact=impact))
