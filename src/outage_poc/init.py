"""Initialization: fixed program logic that runs before the first decision.

Two lookups (the down cell's site, then the geography around it), then the
program derives the analysis grid, the areas and the spatial relations, and
builds State 0. The model is not consulted. Backup cells are not known here;
they enter State when a coverage record lists them.
"""

from collections.abc import Mapping
from typing import assert_never

from outage_poc.data_client import (
    DataClient,
    Rows,
    ToolFailure,
    ToolResult,
    ToolTimeout,
)
from outage_poc.geometry import (
    bounds,
    covers_point,
    geometries_intersect,
    make_grid,
    select_grid,
)
from outage_poc.models import (
    Area,
    AreaId,
    CellId,
    GeoKind,
    Geometry,
    GeoObject,
    GridPoint,
    QueryParameters,
    RunConfig,
    SpatialRelation,
    State,
    Task,
    TaskInput,
)
from outage_poc.persistence import _field, _geometry, _number, _object, _string
from outage_poc.state import COORDINATE_SYSTEM, STUDY_AREA, initial_state

COVERAGE_EPOCH = "pre_outage"
# Declared full width of each road corridor, keyed by road id.
CORRIDOR_WIDTHS_M: Mapping[str, float] = {"H1": 300.0, "H2": 500.0}
_GEO_KINDS: tuple[GeoKind, ...] = (
    "settlement",
    "highway",
    "farmland",
    "vineyard",
    "forest",
    "study_area",
)


def _rectangle(left: float, bottom: float, right: float, top: float) -> Geometry:
    if left >= right or bottom >= top:
        raise ValueError("Rectangle bounds must have positive width and height")
    return Geometry(
        "polygon", ((left, bottom), (right, bottom), (right, top), (left, top)), None
    )


def derive_areas(
    grid: tuple[GridPoint, ...],
    geography: tuple[GeoObject, ...],
    grid_spacing_m: float,
    corridor_widths_m: Mapping[str, float] = CORRIDOR_WIDTHS_M,
) -> tuple[Area, ...]:
    """The queryable areas: one per geography object, plus two sub-areas of S2.

    Rules:
    - A settlement, land-use object or the study area is an area with its own
      geometry; every area except the study area has the study area as parent.
    - A highway is a centreline, not an area. Its area is the round-ended
      corridor `<road>_buffer` with the declared full width of that road in
      `corridor_widths_m` (H1 300 m, H2 500 m by default). A road without a
      declared width is an error.
    - S2 has two sub-areas: `S2_roadside`, the five southern grid rows of S2
      next to H2, and `S2_remaining`, the rest of S2. The manual trace queried
      only the roadside part of a settlement; this split keeps that case
      available as an area. It is a case-specific choice, not a validated rule.
    - Cell sites are not areas.
    """
    areas: list[Area] = []
    for item in geography:
        if item.kind == "cell":
            continue
        if item.kind == "highway":
            if item.id not in corridor_widths_m:
                raise ValueError(f"No declared corridor width for road {item.id}")
            width = corridor_widths_m[item.id]
            geometry = Geometry("buffer", item.geometry.coordinates, width)
            area_id = AreaId(f"{item.id}_buffer")
            description = (
                f"Round-ended road corridor for {item.id}; full width {width:g} m"
            )
        else:
            geometry = item.geometry
            area_id = AreaId(item.id)
            description = item.description
        areas.append(
            Area(
                area_id,
                description,
                geometry,
                select_grid(grid, geometry),
                None if area_id == STUDY_AREA else STUDY_AREA,
            )
        )
    s2 = [item for item in geography if item.id == "S2"]
    if len(s2) == 1:
        left, bottom, right, top = bounds(s2[0].geometry)
        split = bottom + 5 * grid_spacing_m
        for area_id, description, geometry in (
            (
                "S2_roadside",
                "Roadside section of S2 (southern five grid rows)",
                _rectangle(left, bottom, right, split),
            ),
            (
                "S2_remaining",
                "Interior part of S2 beyond the roadside section; querying determines its coverage",
                _rectangle(left, split, right, top),
            ),
        ):
            areas.append(
                Area(
                    AreaId(area_id),
                    description,
                    geometry,
                    select_grid(grid, geometry),
                    AreaId("S2"),
                )
            )
    return tuple(areas)


