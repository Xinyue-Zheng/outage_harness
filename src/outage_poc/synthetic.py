"""Deterministic synthetic inputs and an offline geometric coverage provider.

Only the synthetic tool library (data_tools.py) reads this module; the harness
never imports it. The record generator models pre-outage evidence only; its
formulas are fictional, not a propagation model.
"""

from math import hypot, isfinite

from outage_poc.geometry import make_grid, select_grid
from outage_poc.models import (
    CellId,
    CoverageObservation,
    CoverageRecord,
    Dataset,
    Geometry,
    GeoObject,
    GridPoint,
    KPIRecord,
    ObservationId,
    QueryParameters,
    Signal,
    TaskInput,
)

COORDINATE_SYSTEM = (
    "synthetic local planar coordinates in metres; not latitude/longitude"
)
COVERAGE_EPOCH = "pre_outage"


def _rectangle(left: float, bottom: float, right: float, top: float) -> Geometry:
    if left >= right or bottom >= top:
        raise ValueError("Rectangle bounds must have positive width and height")
    return Geometry(
        "polygon", ((left, bottom), (right, bottom), (right, top), (left, top)), None
    )


def _polygon(*corners: tuple[float, float]) -> Geometry:
    return Geometry("polygon", tuple(corners), None)


def _make_grid() -> tuple[GridPoint, ...]:
    return make_grid(0, 0, 6000, 4000, 100.0)


def _make_geography() -> tuple[GeoObject, ...]:
    return (
        GeoObject(
            "Study_area",
            "study_area",
            "Synthetic rural study area; land use does not imply population or demand",
            _rectangle(0, 0, 6000, 4000),
        ),
        GeoObject(
            "S1",
            "settlement",
            "Synthetic settlement nearest the down cell",
            _rectangle(800, 1000, 1400, 1600),
        ),
        GeoObject(
            "S2",
            "settlement",
            "Synthetic settlement extending north from H2",
            _rectangle(4000, 1000, 4800, 3500),
        ),
        GeoObject(
            "S3",
            "settlement",
            "Synthetic northern settlement",
            _rectangle(800, 2900, 1600, 3500),
        ),
        GeoObject(
            "H1",
            "highway",
            "Synthetic highway centreline; query with H1_buffer (300 m full width)",
            Geometry("polyline", ((1100, 1200), (1100, 3300)), None),
        ),
        GeoObject(
            "H2",
            "highway",
            "Synthetic highway centreline; query with H2_buffer (500 m full width)",
            Geometry("polyline", ((1100, 1250), (4500, 1250)), None),
        ),
        GeoObject(
            "F1",
            "farmland",
            "Synthetic farmland; demand is not inferred from land use",
            _rectangle(1600, 0, 4000, 1000),
        ),
        GeoObject(
            "V1",
            "vineyard",
            "Synthetic vineyard; demand is not inferred from land use",
            _rectangle(1600, 1600, 3500, 2900),
        ),
        GeoObject(
            "F2",
            "forest",
            "Synthetic forest; demand is not assumed to be zero",
            _rectangle(4800, 2000, 6000, 4000),
        ),
        # Land use covering the rest of the study area, as mapped land use
        # usually does around rural settlements.
        GeoObject(
            "F3",
            "farmland",
            "Synthetic farmland west and south of S1; demand is not inferred from land use",
            _polygon(
                (0, 0), (1600, 0), (1600, 1000), (800, 1000), (800, 2800), (0, 2800)
            ),
        ),
        GeoObject(
            "F4",
            "farmland",
            "Synthetic farmland between S1 and S3; demand is not inferred from land use",
            _rectangle(800, 1600, 1600, 2900),
        ),
        GeoObject(
            "F5",
            "farmland",
            "Synthetic farmland along H2 east of S1; demand is not inferred from land use",
            _rectangle(1400, 1000, 4000, 1600),
        ),
        GeoObject(
            "F6",
            "farmland",
            "Synthetic farmland east of V1; demand is not inferred from land use",
            _rectangle(3500, 1600, 4000, 2900),
        ),
        GeoObject(
            "F7",
            "farmland",
            "Synthetic farmland south of S2; demand is not inferred from land use",
            _rectangle(4000, 0, 4800, 1000),
        ),
        GeoObject(
            "F8",
            "farmland",
            "Synthetic farmland in the south-east; demand is not inferred from land use",
            _rectangle(4800, 0, 6000, 2000),
        ),
        GeoObject(
            "W1",
            "forest",
            "Synthetic forest across the north; demand is not assumed to be zero",
            _polygon(
                (0, 2800),
                (800, 2800),
                (800, 3500),
                (1600, 3500),
                (1600, 2900),
                (4000, 2900),
                (4000, 3500),
                (4800, 3500),
                (4800, 4000),
                (0, 4000),
            ),
        ),
        GeoObject(
            "D0",
            "cell",
            "Synthetic down cell marker",
            _rectangle(990, 1290, 1010, 1310),
        ),
        GeoObject(
            "B1",
            "cell",
            "Synthetic available backup marker",
            _rectangle(1590, 1590, 1610, 1610),
        ),
        GeoObject(
            "B2",
            "cell",
            "Synthetic available backup marker",
            _rectangle(4090, 1190, 4110, 1210),
        ),
        GeoObject(
            "B3",
            "cell",
            "Synthetic available backup marker",
            _rectangle(4590, 2790, 4610, 2810),
        ),
    )


