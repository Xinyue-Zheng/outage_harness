"""Per-point coverage for query_area_coverage.

The heatmap tool reports one serving sector per sampled coordinate, so it can
never show which other cells cover a location. The point API reports, for every
sample within a radius of a queried coordinate, the serving sector and the
strongest neighbour cells with their RSRP. Cells listed in one sample are
observed together at one measurement, which is the fact that backup analysis
needs.

This module keeps the three program responsibilities apart:

- fetch_area_points: one API call per analysis grid location of an area; the
  raw samples go to a JSON artifact in the run directory, nothing else.
- apply_point_coverage: fold one artifact into the State coverage table. Each
  queried location keeps every sample's cell list with RSRP, plus per-cell
  aggregates over its samples.
- refresh_summaries: per-area counts the context builder renders, including
  how many down-cell locations also report an eligible backup cell.

The LLM still names an area id. The program resolves the area to grid
locations and to coordinates; the model never outputs points.

State conventions follow evidence_state.py: dict State, geography.json next to
the run with a SHA-256 pointer in the snapshot, integer grid ids
`row * columns + column`, memberships from geography["areas"][id]["grid_ids"].
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# lat, lon, radius_m -> samples, as query_point_coverage returns data["array"].
PointQuery = Callable[[float, float, float], list[dict[str, Any]]]
IsOutage = Callable[[str], bool]
EligibleBackups = Callable[[Iterable[str]], list[str]]

_SAMPLE_CELL_KEYS_PREFIX = "top"
_NOT_LISTED = (
    "A cell that is not listed at a location is not shown to be absent there: the "
    "point API lists the serving sector and only the strongest neighbours of each sample."
)


# Geometry helpers.


def read_geometry(state: Mapping[str, Any], run_dir: str | Path) -> dict[str, Any]:
    """The geometry file the snapshot points at, after checking its SHA-256."""
    geography = state["geography"]
    pointer = geography.get("geometry") or geography.get("source", {}).get("geometry")
    if not isinstance(pointer, Mapping):
        raise ValueError("State geography has no geometry pointer")
    path = (Path(run_dir).resolve() / str(pointer["path"])).resolve()
    if not path.is_relative_to(Path(run_dir).resolve()):
        raise ValueError("Geometry pointer leaves the run directory")
    encoded = path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != pointer["sha256"]:
        raise ValueError("Geography SHA256 mismatch")
    return json.loads(encoded)


def grid_center(geometry: Mapping[str, Any], grid_id: str) -> tuple[float, float]:
    """Latitude and longitude of the centre of one analysis grid location.

    Inverse of evidence_state._locate: origin at the south-west corner, the
    longitude scale from the site latitude.
    """
    grid = geometry["grid"]
    if not str(grid_id).isdigit():
        raise ValueError(f"Grid ids must be integer strings, got {grid_id!r}")
    columns, spacing = int(grid["columns"]), float(grid["spacing_m"])
    row, column = divmod(int(grid_id), columns)
    site_lat = float(geometry["site"].get("lat", grid.get("origin_lat")))
    lon_scale = 111_320.0 * math.cos(math.radians(site_lat))
    lat = float(grid["origin_lat"]) + (row + 0.5) * spacing / 111_320.0
    lon = float(grid["origin_lon"]) + (column + 0.5) * spacing / lon_scale
    return lat, lon


def _memberships(geometry: Mapping[str, Any]) -> dict[str, list[str]]:
    memberships: dict[str, list[str]] = {}
    for area_id, area in geometry["areas"].items():
        for grid_id in area["grid_ids"]:
            memberships.setdefault(str(grid_id), []).append(area_id)
    return memberships


# Fetching.


def sample_cells(sample: Mapping[str, Any]) -> tuple[str | None, dict[str, float]]:
    """The serving sector name and every cell the sample lists with its RSRP.

    The serving entry and the top-N entries are read; a cell listed twice keeps
    its highest RSRP. An entry without a sector name or a finite RSRP is an
    error in the API contract and raises.
    """
    info = sample.get("info", sample)
    if not isinstance(info, Mapping):
        raise ValueError("A sample must be an object with an info block")
    cells: dict[str, float] = {}
    serving: str | None = None
    for key, entry in info.items():
        if key != "serving" and not str(key).startswith(_SAMPLE_CELL_KEYS_PREFIX):
            continue
        if not isinstance(entry, Mapping):
            raise ValueError(f"Sample entry {key} is not an object")
        name = entry.get("sector_name")
        rsrp = entry.get("rsrp")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Sample entry {key} has no sector_name")
        if isinstance(rsrp, bool) or not isinstance(rsrp, (int, float)) or not math.isfinite(rsrp):
            raise ValueError(f"Sample entry {key} ({name}) has no finite rsrp")
        value = float(rsrp)
        cells[name] = max(cells[name], value) if name in cells else value
        if key == "serving":
            serving = name
    return serving, cells


def fetch_area_points(
    state: Mapping[str, Any],
    area_id: str,
    run_dir: str | Path,
    query: PointQuery,
    *,
    radius_m: float,
    call_id: str,
    skip_queried: bool = True,
    workers: int = 1,
) -> dict[str, Any]:
    """Fetch every grid location of one area through the point API.

    Writes artifacts/<call_id>_<area_id>.json with one record per requested
    location: grid id, coordinates, status (valid, missing, error) and the raw
    samples. A location already in the coverage table is skipped when
    skip_queried is true, so overlapping areas never fetch a location twice.
    A failed call is recorded as error and the location stays unqueried.

    Returns a result summary in the shape runner._summarize produces, so
    _update_state and the provenance lines work unchanged.
    """
    geometry = read_geometry(state, run_dir)
    if area_id not in geometry["areas"]:
        raise ValueError(f"Unknown area {area_id!r}")
    if radius_m <= 0 or not math.isfinite(radius_m):
        raise ValueError("radius_m must be a positive number")
    table = state.get("coverage") or {}
    requested = [str(g) for g in geometry["areas"][area_id]["grid_ids"]]
    to_fetch = [g for g in requested if not (skip_queried and g in table)]

    def fetch_one(grid_id: str) -> dict[str, Any]:
        lat, lon = grid_center(geometry, grid_id)
        record: dict[str, Any] = {"grid_id": grid_id, "lat": lat, "lon": lon}
        try:
            samples = query(lat, lon, radius_m)
        except Exception as error:  # noqa: BLE001 - the API failure is data, recorded per point
            return {**record, "status": "error", "samples": [], "error": f"{type(error).__name__}: {error}"}
        if not isinstance(samples, list):
            return {**record, "status": "error", "samples": [], "error": "API did not return a list"}
        for sample in samples:
            sample_cells(sample)  # contract check; raises on a malformed sample
        return {**record, "status": "valid" if samples else "missing", "samples": samples}

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            points = list(pool.map(fetch_one, to_fetch))
    else:
        points = [fetch_one(g) for g in to_fetch]
    artifact = {
        "area_id": area_id,
        "radius_m": radius_m,
        "requested_grid_ids": requested,
        "skipped_already_queried": [g for g in requested if g not in to_fetch],
        "points": points,
    }
    path = (Path(run_dir).resolve() / "artifacts" / f"{call_id}_{area_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    counts = {status: sum(p["status"] == status for p in points) for status in ("valid", "missing", "error")}
    return {
        "status": "success" if counts["error"] < len(points) or not points else "error",
        "tool": "query_area_coverage",
        "output_file": str(path),
        "row_count": len(points),
        "columns": ["grid_id", "lat", "lon", "status", "samples"],
        "source": "point_api",
        "details": {
            "area_id": area_id,
            "radius_m": radius_m,
            "requested": len(requested),
            "fetched": len(to_fetch),
            "skipped_already_queried": len(requested) - len(to_fetch),
            **{f"{status}_points": count for status, count in counts.items()},
        },
        **({"error": f"{counts['error']} of {len(points)} point calls failed"} if counts["error"] == len(points) and points else {}),
    }


# Folding the artifact into State.


def _point_entry(point: Mapping[str, Any], observation_id: str, area_ids: list[str]) -> dict[str, Any]:
    """One coverage-table entry: every sample's cells with RSRP, and per-cell aggregates."""
    samples = []
    aggregates: dict[str, dict[str, Any]] = {}
    for raw in point["samples"]:
        serving, cells = sample_cells(raw)
        samples.append({"serving": serving, "cells": dict(sorted(cells.items()))})
        for cell, rsrp in cells.items():
            stats = aggregates.setdefault(cell, {
                "sample_count": 0, "serving_count": 0,
                "rsrp_min_dbm": rsrp, "rsrp_max_dbm": rsrp, "rsrp_sum_dbm": 0.0,
            })
            stats["sample_count"] += 1
            stats["serving_count"] += int(cell == serving)
            stats["rsrp_min_dbm"] = min(stats["rsrp_min_dbm"], rsrp)
            stats["rsrp_max_dbm"] = max(stats["rsrp_max_dbm"], rsrp)
            stats["rsrp_sum_dbm"] += rsrp
    for stats in aggregates.values():
        stats["rsrp_mean_dbm"] = round(stats.pop("rsrp_sum_dbm") / stats["sample_count"], 2)
    status = "valid" if samples else "missing"
    return {
        "status": status,
        "observation": observation_id,
        "area_ids": area_ids,
        "sample_count": len(samples),
        "samples": samples,
        "cells": dict(sorted(aggregates.items())),
    }


