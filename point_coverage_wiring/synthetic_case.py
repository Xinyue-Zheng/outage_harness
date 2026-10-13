"""A synthetic case for the per-point wiring: geometry, State 0 and a fake point API.

The shapes follow the internal State after split_geography: a geography.json
next to the run with grid, site, objects and areas (geometry plus grid ids);
a snapshot whose geography section carries the SHA-256 pointer, objects and
area metadata without coordinates; integer grid ids `row * columns + column`.

The fake API returns samples in the shape of synthetic_data_sample.json: each
sample has an info block with rsrq, rssi, a serving entry and top1..topN
entries, each with id, latitude, longitude, rsrp and sector_name. Signal
strengths come from distance to three synthetic sites; numbers are not real.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

DOWN_PREFIX = "CCL00001"
# Sector names use the internal pattern: enodeb id, sector tag, carrier index.
SITES: dict[str, tuple[float, float]] = {
    # name: (x_m, y_m) from the grid origin
    f"{DOWN_PREFIX}_aa_1": (1000.0, 1000.0),
    f"{DOWN_PREFIX}_ab_1": (1000.0, 1000.0),
    "CCL00002_aa_1": (1900.0, 1100.0),
    "CCL00003_ab_1": (300.0, 1700.0),
    "CCSN000004_aa_1": (1200.0, 300.0),  # NR: never an LTE backup
}
# Azimuth of each sector in degrees (compass); None is omnidirectional.
AZIMUTH: dict[str, float | None] = {
    f"{DOWN_PREFIX}_aa_1": 60.0,
    f"{DOWN_PREFIX}_ab_1": 240.0,
    "CCL00002_aa_1": 250.0,
    "CCL00003_ab_1": 120.0,
    "CCSN000004_aa_1": None,
}
GRID = {"origin_lat": 41.80, "origin_lon": -72.30, "spacing_m": 100.0, "rows": 20, "columns": 20}
SITE_LAT = 41.809
TOP_N = 3
RSRP_FLOOR = -112.0


def _lon_scale() -> float:
    return 111_320.0 * math.cos(math.radians(SITE_LAT))


def _to_latlon(x_m: float, y_m: float) -> tuple[float, float]:
    return GRID["origin_lat"] + y_m / 111_320.0, GRID["origin_lon"] + x_m / _lon_scale()


def _to_xy(lat: float, lon: float) -> tuple[float, float]:
    return (lon - GRID["origin_lon"]) * _lon_scale(), (lat - GRID["origin_lat"]) * 111_320.0


def _rsrp(cell: str, x_m: float, y_m: float) -> float:
    sx, sy = SITES[cell]
    distance = max(math.hypot(x_m - sx, y_m - sy), 30.0)
    value = -60.0 - 38.0 * math.log10(distance / 30.0)
    azimuth = AZIMUTH[cell]
    if azimuth is not None:
        bearing = math.degrees(math.atan2(x_m - sx, y_m - sy)) % 360
        off = min(abs(bearing - azimuth), 360 - abs(bearing - azimuth))
        value -= 12.0 * min(off / 90.0, 1.5) ** 2
    return value


def fake_point_api(lat: float, lon: float, radius_m: float, *, seed: int = 7) -> list[dict[str, Any]]:
    """Samples within radius_m of the point: 0 to 3 of them, each listing serving and top-N cells."""
    x, y = _to_xy(lat, lon)
    rng = random.Random(f"{seed}:{round(x)}:{round(y)}")
    count = rng.choice((0, 1, 2, 2, 3)) if rng.random() > 0.06 else 0
    samples = []
    for _ in range(count):
        angle, dist = rng.uniform(0, 2 * math.pi), rng.uniform(0, radius_m)
        sx, sy = x + dist * math.cos(angle), y + dist * math.sin(angle)
        levels = {cell: round(_rsrp(cell, sx, sy) + rng.gauss(0, 1.5), 2) for cell in SITES}
        heard = sorted((c for c in levels if levels[c] > RSRP_FLOOR), key=lambda c: -levels[c])
        if not heard:
            continue
        slat, slon = _to_latlon(sx, sy)

        def entry(cell: str) -> dict[str, Any]:
            return {"id": abs(hash(cell)) % 100000, "latitude": round(slat, 6), "longitude": round(slon, 6),
                    "rsrp": levels[cell], "sector_name": cell}

        info: dict[str, Any] = {"rsrq": round(rng.uniform(-14, -8), 2), "rssi": round(rng.uniform(-80, -60), 2),
                                "serving": entry(heard[0])}
        for index, cell in enumerate(heard[:TOP_N], start=1):
            info[f"top{index}"] = entry(cell)
        info["latitude"], info["longitude"] = round(slat, 6), round(slon, 6)
        samples.append({"info": info})
    return samples


def _cell_ids(x0: float, y0: float, x1: float, y1: float) -> list[str]:
    spacing, columns = GRID["spacing_m"], GRID["columns"]
    ids = []
    for row in range(GRID["rows"]):
        for column in range(columns):
            cx, cy = (column + 0.5) * spacing, (row + 0.5) * spacing
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                ids.append(str(row * columns + column))
    return ids


def _corridor_ids(points: list[tuple[float, float]], half_width: float) -> list[str]:
    spacing, columns = GRID["spacing_m"], GRID["columns"]
    ids = []
    for row in range(GRID["rows"]):
        for column in range(columns):
            cx, cy = (column + 0.5) * spacing, (row + 0.5) * spacing
            for (ax, ay), (bx, by) in zip(points, points[1:]):
                t = max(0.0, min(1.0, ((cx - ax) * (bx - ax) + (cy - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
                if math.hypot(cx - (ax + t * (bx - ax)), cy - (ay + t * (by - ay))) <= half_width:
                    ids.append(str(row * columns + column))
                    break
    return ids


def _polygon(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    corners = [_to_latlon(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    return {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in corners]]}


def build_case(run_dir: Path) -> dict[str, Any]:
    """Write geography.json and state_00.json into run_dir and return State 0."""
    run_dir.mkdir(parents=True, exist_ok=True)
    site_lat, site_lon = _to_latlon(*SITES[f"{DOWN_PREFIX}_aa_1"])
    road = [(0.0, 1300.0), (1000.0, 1050.0), (2000.0, 900.0)]
    objects = {
        "study_area": {"kind": "study_area", "description": "Synthetic 2 km square around the down site.",
                       "geometry": _polygon(0, 0, 2000, 2000)},
        "settlement_S1": {"kind": "settlement", "name": "S1", "tags": {"place": "village", "name": "S1"},
                          "description": "Synthetic village around the down site.",
                          "geometry": _polygon(700, 800, 1300, 1300)},
        "settlement_S2": {"kind": "settlement", "name": "S2", "tags": {"place": "hamlet", "name": "S2"},
                          "description": "Synthetic hamlet east of the site.",
                          "geometry": _polygon(1600, 900, 2000, 1300)},
        "road_H1": {"kind": "road", "geometry_kind": "polyline", "tags": {"highway": "primary"},
                    "description": "Synthetic primary road crossing the study area.",
                    "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lat, lon in map(lambda p: _to_latlon(*p), road)]}},
    }
    areas_grid = {
        "study_area": _cell_ids(0, 0, 2000, 2000),
        "S1": _cell_ids(700, 800, 1300, 1300),
        "S2": _cell_ids(1600, 900, 2000, 1300),
        "road_H1": _corridor_ids(road, 150.0),
        "F1": _cell_ids(0, 1400, 900, 2000),
    }
    descriptions = {
        "study_area": ("study_area", "The whole study area."),
        "S1": ("settlement", "S1 (village) settlement area."),
        "S2": ("settlement", "S2 (hamlet) settlement area."),
        "road_H1": ("road_corridor", "300 m corridor around the primary road H1."),
        "F1": ("landuse", "Farmland in the north-west; demand is not inferred from land use."),
    }
    geometry = {
        "coordinate_system": "WGS84 longitude/latitude geometries; local metre grid",
        "grid": dict(GRID),
        "site": {"lat": site_lat, "lon": site_lon},
        "study_area": {"side_m": 2000.0, "west": _to_latlon(0, 0)[1], "south": _to_latlon(0, 0)[0],
                       "east": _to_latlon(2000, 2000)[1], "north": _to_latlon(2000, 2000)[0]},
        "objects": {key: item["geometry"] for key, item in objects.items()},
        "areas": {area_id: {"geometry": objects.get(area_id, objects["study_area"])["geometry"], "grid_ids": ids}
                  for area_id, ids in areas_grid.items()},
    }
    encoded = (json.dumps(geometry, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    (run_dir / "geography.json").write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    sx, sy = SITES[f"{DOWN_PREFIX}_aa_1"]
    area_meta = {}
    for area_id, ids in areas_grid.items():
        kind, description = descriptions[area_id]
        centers = [((int(g) % GRID["columns"] + 0.5) * GRID["spacing_m"] - sx, (int(g) // GRID["columns"] + 0.5) * GRID["spacing_m"] - sy) for g in ids]
        nearest = min(math.hypot(dx, dy) for dx, dy in centers)
        area_meta[area_id] = {"id": area_id, "kind": kind, "description": description,
                              "grid_count": len(ids), "locations": len(ids),
                              "contains_site": nearest < GRID["spacing_m"],
                              "nearest_distance_from_site_m": round(nearest),
                              "center_distance_from_site_m": round(math.hypot(sum(dx for dx, _ in centers) / len(centers), sum(dy for _, dy in centers) / len(centers))),
                              "center_direction_from_site": "east" if sum(dx for dx, _ in centers) > 0 else "west"}
    state = {
        "id": "state_00",
        "task": {"down_cell_id": DOWN_PREFIX, "start_time": "2026-02-10T09:00:00Z", "end_time": "2026-02-10T12:00:00Z",
                 "objective": "Find where the outage sectors serve users and which cells can take over."},
        "coordinate_system": geometry["coordinate_system"],
        "grid": {"spacing_m": GRID["spacing_m"], "rows": GRID["rows"], "columns": GRID["columns"]},
        "site": {"metadata": {"site_name": "Synthetic site"}},
        "study_area": {"side_m": 2000.0, "rule": "2 km square centred on the site"},
        "geography": {
            "source": {"query_basic_information": "init_obs_00_cell", "query_osm_landuse": "init_obs_00_osm"},
            "geometry": {"path": "geography.json", "sha256": digest},
            "objects": {key: {k: v for k, v in item.items() if k != "geometry"} for key, item in objects.items()},
            "areas": area_meta,
            "relations": [{"subject": "road_H1", "predicate": "intersects", "object": "S1",
                           "evidence": "Polyline and polygon intersect in WGS84"}],
        },
        "areas": list(area_meta.values()),
        "coverage": {}, "coverage_artifacts": {}, "cells_seen": [], "outage_cells": [], "backup_candidates": [],
        "observations": [], "kpis": [], "notes": [], "unknowns": {},
        "query_budget": {"locations_spent": 0, "locations_limit": 600},
        "final_report_inputs": {"run_dir": run_dir.as_posix(), "case_state_path": (run_dir / "state.json").as_posix()},
    }
    (run_dir / "state_00.json").write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    return state


TOOL_DECLARATIONS = (
    {"name": "query_area_coverage",
     "description": "Fetch pre-outage coverage at every analysis grid location of one listed area through "
                    "the point API: for each location, every sample within the radius with its serving "
                    "sector and strongest neighbour cells and their RSRP.",
     "input_schema": {"type": "object", "properties": {"area_id": {"type": "string"}},
                      "required": ["area_id"], "additionalProperties": False}},
    {"name": "inspect_observation",
     "description": "Inspect existing coverage rows without another API query.",
     "input_schema": {"type": "object", "properties": {"observation_id": {"type": "string"}, "area_id": {"type": "string"},
                                                       "offset": {"type": "integer"}, "limit": {"type": "integer"}},
                      "required": ["observation_id", "area_id", "offset", "limit"], "additionalProperties": False}},
    {"name": "query_lte_rrc_prb",
     "description": "Hourly RRC and PRB KPI rows of LTE cells over a time window.",
     "input_schema": {"type": "object", "properties": {"cell_ids": {"type": "array", "items": {"type": "string"}},
                                                       "start_time": {"type": "string"}, "end_time": {"type": "string"}},
                      "required": ["cell_ids", "start_time", "end_time"], "additionalProperties": False}},
)