def _backup_signals(point: GridPoint) -> tuple[Signal, ...]:
    signals: list[Signal] = []
    for cell_id, x_m, y_m in (
        (CellId("B1"), 1600, 1600),
        (CellId("B2"), 4100, 1200),
        (CellId("B3"), 4600, 2800),
    ):
        distance = hypot(point.x_m - x_m, point.y_m - y_m)
        if distance <= 2300:
            signals.append(
                Signal(
                    cell_id,
                    round(-78 - distance / 60, 2),
                    round(-8 - distance / 330, 2),
                )
            )
    return tuple(signals)


def _make_record(point: GridPoint) -> CoverageRecord:
    """Generate spatially determined fictional measurements before any query."""
    x_m, y_m = point.x_m, point.y_m
    in_s2 = 4000 <= x_m <= 4800 and 1000 <= y_m <= 3500
    target_rsrp: float | None = None
    backups = _backup_signals(point)
    if in_s2:
        local_column, local_row = point.column - 40, point.row - 10
        if local_row < 5:
            if local_column < 4:
                target_rsrp = float(-111 + (local_row * 4 + local_column) % 8)
        else:
            if (local_column + 3 * local_row) % 19 == 0:
                return CoverageRecord(point.id, "missing", (), None)
            if (local_column + local_row) % 17 == 0:
                return CoverageRecord(point.id, "valid", (), 0.0)
            if local_row < 16 and local_column < 3:
                target_rsrp = float(-113 + (local_column + local_row) % 7)
    else:
        if (point.column * 3 + point.row * 5) % 97 == 0:
            return CoverageRecord(point.id, "missing", (), None)
        if (point.column + point.row * 3) % 53 == 0:
            return CoverageRecord(point.id, "valid", (), 0.0)
        distance = hypot(x_m - 1000, y_m - 1300)
        if distance <= 1450:
            target_rsrp = round(-79 - distance / 48, 2)
        elif 1200 <= x_m < 4000 and abs(y_m - 1250) <= 250:
            target_rsrp = round(-96 - (x_m - 1200) / 210, 2)
        if 800 <= x_m <= 1000 and 1000 <= y_m <= 1200:
            backups = ()
    if target_rsrp is None:
        return CoverageRecord(point.id, "valid", backups, 0.0)
    signals = (
        Signal(CellId("D0"), target_rsrp, round(-9 - abs(target_rsrp + 80) / 6, 2)),
        *backups,
    )
    # Nonuniform explicit D0 demand; geography labels are not a population proxy.
    traffic = round(0.3 + ((point.column * 3 + point.row * 7) % 13) * 0.11, 2)
    return CoverageRecord(point.id, "valid", signals, traffic)