def apply_point_coverage(
    state: Mapping[str, Any],
    observation: Mapping[str, Any],
    run_dir: str | Path,
    is_outage: IsOutage,
    eligible_backups: EligibleBackups,
) -> dict[str, Any]:
    """Fold one point-coverage artifact into the coverage table and refresh summaries.

    A valid entry replaces whatever the table held for the location. A missing
    entry never replaces a valid one. An error point is not entered: the
    location stays unqueried and its count goes to the observation record.
    """
    geometry = read_geometry(state, run_dir)
    result = observation.get("result") or {}
    output = result.get("output_file")
    if not isinstance(output, str) or not output.endswith(".json"):
        raise ValueError("A point-coverage observation needs a JSON artifact path")
    path = Path(output)
    if not path.is_absolute():
        path = Path(run_dir) / path
    path = path.resolve()
    if not path.is_relative_to(Path(run_dir).resolve()) or not path.is_file():
        raise ValueError("Evidence artifact must be an existing file inside the run")
    artifact = json.loads(path.read_text(encoding="utf-8"))
    memberships = _memberships(geometry)
    observation_id = str(observation["id"])
    updated = copy.deepcopy(dict(state))
    table = updated.setdefault("coverage", {})
    errors: list[str] = []
    for point in artifact["points"]:
        grid_id = str(point["grid_id"])
        if grid_id not in memberships:
            raise ValueError(f"Artifact lists grid id {grid_id} outside every area")
        if point["status"] == "error":
            errors.append(grid_id)
            continue
        entry = _point_entry(point, observation_id, memberships[grid_id])
        if entry["status"] == "valid" or table.get(grid_id, {}).get("status") != "valid":
            table[grid_id] = entry
    record = {
        "id": observation_id,
        "action": observation.get("action", {}),
        "params": copy.deepcopy(observation.get("parameters", observation.get("action", {}).get("parameters", {}))),
        "requested_area_id": artifact["area_id"],
        "result": {
            "output_file": str(path.relative_to(Path(run_dir).resolve())),
            "status": result.get("status", "success"),
            **{key: value for key, value in (result.get("details") or {}).items()},
            "error_grid_ids": errors,
        },
    }
    items = updated.setdefault("observations", [])
    items[:] = [item for item in items if item.get("id", item.get("observation_id")) != observation_id]
    items.append(record)
    refresh_summaries(updated, geometry, is_outage, eligible_backups)
    return updated


