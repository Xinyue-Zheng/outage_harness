"""Small planar geometry helpers; all coordinates and widths are metres."""

from itertools import pairwise
from math import isfinite

from outage_poc.models import Coordinate, Geometry, GridId, GridPoint


def validate_geometry(geometry: Geometry) -> None:
    """Reject unusable geometries rather than guessing a query footprint."""
    if geometry.kind not in {"polygon", "polyline", "buffer"}:
        raise ValueError(f"Unsupported geometry kind: {geometry.kind}")
    minimum = 3 if geometry.kind == "polygon" else 2
    if len(geometry.coordinates) < minimum:
        raise ValueError(f"{geometry.kind} needs at least {minimum} coordinates")
    if any(not isfinite(v) for point in geometry.coordinates for v in point):
        raise ValueError("Geometry coordinates must be finite")
    if len(set(geometry.coordinates)) < minimum:
        raise ValueError("Geometry has too few distinct coordinates")
    if any(a == b for a, b in pairwise(geometry.coordinates)):
        raise ValueError("Geometry has a zero-length segment")
    if geometry.kind == "buffer":
        width = geometry.buffer_width_m
        if width is None or not isfinite(width) or width <= 0:
            raise ValueError("A road buffer requires a positive finite full width")
    elif geometry.buffer_width_m is not None:
        raise ValueError("Only buffer geometry may specify buffer_width_m")
    if geometry.kind == "polygon":
        area_twice = sum(a[0] * b[1] - b[0] * a[1] for a, b in _segments(geometry))
        if area_twice == 0:
            raise ValueError("Polygon has zero signed area")
        segments = _segments(geometry)
        for index, (a, b) in enumerate(segments):
            for other_index in range(index + 2, len(segments)):
                if index == 0 and other_index == len(segments) - 1:
                    continue
                c, d = segments[other_index]
                if _segments_intersect(a, b, c, d):
                    raise ValueError("Polygon must be simple (no self-intersections)")


def _segments(geometry: Geometry) -> tuple[tuple[Coordinate, Coordinate], ...]:
    coordinates = geometry.coordinates
    segments = tuple(pairwise(coordinates))
    if geometry.kind == "polygon" and coordinates[-1] != coordinates[0]:
        return (*segments, (coordinates[-1], coordinates[0]))
    return segments


def _segment_distance_squared(
    point: Coordinate, start: Coordinate, end: Coordinate
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator == 0:
        raise ValueError("Cannot compute distance to a zero-length segment")
    fraction = max(
        0.0,
        min(
            1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator
        ),
    )
    return (point[0] - start[0] - fraction * dx) ** 2 + (
        point[1] - start[1] - fraction * dy
    ) ** 2


def _point_in_polygon(point: Coordinate, geometry: Geometry) -> bool:
    inside = False
    x, y = point
    for start, end in _segments(geometry):
        if _segment_distance_squared(point, start, end) <= 1e-12:
            return True
        if (start[1] > y) != (end[1] > y):
            crossing_x = start[0] + (y - start[1]) * (end[0] - start[0]) / (
                end[1] - start[1]
            )
            if x < crossing_x:
                inside = not inside
    return inside


def _covers_point(point: Coordinate, geometry: Geometry) -> bool:
    if geometry.kind == "polygon":
        return _point_in_polygon(point, geometry)
    width = geometry.buffer_width_m
    radius = width / 2 if geometry.kind == "buffer" and width is not None else 0.0
    return any(
        _segment_distance_squared(point, a, b) <= radius * radius + 1e-12
        for a, b in _segments(geometry)
    )


def covers_point(point: Coordinate, geometry: Geometry) -> bool:
    """Boundary-inclusive point selection; buffers are round-ended corridors."""
    validate_geometry(geometry)
    if any(not isfinite(v) for v in point):
        raise ValueError("Point coordinates must be finite")
    return _covers_point(point, geometry)


def select_grid(grid: tuple[GridPoint, ...], geometry: Geometry) -> tuple[GridId, ...]:
    """Select grid centres using the actual polygon or road buffer geometry."""
    validate_geometry(geometry)
    if len({point.id for point in grid}) != len(grid):
        raise ValueError("Grid IDs must be unique")
    if any(not isfinite(p.x_m) or not isfinite(p.y_m) for p in grid):
        raise ValueError("Grid coordinates must be finite")
    return tuple(
        point.id for point in grid if _covers_point((point.x_m, point.y_m), geometry)
    )


def query_boundary(
    queried_ids: set[GridId], unqueried_ids: set[GridId], grid: tuple[GridPoint, ...]
) -> tuple[GridId, ...]:
    """Queried centres with a four-neighbour centre in the supplied unknown set.

    The caller supplies an area's queried and unqueried sets. Diagonals,
    missing records and signal values do not determine boundary membership.
    """
    lookup = {point.id: point for point in grid}
    positions = {(point.column, point.row): point.id for point in grid}
    if len(lookup) != len(grid) or len(positions) != len(grid):
        raise ValueError("Grid IDs and row/column positions must be unique")
    if queried_ids & unqueried_ids:
        raise ValueError("Queried and unqueried sets overlap")
    if (queried_ids | unqueried_ids) - lookup.keys():
        raise ValueError("Boundary sets contain unknown grid IDs")
    result: list[GridId] = []
    for point in grid:
        if point.id not in queried_ids:
            continue
        if any(
            positions.get((point.column + dx, point.row + dy)) in unqueried_ids
            for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0))
        ):
            result.append(point.id)
    return tuple(result)