def validate_record(record: CoverageRecord, down_cell_id: CellId) -> None:
    if not record.grid_id:
        raise ValueError("Coverage record grid_id is empty")
    if record.status not in {"valid", "missing"}:
        raise ValueError(f"Unknown data status at {record.grid_id}")
    if record.status == "missing":
        if record.cells or record.down_cell_traffic_mbps is not None:
            raise ValueError("Missing records cannot contain signals or known demand")
        return
    traffic = record.down_cell_traffic_mbps
    if traffic is None or not isfinite(traffic) or traffic < 0:
        raise ValueError("Valid synthetic records require finite nonnegative demand")
    cell_ids = [signal.cell_id for signal in record.cells]
    if len(set(cell_ids)) != len(cell_ids) or any(not cell_id for cell_id in cell_ids):
        raise ValueError("Signal cell IDs must be nonempty and unique")
    if any(
        not isfinite(signal.rsrp_dbm) or not isfinite(signal.rsrq_db)
        for signal in record.cells
    ):
        raise ValueError("Signals require finite measured RSRP and RSRQ")
    if down_cell_id not in cell_ids and traffic != 0:
        raise ValueError(
            "D0 demand requires observed D0 presence in this synthetic model"
        )


def build_dataset() -> Dataset:
    """Generate fictional geography, a full regular grid and pre-outage inputs."""
    grid = _make_grid()
    geography = _make_geography()
    records = tuple(_make_record(point) for point in grid)
    task = TaskInput(
        CellId("D0"),
        "2026-01-15T09:00:00Z",
        "Investigate the outage impact of cell D0 using synthetic pre-outage coverage and explicit synthetic demand.",
    )
    for record in records:
        validate_record(record, task.down_cell_id)
    return Dataset(
        task,
        100.0,
        grid,
        geography,
        records,
        tuple(
            record
            for cell, prb, capacity in (
                ("B1", 52.0, 70.0),
                ("B2", 68.0, 80.0),
                ("B3", 43.0, 65.0),
            )
            for record in (
                KPIRecord(
                    CellId(cell), "pre_outage", "prb_utilization", prb, "percent"
                ),
                KPIRecord(CellId(cell), "pre_outage", "capacity", capacity, "Mbps"),
            )
        ),
    )


def query_coverage(
    dataset: Dataset, parameters: QueryParameters, observation_id: ObservationId
) -> CoverageObservation:
    """Query the pre-generated records by geometry, independently of step IDs."""
    if not observation_id:
        raise ValueError("Observation ID cannot be empty")
    if parameters.grid_ids != select_grid(dataset.grid, parameters.geometry):
        raise ValueError(
            f"Query grid set of area {parameters.area_id} disagrees with its geometry"
        )
    if parameters.coordinate_system != COORDINATE_SYSTEM:
        raise ValueError("Query coordinate system does not match the dataset")
    if parameters.coverage_epoch != COVERAGE_EPOCH:
        raise ValueError(f"Only the {COVERAGE_EPOCH} coverage epoch exists")
    lookup = {record.grid_id: record for record in dataset.records}
    if len(lookup) != len(dataset.records):
        raise ValueError("Synthetic input has duplicate coverage grid IDs")
    if set(lookup) != {point.id for point in dataset.grid}:
        raise ValueError("Synthetic records must cover the entire analysis grid")
    # Selection is recomputed from actual geometry; no step identifier is consulted.
    selected_ids = select_grid(dataset.grid, parameters.geometry)
    records = tuple(lookup[grid_id] for grid_id in selected_ids)
    for record in records:
        validate_record(record, dataset.task.down_cell_id)
    missing = sum(record.status == "missing" for record in records)
    status = (
        "complete"
        if missing == 0
        else "all_missing"
        if missing == len(records)
        else "partial_missing"
    )
    return CoverageObservation(observation_id, "synthetic", parameters, status, records)