# Summaries.


def _boundary(area_ids: list[str], queried: set[str], columns: int) -> set[str]:
    """Queried locations with an unqueried 4-neighbour inside the same area."""
    inside = set(area_ids)
    unqueried = inside - queried
    boundary: set[str] = set()
    for grid_id in queried & inside:
        row, column = divmod(int(grid_id), columns)
        for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            neighbour = str((row + dr) * columns + (column + dc))
            if 0 <= column + dc < columns and neighbour in unqueried:
                boundary.add(grid_id)
                break
    return boundary


def area_summary(
    state: Mapping[str, Any],
    grid_ids: list[str],
    columns: int,
    is_outage: IsOutage,
    eligible_backups: EligibleBackups,
) -> dict[str, Any]:
    """Counts for one area. Every count is over analysis grid locations.

    - down_cell_present: valid locations where at least one sample lists an
      outage cell.
    - down_cell_with_backup: of those, locations where some sample lists an
      eligible backup cell; down_cell_with_backup_same_sample narrows this to
      a backup listed in the same sample as the outage cell.
    - cells[cell]: present (valid locations listing it), strongest (locations
      where it has the highest RSRP), with_down_cell (locations where a sample
      lists both it and an outage cell), serving (locations where it serves at
      least one sample), RSRP min, max and mean over its samples.
    """
    table = state.get("coverage") or {}
    ids = [str(g) for g in grid_ids]
    entries = {g: table[g] for g in ids if g in table}
    valid = {g: e for g, e in entries.items() if e["status"] == "valid"}
    missing = {g for g, e in entries.items() if e["status"] == "missing"}
    cells: dict[str, dict[str, Any]] = {}
    down_present: set[str] = set()
    with_backup: set[str] = set()
    with_backup_same_sample: set[str] = set()
    no_coverage: set[str] = set()
    other_only: set[str] = set()
    all_cells = {cell for e in valid.values() for cell in e["cells"]}
    backups = set(eligible_backups(all_cells))
    for grid_id, entry in valid.items():
        listed = set(entry["cells"])
        if not listed:
            no_coverage.add(grid_id)
            continue
        outage_here = {c for c in listed if is_outage(c)}
        if outage_here:
            down_present.add(grid_id)
            if listed & backups:
                with_backup.add(grid_id)
            if any(
                any(is_outage(c) for c in s["cells"]) and set(s["cells"]) & backups
                for s in entry["samples"]
            ):
                with_backup_same_sample.add(grid_id)
        else:
            other_only.add(grid_id)
        strongest = min(entry["cells"], key=lambda c: (-entry["cells"][c]["rsrp_max_dbm"], c))
        together = {c for s in entry["samples"] if any(is_outage(x) for x in s["cells"]) for c in s["cells"]}
        for cell, stats in entry["cells"].items():
            summary = cells.setdefault(cell, {
                "present": 0, "strongest": 0, "with_down_cell": 0, "serving": 0,
                "sample_count": 0, "rsrp_min_dbm": stats["rsrp_min_dbm"],
                "rsrp_max_dbm": stats["rsrp_max_dbm"], "rsrp_sum_dbm": 0.0,
            })
            summary["present"] += 1
            summary["strongest"] += int(cell == strongest)
            summary["with_down_cell"] += int(cell in together and not is_outage(cell))
            summary["serving"] += int(stats["serving_count"] > 0)
            summary["sample_count"] += stats["sample_count"]
            summary["rsrp_min_dbm"] = min(summary["rsrp_min_dbm"], stats["rsrp_min_dbm"])
            summary["rsrp_max_dbm"] = max(summary["rsrp_max_dbm"], stats["rsrp_max_dbm"])
            summary["rsrp_sum_dbm"] += stats["rsrp_mean_dbm"] * stats["sample_count"]
    for summary in cells.values():
        summary["rsrp_mean_dbm"] = round(summary.pop("rsrp_sum_dbm") / summary["sample_count"], 2)
    boundary = _boundary(ids, set(entries), columns)
    return {
        "total": len(ids),
        "queried": len(entries),
        "unqueried": len(ids) - len(entries),
        "valid": len(valid),
        "missing": len(missing),
        "no_coverage": len(no_coverage),
        "other_cells_only": len(other_only),
        "down_cell_present": len(down_present),
        "down_cell_with_backup": len(with_backup),
        "down_cell_with_backup_same_sample": len(with_backup_same_sample),
        "down_cell_without_backup": len(down_present - with_backup),
        "boundary": len(boundary),
        "boundary_missing": len(boundary & missing),
        "boundary_with_down_cell": len(boundary & down_present),
        "outage_cells": sorted(c for c in all_cells if is_outage(c)),
        "backup_candidates": sorted(backups),
        "valid_sample_count": sum(e["sample_count"] for e in valid.values()),
        "cells": dict(sorted(cells.items())),
    }