def _cross(start: Coordinate, end: Coordinate, point: Coordinate) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (
        point[0] - start[0]
    )


def _segments_intersect(
    a: Coordinate, b: Coordinate, c: Coordinate, d: Coordinate
) -> bool:
    sides = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    if sides[0] * sides[1] < 0 and sides[2] * sides[3] < 0:
        return True
    return any(
        _segment_distance_squared(point, start, end) <= 1e-12
        for point, start, end in ((a, c, d), (b, c, d), (c, a, b), (d, a, b))
    )


def geometries_intersect(first: Geometry, second: Geometry) -> bool:
    """Test polygon, centreline or round buffer intersection in the local plane."""
    validate_geometry(first)
    validate_geometry(second)
    if any(_covers_point(point, second) for point in first.coordinates) or any(
        _covers_point(point, first) for point in second.coordinates
    ):
        return True
    radius = sum(
        geometry.buffer_width_m / 2
        for geometry in (first, second)
        if geometry.kind == "buffer" and geometry.buffer_width_m is not None
    )
    for a, b in _segments(first):
        for c, d in _segments(second):
            if _segments_intersect(a, b, c, d):
                return True
            distances = (
                _segment_distance_squared(a, c, d),
                _segment_distance_squared(b, c, d),
                _segment_distance_squared(c, a, b),
                _segment_distance_squared(d, a, b),
            )
            if min(distances) <= radius * radius + 1e-12:
                return True
    return False


def bounds(geometry: Geometry) -> tuple[float, float, float, float]:
    """Left, bottom, right and top of the geometry's vertices."""
    validate_geometry(geometry)
    xs = [point[0] for point in geometry.coordinates]
    ys = [point[1] for point in geometry.coordinates]
    return min(xs), min(ys), max(xs), max(ys)


def within_distance(point: Coordinate, geometry: Geometry, distance_m: float) -> bool:
    """True when some part of the geometry lies within distance_m of the point."""
    validate_geometry(geometry)
    if not isfinite(distance_m) or distance_m < 0:
        raise ValueError("Distance must be finite and nonnegative")
    if geometry.kind == "polygon" and _point_in_polygon(point, geometry):
        return True
    width = geometry.buffer_width_m
    reach = distance_m + (width / 2 if geometry.kind == "buffer" and width else 0.0)
    return any(
        _segment_distance_squared(point, a, b) <= reach * reach + 1e-12
        for a, b in _segments(geometry)
    )


def make_grid(
    left: float, bottom: float, right: float, top: float, spacing_m: float
) -> tuple[GridPoint, ...]:
    """Regular grid of cell centres over a rectangle, in row-major order.

    Ids are G_r<row>_c<column>; the coverage source must use the same ids.
    """
    if not isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("Grid spacing must be finite and positive")
    columns = (right - left) / spacing_m
    rows = (top - bottom) / spacing_m
    if columns != int(columns) or rows != int(rows) or columns < 1 or rows < 1:
        raise ValueError(
            f"A {right - left:g} m by {top - bottom:g} m rectangle does not divide "
            f"into whole {spacing_m:g} m grid cells"
        )
    return tuple(
        GridPoint(
            GridId(f"G_r{row:02d}_c{column:02d}"),
            left + column * spacing_m + spacing_m / 2,
            bottom + row * spacing_m + spacing_m / 2,
            column,
            row,
        )
        for row in range(int(rows))
        for column in range(int(columns))
    )
