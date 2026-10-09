"""The State the context builder reads, as stored in the two-file layout.

Persistence writes two kinds of file per run:

- geography.json, once, after initialization: coordinate system, analysis grid,
  object geometries, and for every area its geometry and grid ids.
- state_NN.json, every round: the task, a geography section without
  coordinates (objects, relations, areas, and the name and SHA-256 of
  geography.json), the coverage table with one entry per queried location,
  observation references, count-only summaries per area, KPI records, impact,
  inspection, notes and unknowns.

load_state reads one snapshot and the geometry file it names, checks the hash,
and returns one State. Every other function here is a fact computed from that
State; nothing here reads hidden coverage data.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, assert_never

from outage_poc.models import (
    KPI_UNITS,
    ActionSpec,
    AreaId,
    BackupAssignment,
    BackupLoad,
    BaselineKPI,
    CellId,
    Coordinate,
    GeoKind,
    Geometry,
    GridId,
    GridPoint,
    ImpactAnalysis,
    KPIRecord,
    LoadParameters,
    Note,
    ObservationId,
    Phase,
    RunConfig,
    Signal,
    SpatialRelation,
    Task,
)

STUDY_AREA = AreaId("Study_area")

AreaKind = Literal["study_area", "sub_area", "corridor"]


# The content of geography.json.


@dataclass(frozen=True)
class AreaGeometry:
    geometry: Geometry
    grid_ids: tuple[GridId, ...]


@dataclass(frozen=True)
class GeographyData:
    coordinate_system: str
    grid_spacing_m: float
    grid: tuple[GridPoint, ...]
    objects: dict[str, Geometry]
    areas: dict[AreaId, AreaGeometry]


# The geography section of a snapshot: everything about places except coordinates.


@dataclass(frozen=True)
class GeometryFile:
    # Relative to the run directory.
    path: str
    sha256: str


@dataclass(frozen=True)
class GeoObjectEntry:
    id: str
    kind: GeoKind
    description: str
    # Grid locations inside the object; None for a highway, which is a centerline.
    locations: int | None
    # The query corridor of a highway and its full width; None for other objects.
    corridor: AreaId | None
    width_m: float | None


@dataclass(frozen=True)
class AreaEntry:
    id: AreaId
    kind: AreaKind
    # What the area is derived from: the study area itself, the parent area of a
    # sub-area, or the highway of a corridor.
    parent: str
    # Full corridor width; None unless kind is corridor.
    width_m: float | None
    locations: int


@dataclass(frozen=True)
class GeographySection:
    # Action name to the initialization observation it came from.
    source: dict[str, ObservationId]
    geometry: GeometryFile
    objects: tuple[GeoObjectEntry, ...]
    relations: tuple[SpatialRelation, ...]
    areas: tuple[AreaEntry, ...]


# Evidence.


@dataclass(frozen=True)
class CoverageEntry:
    """One queried location: its status, its observation, and every cell with its signal."""

    grid_id: GridId
    status: Literal["valid", "missing"]
    observation: ObservationId
    cells: tuple[Signal, ...]
    # Synthetic demand assigned to the down cell; None for a missing record.
    down_cell_traffic_mbps: float | None


@dataclass(frozen=True)
class ObservationRef:
    id: ObservationId
    path: str
    area_id: AreaId


@dataclass(frozen=True)
class CellSummary:
    """Counts for one cell inside one area, over the valid locations that list it."""

    cell_id: CellId
    present: int
    strongest: int
    # Locations that list both this cell and the down cell; 0 for the down cell.
    with_down_cell: int
    rsrp_min_dbm: float
    rsrp_max_dbm: float
    rsrp_mean_dbm: float


@dataclass(frozen=True)
class AreaSummary:
    area_id: AreaId
    queried: int
    unqueried: int
    valid: int
    missing: int
    no_coverage: int
    # Valid locations with cells but without the down cell. Not the same as no coverage.
    other_cells_only: int
    down_cell_present: int
    boundary: int
    # Boundary locations with missing data: unknown, not down-cell-absent.
    boundary_missing: int
    boundary_with_down_cell: int
    # Every cell a valid record in the area lists, the down cell included, by cell id.
    cells: tuple[CellSummary, ...]


@dataclass(frozen=True)
class Inspection:
    """The drill-down the model asked for. The rows come from the coverage table."""

    step_index: int
    observation_id: ObservationId
    first_row: int
    row_count: int


@dataclass(frozen=True)
class State:
    id: str
    task: Task
    geography: GeographySection
    # The content of the geometry file the geography section names.
    geometry: GeographyData
    coverage: dict[GridId, CoverageEntry]
    observations: tuple[ObservationRef, ...]
    summaries: dict[AreaId, AreaSummary]
    kpis: tuple[KPIRecord, ...]
    impact: ImpactAnalysis | None
    inspection: Inspection | None
    notes: tuple[Note, ...]
    unknowns: tuple[str, ...]


# Facts computed from State.


def summary_for(state: State, area_id: AreaId) -> AreaSummary:
    summary = state.summaries.get(area_id)
    if summary is None:
        raise ValueError(f"No summary for area {area_id!r}")
    return summary


def area_entry(state: State, area_id: AreaId) -> AreaEntry:
    matches = [area for area in state.geography.areas if area.id == area_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one area entry for {area_id!r}")
    return matches[0]


def key_areas(state: State) -> tuple[AreaId, ...]:
    """The task-relevant areas: every corridor and every sub-area derived directly
    from the study area. Not the study area itself, and not a sub-area of a
    sub-area such as S2_roadside."""
    selected: list[AreaId] = []
    for area in state.geography.areas:
        match area.kind:
            case "study_area":
                continue
            case "corridor":
                selected.append(area.id)
            case "sub_area":
                if area.parent == STUDY_AREA:
                    selected.append(area.id)
            case _ as unreachable:
                assert_never(unreachable)
    return tuple(selected)


def down_cell_locations(state: State) -> frozenset[GridId]:
    """Queried locations whose valid record lists the down cell."""
    down = state.task.down_cell_id
    return frozenset(
        entry.grid_id
        for entry in state.coverage.values()
        if entry.status == "valid" and any(s.cell_id == down for s in entry.cells)
    )


def unqueried_ids(state: State, area_id: AreaId) -> tuple[GridId, ...]:
    geometry = state.geometry.areas.get(area_id)
    if geometry is None:
        raise ValueError(f"No geometry for area {area_id!r}")
    return tuple(g for g in geometry.grid_ids if g not in state.coverage)


def d0_border_count(state: State, area_id: AreaId) -> int:
    """How many unqueried locations of the area share an edge with a queried
    location where the down cell is present.

    A program fact for the key-area rule: an area whose unqueried locations do
    not border any observed down-cell location can be left unqueried if the
    finish names it. A border with the down cell present is also a study-area
    query-boundary location with the down cell, so the boundary rule fails there.
    """
    present = down_cell_locations(state)
    positions = {(p.column, p.row): p.id for p in state.geometry.grid}
    by_id = {p.id: p for p in state.geometry.grid}
    count = 0
    for grid_id in unqueried_ids(state, area_id):
        point = by_id[grid_id]
        if any(
            positions.get((point.column + dx, point.row + dy)) in present
            for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0))
        ):
            count += 1
    return count


def queried_d0_present(state: State) -> bool:
    """The backup phase starts once a queried location lists the down cell."""
    return summary_for(state, STUDY_AREA).down_cell_present > 0


def backup_candidates(state: State) -> tuple[CellId, ...]:
    """Cells seen in valid records of the study area, other than the down cell."""
    return tuple(
        cell.cell_id
        for cell in summary_for(state, STUDY_AREA).cells
        if cell.cell_id != state.task.down_cell_id
    )


def candidates_without_kpi(state: State) -> tuple[str, ...]:
    """One line per backup candidate that lacks a KPI indicator."""
    held = {(record.cell_id, record.indicator) for record in state.kpis}
    lines: list[str] = []
    for cell in backup_candidates(state):
        missing = [name for name in KPI_UNITS if (cell, name) not in held]
        if missing:
            lines.append(f"{cell} has no {' or '.join(missing)}")
    return tuple(lines)


def current_phase(state: State) -> Phase:
    """Coverage until a queried location lists the down cell; backup after that."""
    return "backup" if queried_d0_present(state) else "coverage"


def precondition_failure(action: ActionSpec, state: State) -> str | None:
    """None when the action may run against this State; else the State fact that blocks it."""
    if action.phase == "initialization":
        return (
            f"{action.name} runs only during initialization, before the first decision"
        )
    down = state.task.down_cell_id
    match action.precondition:
        case "none":
            return None
        case "queried_d0_present":
            if queried_d0_present(state):
                return None
            return (
                "precondition queried_d0_present does not hold: no queried "
                f"location lists {down} yet"
            )
        case "kpi_present_for_candidates":
            if not queried_d0_present(state):
                return (
                    "precondition kpi_present_for_candidates does not hold: no "
                    f"queried location lists {down} yet"
                )
            missing = candidates_without_kpi(state)
            if missing:
                return (
                    "precondition kpi_present_for_candidates does not hold: "
                    f"{'; '.join(missing)}"
                )
            return None
        case "observation_present":
            if state.observations:
                return None
            return (
                "precondition observation_present does not hold: no coverage "
                "observation exists yet"
            )
        case _ as unreachable:
            assert_never(unreachable)


def allowed_actions(
    actions: tuple[ActionSpec, ...], state: State
) -> tuple[ActionSpec, ...]:
    """Loop actions whose precondition holds. Coverage actions stay allowed in the
    backup phase, because the investigation may still widen its area."""
    return tuple(a for a in actions if precondition_failure(a, state) is None)


def budget_blocks_boundary(state: State, config: RunConfig) -> str | None:
    """The fact that ends a run as query_budget: some key area still borders an
    observed down-cell location, and even the cheapest such area costs more
    than the budget that remains. Returns the sentence for the model, or None
    when the budget still allows at least one of those areas."""
    spent = summary_for(state, STUDY_AREA).queried
    remaining = config.query_budget_locations - spent
    bordering = [
        (summary_for(state, area_id).unqueried, area_id)
        for area_id in key_areas(state)
        if summary_for(state, area_id).unqueried and d0_border_count(state, area_id)
    ]
    if not bordering:
        return None
    cost, cheapest = min(bordering)
    if cost <= remaining:
        return None
    return (
        f"the boundary check cannot be met within the budget: {cheapest} is the "
        f"cheapest key area whose unqueried locations border {state.task.down_cell_id} "
        f"and it would cost {cost} locations, but only {remaining} remain"
    )


def observation_rows(
    state: State, observation_id: ObservationId
) -> tuple[CoverageEntry, ...]:
    """The coverage entries one observation returned, in grid order (row, then column)."""
    order = {p.id: (p.row, p.column) for p in state.geometry.grid}
    rows = [e for e in state.coverage.values() if e.observation == observation_id]
    return tuple(sorted(rows, key=lambda e: order[e.grid_id]))


def observation_ref(state: State, observation_id: ObservationId) -> ObservationRef:
    matches = [o for o in state.observations if o.id == observation_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one observation {observation_id!r}")
    return matches[0]


# Loading the two files. Each helper narrows a JSON value or raises.


def _object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{where}: expected an object")
    return {str(k): v for k, v in value.items()}


def _list(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{where}: expected a list")
    return value


def _str(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{where}: expected a string")
    return value


def _float(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{where}: expected a number")
    return float(value)


def _int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{where}: expected an integer")
    return value


def _optional_float(value: object, where: str) -> float | None:
    return None if value is None else _float(value, where)


def _literal[T: str](value: object, choices: tuple[T, ...], where: str) -> T:
    text = _str(value, where)
    for choice in choices:
        if text == choice:
            return choice
    raise ValueError(f"{where}: {text!r} is not one of {choices}")


GEO_KINDS: tuple[GeoKind, ...] = (
    "settlement",
    "highway",
    "farmland",
    "vineyard",
    "forest",
    "study_area",
    "cell",
)
AREA_KINDS: tuple[AreaKind, ...] = ("study_area", "sub_area", "corridor")


def _geometry(value: object, where: str) -> Geometry:
    data = _object(value, where)
    coordinates: list[Coordinate] = []
    for i, pair in enumerate(_list(data["coordinates"], f"{where}.coordinates")):
        xy = _list(pair, f"{where}.coordinates[{i}]")
        if len(xy) != 2:
            raise ValueError(f"{where}.coordinates[{i}]: expected two numbers")
        coordinates.append((_float(xy[0], f"{where}.x"), _float(xy[1], f"{where}.y")))
    return Geometry(
        kind=_literal(data["kind"], ("polygon", "polyline", "buffer"), where),
        coordinates=tuple(coordinates),
        buffer_width_m=_optional_float(data["buffer_width_m"], f"{where}.width"),
    )


def _geography_data(value: object) -> GeographyData:
    data = _object(value, "geography.json")
    grid = tuple(
        GridPoint(
            id=GridId(_str(p["id"], "grid.id")),
            x_m=_float(p["x_m"], "grid.x_m"),
            y_m=_float(p["y_m"], "grid.y_m"),
            column=_int(p["column"], "grid.column"),
            row=_int(p["row"], "grid.row"),
        )
        for item in _list(data["grid"], "grid")
        for p in (_object(item, "grid[]"),)
    )
    objects = {
        name: _geometry(geometry, f"objects.{name}")
        for name, geometry in _object(data["objects"], "objects").items()
    }
    areas: dict[AreaId, AreaGeometry] = {}
    for name, area in _object(data["areas"], "areas").items():
        entry = _object(area, f"areas.{name}")
        areas[AreaId(name)] = AreaGeometry(
            geometry=_geometry(entry["geometry"], f"areas.{name}.geometry"),
            grid_ids=tuple(
                GridId(_str(g, f"areas.{name}.grid_ids"))
                for g in _list(entry["grid_ids"], f"areas.{name}.grid_ids")
            ),
        )
    return GeographyData(
        coordinate_system=_str(data["coordinate_system"], "coordinate_system"),
        grid_spacing_m=_float(data["grid_spacing_m"], "grid_spacing_m"),
        grid=grid,
        objects=objects,
        areas=areas,
    )


def _task(value: object) -> Task:
    data = _object(value, "task")
    return Task(
        down_cell_id=CellId(_str(data["down_cell_id"], "task.down_cell_id")),
        outage_time=_str(data["outage_time"], "task.outage_time"),
        objective=_str(data["objective"], "task.objective"),
        site_x_m=_float(data["site_x_m"], "task.site_x_m"),
        site_y_m=_float(data["site_y_m"], "task.site_y_m"),
        coverage_epoch=_literal(data["coverage_epoch"], ("pre_outage",), "task.epoch"),
    )


def _geography_section(value: object) -> GeographySection:
    data = _object(value, "geography")
    source = {
        action: ObservationId(_str(obs, f"geography.source.{action}"))
        for action, obs in _object(data["source"], "geography.source").items()
    }
    file = _object(data["geometry"], "geography.geometry")
    objects: list[GeoObjectEntry] = []
    for name, item in _object(data["objects"], "geography.objects").items():
        where = f"geography.objects.{name}"
        entry = _object(item, where)
        corridor = entry.get("corridor")
        locations = entry.get("locations")
        objects.append(
            GeoObjectEntry(
                id=name,
                kind=_literal(entry["kind"], GEO_KINDS, where),
                description=_str(entry["description"], where),
                locations=None if locations is None else _int(locations, where),
                corridor=None if corridor is None else AreaId(_str(corridor, where)),
                width_m=_optional_float(entry.get("width_m"), where),
            )
        )
    relations = tuple(
        SpatialRelation(
            subject_id=_str(r["subject"], "relation.subject"),
            predicate=_str(r["predicate"], "relation.predicate"),
            object_id=_str(r["object"], "relation.object"),
            evidence=_str(r["evidence"], "relation.evidence"),
        )
        for item in _list(data["relations"], "geography.relations")
        for r in (_object(item, "geography.relations[]"),)
    )
    areas: list[AreaEntry] = []
    for name, item in _object(data["areas"], "geography.areas").items():
        where = f"geography.areas.{name}"
        entry = _object(item, where)
        areas.append(
            AreaEntry(
                id=AreaId(name),
                kind=_literal(entry["kind"], AREA_KINDS, where),
                parent=_str(entry["from"], where),
                width_m=_optional_float(entry.get("width_m"), where),
                locations=_int(entry["locations"], where),
            )
        )
    return GeographySection(
        source=source,
        geometry=GeometryFile(
            path=_str(file["path"], "geography.geometry.path"),
            sha256=_str(file["sha256"], "geography.geometry.sha256"),
        ),
        objects=tuple(objects),
        relations=relations,
        areas=tuple(areas),
    )


def _signals(value: object, where: str) -> tuple[Signal, ...]:
    return tuple(
        Signal(
            cell_id=CellId(cell),
            rsrp_dbm=_float(_object(s, where)["rsrp_dbm"], f"{where}.rsrp"),
            rsrq_db=_float(_object(s, where)["rsrq_db"], f"{where}.rsrq"),
        )
        for cell, s in _object(value, where).items()
    )


def _coverage(value: object) -> dict[GridId, CoverageEntry]:
    table: dict[GridId, CoverageEntry] = {}
    for grid_id, item in _object(value, "coverage").items():
        where = f"coverage.{grid_id}"
        entry = _object(item, where)
        status = _literal(entry["status"], ("valid", "missing"), where)
        observation = ObservationId(_str(entry["observation"], where))
        match status:
            case "valid":
                # A valid record stores its cells (possibly none) and its traffic.
                table[GridId(grid_id)] = CoverageEntry(
                    grid_id=GridId(grid_id),
                    status=status,
                    observation=observation,
                    cells=_signals(entry["cells"], f"{where}.cells"),
                    down_cell_traffic_mbps=_float(
                        entry["down_cell_traffic_mbps"], where
                    ),
                )
            case "missing":
                # A missing record stores only its status and its observation.
                if "cells" in entry or "down_cell_traffic_mbps" in entry:
                    raise ValueError(f"{where}: a missing record carries no data")
                table[GridId(grid_id)] = CoverageEntry(
                    grid_id=GridId(grid_id),
                    status=status,
                    observation=observation,
                    cells=(),
                    down_cell_traffic_mbps=None,
                )
            case _ as unreachable:
                assert_never(unreachable)
    return table


def _summaries(value: object) -> dict[AreaId, AreaSummary]:
    summaries: dict[AreaId, AreaSummary] = {}
    for area_id, item in _object(value, "summaries").items():
        where = f"summaries.{area_id}"
        s = _object(item, where)
        cells = tuple(
            CellSummary(
                cell_id=CellId(cell_id),
                present=_int(c["present"], f"{where}.{cell_id}"),
                strongest=_int(c["strongest"], f"{where}.{cell_id}"),
                with_down_cell=_int(c["with_down_cell"], f"{where}.{cell_id}"),
                rsrp_min_dbm=_float(c["rsrp_min_dbm"], f"{where}.{cell_id}"),
                rsrp_max_dbm=_float(c["rsrp_max_dbm"], f"{where}.{cell_id}"),
                rsrp_mean_dbm=_float(c["rsrp_mean_dbm"], f"{where}.{cell_id}"),
            )
            for cell_id, item in _object(s["cells"], f"{where}.cells").items()
            for c in (_object(item, f"{where}.cells.{cell_id}"),)
        )
        summaries[AreaId(area_id)] = AreaSummary(
            area_id=AreaId(area_id),
            queried=_int(s["queried"], where),
            unqueried=_int(s["unqueried"], where),
            valid=_int(s["valid"], where),
            missing=_int(s["missing"], where),
            no_coverage=_int(s["no_coverage"], where),
            other_cells_only=_int(s["other_cells_only"], where),
            down_cell_present=_int(s["down_cell_present"], where),
            boundary=_int(s["boundary"], where),
            boundary_missing=_int(s["boundary_missing"], where),
            boundary_with_down_cell=_int(s["boundary_with_down_cell"], where),
            cells=cells,
        )
    return summaries


def _kpis(value: object) -> tuple[KPIRecord, ...]:
    records: list[KPIRecord] = []
    for item in _list(value, "kpis"):
        k = _object(item, "kpis[]")
        records.append(
            KPIRecord(
                cell_id=CellId(_str(k["cell_id"], "kpi.cell_id")),
                window=_literal(k["window"], ("pre_outage",), "kpi.window"),
                indicator=_literal(
                    k["indicator"], ("prb_utilization", "capacity"), "kpi.indicator"
                ),
                value=_float(k["value"], "kpi.value"),
                unit=_literal(k["unit"], ("percent", "Mbps"), "kpi.unit"),
            )
        )
    return tuple(records)


def _grid_ids(value: object, where: str) -> tuple[GridId, ...]:
    return tuple(GridId(_str(g, where)) for g in _list(value, where))


def _impact(value: object) -> ImpactAnalysis | None:
    if value is None:
        return None
    data = _object(value, "impact")
    p = _object(data["parameters"], "impact.parameters")
    assignments = tuple(
        BackupAssignment(
            grid_id=GridId(_str(a["grid_id"], "assignment.grid_id")),
            backup_cell_id=(
                None
                if a["backup_cell_id"] is None
                else CellId(_str(a["backup_cell_id"], "assignment.backup"))
            ),
            classification=_literal(
                a["classification"],
                ("transferred", "no_eligible_backup"),
                "assignment.class",
            ),
            traffic_mbps=_float(a["traffic_mbps"], "assignment.traffic"),
        )
        for item in _list(data["assignments"], "impact.assignments")
        for a in (_object(item, "impact.assignments[]"),)
    )
    loads = tuple(
        BackupLoad(
            cell_id=CellId(_str(b["cell_id"], "load.cell_id")),
            assigned_locations=_int(b["assigned_locations"], "load"),
            location_share=_float(b["location_share"], "load"),
            transferred_mbps=_float(b["transferred_mbps"], "load"),
            traffic_share=_float(b["traffic_share"], "load"),
            baseline_prb_percent=_float(b["baseline_prb_percent"], "load"),
            capacity_mbps=_float(b["capacity_mbps"], "load"),
            estimated_prb_percent=_float(b["estimated_prb_percent"], "load"),
            exceeds_capacity=bool(b["exceeds_capacity"]),
        )
        for item in _list(data["backup_loads"], "impact.backup_loads")
        for b in (_object(item, "impact.backup_loads[]"),)
    )
    baselines = tuple(
        BaselineKPI(
            cell_id=CellId(_str(k["cell_id"], "baseline.cell_id")),
            baseline_prb_percent=_float(k["baseline_prb_percent"], "baseline"),
            capacity_mbps=_float(k["capacity_mbps"], "baseline"),
        )
        for item in _list(data["baseline_kpis"], "impact.baseline_kpis")
        for k in (_object(item, "impact.baseline_kpis[]"),)
    )
    return ImpactAnalysis(
        source=_literal(data["source"], ("synthetic",), "impact.source"),
        parameters=LoadParameters(
            scope_area_id=AreaId(_str(p["scope_area_id"], "parameters.scope")),
            minimum_rsrp_dbm=_float(p["minimum_rsrp_dbm"], "parameters.rsrp"),
            minimum_rsrq_db=_float(p["minimum_rsrq_db"], "parameters.rsrq"),
            selection_rule=_str(p["selection_rule"], "parameters.rule"),
            load_formula=_str(p["load_formula"], "parameters.formula"),
        ),
        scope_queried_ids=_grid_ids(data["scope_queried_ids"], "impact.scope"),
        excluded_missing_ids=_grid_ids(data["excluded_missing_ids"], "impact.miss"),
        excluded_unqueried_ids=_grid_ids(
            data["excluded_unqueried_ids"], "impact.unqueried"
        ),
        target_location_count=_int(data["target_location_count"], "impact.count"),
        total_target_traffic_mbps=_float(
            data["total_target_traffic_mbps"], "impact.total"
        ),
        unserved_traffic_mbps=_float(data["unserved_traffic_mbps"], "impact.unserved"),
        assignments=assignments,
        backup_loads=loads,
        baseline_kpis=baselines,
        limitations=tuple(
            _str(text, "impact.limitations")
            for text in _list(data["limitations"], "impact.limitations")
        ),
    )


def _inspection(value: object) -> Inspection | None:
    if value is None:
        return None
    data = _object(value, "inspection")
    return Inspection(
        step_index=_int(data["step_index"], "inspection.step_index"),
        observation_id=ObservationId(_str(data["observation_id"], "inspection.obs")),
        first_row=_int(data["first_row"], "inspection.first_row"),
        row_count=_int(data["row_count"], "inspection.row_count"),
    )


def _notes(value: object) -> tuple[Note, ...]:
    return tuple(
        Note(
            kind=_literal(
                n["kind"],
                ("parse_failure", "rejected", "concern", "unmet", "query_failed"),
                "note.kind",
            ),
            step_index=_int(n["step_index"], "note.step_index"),
            text=_str(n["text"], "note.text"),
        )
        for item in _list(value, "notes")
        for n in (_object(item, "notes[]"),)
    )


def load_state(snapshot_path: Path) -> State:
    """Read one state_NN.json and the geometry file it names, next to the run.

    The geometry file's SHA-256 must equal the one the snapshot records.
    """
    data = _object(json.loads(snapshot_path.read_text(encoding="utf-8")), "snapshot")
    geography = _geography_section(data["geography"])
    geometry_path = snapshot_path.parent / geography.geometry.path
    geometry_bytes = geometry_path.read_bytes()
    digest = hashlib.sha256(geometry_bytes).hexdigest()
    if digest != geography.geometry.sha256:
        raise ValueError(
            f"{geometry_path} has sha256 {digest}; the snapshot "
            f"{snapshot_path.name} expects {geography.geometry.sha256}"
        )
    return State(
        id=_str(data["id"], "id"),
        task=_task(data["task"]),
        geography=geography,
        geometry=_geography_data(json.loads(geometry_bytes)),
        coverage=_coverage(data["coverage"]),
        observations=tuple(
            ObservationRef(
                id=ObservationId(_str(o["id"], "observation.id")),
                path=_str(o["path"], "observation.path"),
                area_id=AreaId(_str(o["area_id"], "observation.area_id")),
            )
            for item in _list(data["observations"], "observations")
            for o in (_object(item, "observations[]"),)
        ),
        summaries=_summaries(data["summaries"]),
        kpis=_kpis(data["kpis"]),
        impact=_impact(data["impact"]),
        inspection=_inspection(data["inspection"]),
        notes=_notes(data["notes"]),
        unknowns=tuple(
            _str(u, "unknowns") for u in _list(data["unknowns"], "unknowns")
        ),
    )