def derive_relations(geography: tuple[GeoObject, ...]) -> tuple[SpatialRelation, ...]:
    """Containment in the study area, and which highways intersect which settlements."""
    relations: list[SpatialRelation] = []
    studies = [item for item in geography if item.kind == "study_area"]
    if len(studies) != 1:
        raise ValueError("Geography must contain exactly one study area")
    study = studies[0]
    for item in geography:
        if item.id != study.id and all(
            covers_point(point, study.geometry) for point in item.geometry.coordinates
        ):
            relations.append(
                SpatialRelation(
                    study.id,
                    "contains",
                    item.id,
                    "All geometry vertices lie in the convex rectangular study area",
                )
            )
    for highway in (item for item in geography if item.kind == "highway"):
        for settlement in (item for item in geography if item.kind == "settlement"):
            if geometries_intersect(highway.geometry, settlement.geometry):
                relations.append(
                    SpatialRelation(
                        highway.id,
                        "intersects",
                        settlement.id,
                        "Polyline and polygon intersect in synthetic local metre coordinates",
                    )
                )
    return tuple(relations)


def resolve_area(
    grid: tuple[GridPoint, ...], areas: tuple[Area, ...], area_id: str
) -> QueryParameters:
    """Resolve a known area id to auditable query parameters."""
    matches = [area for area in areas if area.id == area_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one area for {area_id!r}")
    area = matches[0]
    actual_ids = select_grid(grid, area.geometry)
    if actual_ids != area.grid_ids:
        raise ValueError(f"Area {area_id} disagrees with its geometric selection")
    if not actual_ids:
        raise ValueError(f"Area {area_id} contains no analysis grid locations")
    return QueryParameters(
        area.id, area.geometry, actual_ids, COORDINATE_SYSTEM, COVERAGE_EPOCH
    )


def build_initial_state(
    task: Task, geography: tuple[GeoObject, ...], grid_spacing_m: float
) -> State:
    """State 0 from the looked-up task and geography. Pure; no data access."""
    studies = [item for item in geography if item.kind == "study_area"]
    if len(studies) != 1 or studies[0].id != STUDY_AREA:
        raise ValueError(f"Geography must contain exactly one study area {STUDY_AREA}")
    grid = make_grid(*bounds(studies[0].geometry), grid_spacing_m)
    return initial_state(
        task,
        grid_spacing_m,
        grid,
        geography,
        derive_relations(geography),
        derive_areas(grid, geography, grid_spacing_m),
    )


def _rows(name: str, result: ToolResult) -> list[dict[str, object]]:
    match result:
        case Rows(rows=rows):
            return list(rows)
        case ToolTimeout(timeout_s=timeout_s):
            raise ValueError(f"Initialization: {name} timed out after {timeout_s:g} s")
        case ToolFailure(message=message):
            raise ValueError(f"Initialization: {name} failed: {message}")
        case _ as unreachable:
            assert_never(unreachable)


def _geo_object(row: dict[str, object]) -> GeoObject:
    kind = _string(_field(row, "kind"))
    matches = [known for known in _GEO_KINDS if known == kind]
    if not matches:
        raise ValueError(f"osm.geometry returned unsupported kind {kind!r}")
    return GeoObject(
        _string(_field(row, "id")),
        matches[0],
        _string(_field(row, "description")),
        _geometry(_field(row, "geometry")),
    )


def initialize(task: TaskInput, client: DataClient, config: RunConfig) -> State:
    """Look up the down cell's site and the geography around it, then build State 0."""
    cell_rows = _rows(
        "cell.lookup",
        client.call(
            "cell.lookup", {"cell_id": task.down_cell_id}, config.query_timeout_s
        ),
    )
    if len(cell_rows) != 1:
        raise ValueError(f"cell.lookup returned {len(cell_rows)} rows, expected 1")
    cell = cell_rows[0]
    if CellId(_string(_field(cell, "cell_id"))) != task.down_cell_id:
        raise ValueError("cell.lookup returned a different cell")
    metadata = _object(_field(cell, "metadata"))
    if _string(_field(metadata, "kind")) != "cell":
        raise ValueError("cell.lookup metadata does not describe a cell")
    # Coverage is evidence only from before the outage; the epoch is fixed here, once.
    site = Task(
        task.down_cell_id,
        task.outage_time,
        task.objective,
        _number(_field(cell, "x_m")),
        _number(_field(cell, "y_m")),
        COVERAGE_EPOCH,
    )
    geography_rows = _rows(
        "osm.geometry",
        client.call(
            "osm.geometry",
            {
                "center_x_m": site.site_x_m,
                "center_y_m": site.site_y_m,
                "radius_m": config.init_radius_m,
            },
            config.query_timeout_s,
        ),
    )
    geography = tuple(_geo_object(row) for row in geography_rows)
    return build_initial_state(site, geography, config.grid_spacing_m)