def refresh_summaries(
    state: dict[str, Any],
    geometry: Mapping[str, Any],
    is_outage: IsOutage,
    eligible_backups: EligibleBackups,
) -> None:
    """Recompute summaries, regions, cell lists and the coverage unknowns in place."""
    columns = int(geometry["grid"]["columns"])
    state["summaries"] = {
        area_id: area_summary(state, area["grid_ids"], columns, is_outage, eligible_backups)
        for area_id, area in geometry["areas"].items()
    }
    state["regions"] = [{"area_id": area_id, **copy.deepcopy(summary)}
                        for area_id, summary in state["summaries"].items()]
    table = state.get("coverage") or {}
    cells = sorted({cell for entry in table.values() if entry["status"] == "valid" for cell in entry["cells"]})
    state["cells_seen"] = cells
    state["outage_cells"] = [cell for cell in cells if is_outage(cell)]
    state["backup_candidates"] = eligible_backups(cells)
    known = {str(g) for area in geometry["areas"].values() for g in area["grid_ids"]}
    unknowns = state.setdefault("unknowns", {})
    unknowns["coverage"] = {
        "areas_unqueried": sum(s["queried"] == 0 for s in state["summaries"].values()),
        "locations_unqueried": len(known - set(table)),
        "locations_missing": sum(e["status"] == "missing" for e in table.values()),
        "not_listed": _NOT_LISTED,
    }
    unknowns.pop("simultaneous_cell_overlap", None)
    unknowns["backup_cells"] = (
        "Backup candidates are cells of the outage technology seen in valid samples; "
        "their load after the outage traffic moves is not verified."
    )


def inspect_point_coverage(
    state: Mapping[str, Any], observation_id: str | None, area_id: str | None, offset: int, limit: int
) -> list[dict[str, Any]]:
    """Page coverage-table rows by observation and area, without the raw samples."""
    if isinstance(offset, bool) or isinstance(limit, bool) or offset < 0 or limit < 0:
        raise ValueError("offset and limit must be nonnegative integers")
    if area_id is not None and area_id not in state["geography"]["areas"]:
        raise ValueError(f"Unknown area: {area_id}")
    rows = [
        {"grid_id": grid_id, **{k: copy.deepcopy(v) for k, v in entry.items() if k != "samples"}}
        for grid_id, entry in sorted(state.get("coverage", {}).items(), key=lambda kv: int(kv[0]))
        if (observation_id is None or entry["observation"] == observation_id)
        and (area_id is None or area_id in entry["area_ids"])
    ]
    return rows[offset:offset + limit]
