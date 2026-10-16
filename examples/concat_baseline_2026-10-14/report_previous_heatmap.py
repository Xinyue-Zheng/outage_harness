"""Generate a final, provenance-aware report from a completed investigation."""
from __future__ import annotations
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from outage_harness_langgraph.radio import is_outage_cell, outage_prefixes

REPORT_TOOL_DESCRIPTION = (
    "Create the final Markdown and JSON outage report from completed live run artifacts."
)

def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value

def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None

def _ring_area(ring: list[list[float]]) -> float:
    return abs(sum(
        ring[index][0] * ring[index + 1][1] - ring[index + 1][0] * ring[index][1]
        for index in range(len(ring) - 1)
    ) / 2)

def _point_in_ring(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    inside = False
    previous = len(ring) - 1
    for current in range(len(ring)):
        x1, y1 = ring[current]
        x2, y2 = ring[previous]
        if (y1 > latitude) != (y2 > latitude):
            crossing = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing:
                inside = not inside
        previous = current
    return inside

def _load_landuse(path: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if path is None or not path.is_file():
        return [], {"available": False, "reason": "No saved OSM land-use GeoJSON artifact was supplied."}
    collection = _load_json(path)
    features: list[dict[str, Any]] = []
    categories: Counter[str] = Counter()
    for feature in collection.get("features", []):
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        rings = geometry.get("coordinates", []) if geometry.get("type") == "Polygon" else []
        if not rings or not rings[0] or not properties.get("landuse"):
            continue
        exterior = rings[0]
        longitudes = [point[0] for point in exterior]
        latitudes = [point[1] for point in exterior]
        features.append({
            "landuse": str(properties["landuse"]), "rings": rings,
            "area": _ring_area(exterior),
            "bbox": (min(longitudes), min(latitudes), max(longitudes), max(latitudes)),
        })
        categories[str(properties["landuse"])] += 1
    return features, {
        "available": bool(features), "file": path.as_posix(),
        "source": collection.get("source", "OpenStreetMap Overpass API"),
        "feature_count": len(features),
        "landuse_feature_counts": dict(sorted(categories.items())),
        "assignment_rule": "smallest-area containing OSM polygon; unmatched points remain unmapped",
    }

def _classify_landuse(
    longitude: float, latitude: float,
    spatial_index: dict[tuple[int, int], list[dict[str, Any]]], bin_size: float,
) -> str | None:
    matches = []
    key = (math.floor(longitude / bin_size), math.floor(latitude / bin_size))
    for feature in spatial_index.get(key, []):
        min_lng, min_lat, max_lng, max_lat = feature["bbox"]
        if not (min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat):
            continue
        rings = feature["rings"]
        if not _point_in_ring(longitude, latitude, rings[0]):
            continue
        if any(_point_in_ring(longitude, latitude, hole) for hole in rings[1:]):
            continue
        matches.append(feature)
    if not matches:
        return None
    return min(matches, key=lambda feature: feature["area"])["landuse"]

def _index_landuse(
    features: list[dict[str, Any]], bin_size: float = 0.005
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    index: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for feature in features:
        min_lng, min_lat, max_lng, max_lat = feature["bbox"]
        x_start, x_end = math.floor(min_lng / bin_size), math.floor(max_lng / bin_size)
        y_start, y_end = math.floor(min_lat / bin_size), math.floor(max_lat / bin_size)
        for x_bin in range(x_start, x_end + 1):
            for y_bin in range(y_start, y_end + 1):
                index[(x_bin, y_bin)].append(feature)
    return index

def _coverage_summary(
    path: Path, landuse_path: Path | None = None,
    down_cell_ids: list[str] | None = None,
) -> dict[str, Any]:
    down_cell_ids = down_cell_ids or ["ec1a0000"]
    down_label = "_and_".join(down_cell_ids) + "_served"
    rows = 0
    statuses: Counter[str] = Counter()
    rsrp_sum = 0.0
    rsrp_count = 0
    rsrp_min: float | None = None
    rsrp_max: float | None = None
    area_groups: dict[str, dict[str, Any]] = {
        label: {
            "rows": 0, "rsrp_sum": 0.0, "rsrp_count": 0,
            "latitude_min": None, "latitude_max": None,
            "longitude_min": None, "longitude_max": None,
        }
        for label in (down_label, "other_cell_served")
    }
    seen_coordinates: set[tuple[float, float]] = set()
    landuse_features, landuse_metadata = _load_landuse(landuse_path)
    landuse_bin_size = 0.005
    landuse_spatial_index = _index_landuse(landuse_features, landuse_bin_size)
    sample_cell_size = 0.001
    landuse_samples: dict[tuple[str, int, int], tuple[float, tuple[float, float]]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        required = {"lng", "lat", "serving_sector_name", "status", "mean_RSRP_dBm"}
        if not required <= set(columns):
            return {"file": path.as_posix(), "error": "Unexpected heatmap CSV schema"}
        for row in reader:
            longitude = _number(row.get("lng"))
            latitude = _number(row.get("lat"))
            if longitude is None or latitude is None:
                continue
            coordinate = (longitude, latitude)
            if coordinate in seen_coordinates:
                continue
            seen_coordinates.add(coordinate)
            rows += 1
            status = (row.get("status") or "").strip()
            if status:
                statuses[status] += 1
            sector = (row.get("serving_sector_name") or "").strip()
            is_down_sector = is_outage_cell(sector, {"outage_cell_ids": down_cell_ids})
            group_name = down_label if is_down_sector else "other_cell_served"
            area = area_groups[group_name]
            area["rows"] += 1
            if landuse_features:
                grid_x = math.floor(longitude / sample_cell_size)
                grid_y = math.floor(latitude / sample_cell_size)
                center_x = (grid_x + 0.5) * sample_cell_size
                center_y = (grid_y + 0.5) * sample_cell_size
                distance = (longitude - center_x) ** 2 + (latitude - center_y) ** 2
                sample_key = (group_name, grid_x, grid_y)
                current_sample = landuse_samples.get(sample_key)
                if current_sample is None or distance < current_sample[0]:
                    landuse_samples[sample_key] = (distance, coordinate)
            for axis, value in (("latitude", latitude), ("longitude", longitude)):
                minimum = f"{axis}_min"
                maximum = f"{axis}_max"
                area[minimum] = value if area[minimum] is None else min(area[minimum], value)
                area[maximum] = value if area[maximum] is None else max(area[maximum], value)
            rsrp = _number(row.get("mean_RSRP_dBm"))
            if rsrp is not None:
                rsrp_sum += rsrp
                rsrp_count += 1
                rsrp_min = rsrp if rsrp_min is None else min(rsrp_min, rsrp)
                rsrp_max = rsrp if rsrp_max is None else max(rsrp_max, rsrp)
                area["rsrp_sum"] += rsrp
                area["rsrp_count"] += 1
    for (group_name, _, _), (_, (longitude, latitude)) in landuse_samples.items():
        category = _classify_landuse(longitude, latitude, landuse_spatial_index, landuse_bin_size)
        area_groups[group_name].setdefault("landuse_counts", Counter())[category or "unmapped"] += 1
    for area in area_groups.values():
        area["share_of_unique_heatmap_locations_percent"] = 100 * area["rows"] / rows if rows else None
        area["mean_rsrp_dbm"] = area["rsrp_sum"] / area["rsrp_count"] if area["rsrp_count"] else None
        area["latitude_range"] = [area.pop("latitude_min"), area.pop("latitude_max")]
        area["longitude_range"] = [area.pop("longitude_min"), area.pop("longitude_max")]
        area.pop("rsrp_sum")
        area.pop("rsrp_count")
        counts = area.pop("landuse_counts", Counter())
        area["land_use_counts"] = dict(sorted(counts.items()))
        landuse_sample_count = sum(counts.values())
        area["land_use_percentages"] = {
            category: 100 * count / landuse_sample_count if landuse_sample_count else None
            for category, count in sorted(counts.items())
        }
        mapped = {key: value for key, value in counts.items() if key != "unmapped"}
        area["dominant_land_use"] = max(mapped, key=mapped.get) if mapped else None
        area["land_use_note"] = (
            "Approximate land-use shares use a deterministic one-point-per-0.001-degree "
            "grid-cell sample within this serving group. Overlapping OSM ways resolve "
            "to the smallest polygon; unmapped sample points are retained."
            if landuse_features else landuse_metadata["reason"]
        )
        area["land_use_sample_points"] = landuse_sample_count
        area["connection_loss_percent"] = None
        area["degradation_risk_percent"] = None
        area["retained_service_percent"] = None
    return {
        "file": path.as_posix(), "source": "live_query_library", "rows": rows,
        "row_semantics": "unique WGS84 heatmap coordinates",
        "status_counts": dict(statuses), "areas": area_groups,
        "landuse_source": landuse_metadata,
        "landuse_assignment": {
            "method": "deterministic stratified point sample; nearest heatmap point to each 0.001-degree grid-cell center per serving group",
            "sample_points": len(landuse_samples),
            "sample_cell_degrees": sample_cell_size,
            "percentage_type": "approximate sample share, not full point-level census",
        },
        "outcome_percentages": {
            "connection_loss": None, "service_degradation": None,
            "retained_service": None, "not_influenced": None,
            "reason": (
                "The heatmap provides one serving-sector observation per point, not "
                "alternative-backup RSRP, post-outage traffic, or per-location capacity."
            ),
        },
        "mean_rsrp_dbm_all_rows": rsrp_sum / rsrp_count if rsrp_count else None,
        "rsrp_min_dbm": rsrp_min, "rsrp_max_dbm": rsrp_max,
        "interpretation_note": (
            "Heatmap values describe modeled/pre-outage coverage by serving sector; "
            "rows are not unique population counts or measured outage-time users."
        ),
    }

def _kpi_summary(path: Path, cell_column: str, outage_start: str, outage_end: str) -> dict[str, Any]:
    outage_start_dt = datetime.fromisoformat(outage_start)
    outage_end_dt = datetime.fromisoformat(outage_end)
    reference_start = outage_start_dt.replace(day=outage_start_dt.day) - __import__("datetime").timedelta(days=7)
    reference_end = outage_end_dt - __import__("datetime").timedelta(days=7)
    cells: set[str] = set()
    outage_rows = 0
    reference_rows = 0
    outage_rrc: list[float] = []
    reference_rrc: list[float] = []
    outage_prb: list[float] = []
    reference_prb: list[float] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"DATETIMEUTC", cell_column, "AVG_RRC_USERS", "MEAN_PRB_USED"}
        if not required <= set(reader.fieldnames or []):
            return {"file": path.as_posix(), "error": f"Missing columns: {sorted(required)}"}
        for row in reader:
            cell = (row.get(cell_column) or "").strip()
            timestamp = (row.get("DATETIMEUTC") or "").strip()
            if not cell or not timestamp:
                continue
            cells.add(cell)
            moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if moment.tzinfo:
                moment = moment.replace(tzinfo=None)
            rrc = _number(row.get("AVG_RRC_USERS"))
            prb = _number(row.get("MEAN_PRB_USED"))
            if outage_start_dt <= moment <= outage_end_dt:
                outage_rows += 1
                if rrc is not None:
                    outage_rrc.append(rrc)
                if prb is not None:
                    outage_prb.append(prb)
            elif reference_start <= moment <= reference_end:
                reference_rows += 1
                if rrc is not None:
                    reference_rrc.append(rrc)
                if prb is not None:
                    reference_prb.append(prb)
    return {
        "file": path.as_posix(), "source": "live_query_library",
        "cell_column": cell_column, "cells": len(cells), "cell_ids": sorted(cells),
        "outage_window": {"start": outage_start, "end": outage_end},
        "outage_rows": outage_rows,
        "outage_mean_rrc_users_across_cell_hours": sum(outage_rrc) / len(outage_rrc) if outage_rrc else None,
        "outage_mean_prb_source_units_across_cell_hours": sum(outage_prb) / len(outage_prb) if outage_prb else None,
        "reference_window": {
            "start": reference_start.isoformat(sep=" "),
            "end": reference_end.isoformat(sep=" "),
            "basis": "same hours one week earlier",
        },
        "reference_rows": reference_rows,
        "reference_mean_rrc_users_across_cell_hours": sum(reference_rrc) / len(reference_rrc) if reference_rrc else None,
        "reference_mean_prb_source_units_across_cell_hours": sum(reference_prb) / len(reference_prb) if reference_prb else None,
        "interpretation_note": (
            "These are averages across queried cell-hour rows, not a causal outage effect. "
            "PRB units are preserved from the query CSV and are not relabeled as percent."
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    case = report["case"]
    coverage = report["live_evidence"].get("coverage")
    lte = report["live_evidence"].get("lte_kpi")
    nr = report["live_evidence"].get("nr_kpi")
    areas = coverage.get("areas", {}) if coverage else {}

    def format_range(values: list[float | None] | None) -> str:
        if not values or len(values) != 2 or None in values:
            return "unavailable"
        return f"{values[0]:.6f} to {values[1]:.6f}"

    down_cell_ids = outage_prefixes(report["case"].get("outage_cell_ids") or report["case"]["down_cell_id"])
    down_label = "_and_".join(down_cell_ids) + "_served"

    def area_paragraph(label: str, key: str, description: str) -> str:
        area = areas.get(key)
        if not area:
            return f"{label}: area classification is unavailable because the live heatmap is missing."
        share = area.get("share_of_unique_heatmap_locations_percent")
        share_text = f"{share:.1f}%" if isinstance(share, int | float) else "unavailable"
        landuse_percentages = area.get("land_use_percentages", {})
        landuse_text = ", ".join(
            f"{category} {percentage:.1f}%"
            for category, percentage in sorted(
                landuse_percentages.items(), key=lambda item: (-item[1], item[0]),
            )
        ) or "unavailable"
        return (
            f"{label} ({description}; coordinate envelope latitude {format_range(area.get('latitude_range'))}, "
            f"longitude {format_range(area.get('longitude_range'))}; this envelope is not a polygon boundary) "
            f"is mainly {area.get('dominant_land_use') or 'land use unavailable'} "
            f"(sampled land-use mix: {landuse_text}) and contains {share_text} of unique heatmap locations. "
            f"This is a pre-outage serving-footprint share, not a service-outcome share. Connection-loss, "
            f"degradation-risk, and retained-service shares are not estimable from the "
            f"available data. The sector and mean RSRP describe modeled pre-outage coverage, "
            f"not outage-time outcomes."
        )

    lines = [
        f"# Final Outage Report: {case['down_cell_id']}", "",
        f"- Outage window: {case['outage_time']}",
        f"- Objective: {case['objective']}",
        f"- Generated: {report['generated_at']}",
        "- Run status: evidence collection completed; report is program-generated from recorded artifacts.",
        "", "## Live Evidence", "",
    ]
    if coverage:
        lines.extend([
            f"- Coverage rows: {coverage.get('rows')} {coverage.get('row_semantics', 'rows')}.",
            f"- Mean RSRP over all heatmap locations: {coverage.get('mean_rsrp_dbm_all_rows')} dBm.",
            f"- Coverage source: `{coverage.get('file')}`.",
            "", "## Area Impact Summary", "",
            f"OSM source: {coverage.get('landuse_source', {}).get('source', 'unavailable')}; "
            f"{coverage.get('landuse_source', {}).get('feature_count', 0)} land-use polygons.",
            f"Land-use mix is an approximate spatial sample ({coverage.get('landuse_assignment', {}).get('sample_points', 0)} "
            f"sampled locations at {coverage.get('landuse_assignment', {}).get('sample_cell_degrees', 'n/a')} degrees); "
            "overlapping polygons resolve to the smallest containing polygon and unmatched samples are unmapped.",
            "",
            area_paragraph("Area A", down_label, f"modeled pre-outage {' and '.join(down_cell_ids)}-served footprint"),
            "",
            area_paragraph("Area B", "other_cell_served", "modeled pre-outage other-cell-served footprint"),
            "",
            "The rest of the map is not classified as unaffected: it is outside these observed heatmap groups or lacks outage-impact evidence.",
            "",
            "Requested connection-loss, degradation, retained-service, and not-influenced percentages are withheld "
            "rather than inferred from a single-serving-sector heatmap.",
            "", "### Performance Context", "",
        ])
    for title, summary in (("LTE KPIs", lte), ("NR KPIs", nr)):
        if summary:
            lines.extend([
                f"- {title}: {summary.get('cells')} cells, {summary.get('outage_rows')} outage-window cell-hours; "
                f"outage mean RRC users {summary.get('outage_mean_rrc_users_across_cell_hours')}; "
                f"reference-week mean {summary.get('reference_mean_rrc_users_across_cell_hours')}; "
                f"PRB source-unit means {summary.get('outage_mean_prb_source_units_across_cell_hours')} "
                f"vs {summary.get('reference_mean_prb_source_units_across_cell_hours')}.",
                f"  Source: `{summary.get('file')}`. {summary.get('interpretation_note')}",
            ])
    lines.extend([
        "", "## Limitations", "",
        "- Coverage heatmap is coverage-model output and not a count of affected people or outage-time subscribers.",
        "- Land-use polygons were fetched from overpass and saved as tagged GeoJSON; point assignment uses the disclosed spatial sample, smallest-polygon overlap rule, and unmapped share.",
        "- The live coverage heatmap gives one serving-sector record per location; it does not provide all alternate-cell RSRP values needed to identify backup coverage holes or quantify degradation.",
        "- KPI averages are descriptive comparisons across candidate cell-hours; they do not establish causality.",
        "- See the JSON report for complete metric values, source paths, and provenance.", "",
    ])
    return "\n".join(lines)

def final_step_report(
    run_dir: Path,
    case_state_path: Path | None = None,
    notebook_calculation_state_path: Path | None = None,
) -> Path:
    """Write reports from run artifacts; the legacy calculation argument is ignored."""
    run_dir = run_dir.resolve()
    run_state_path = run_dir / "state.json"
    state_path = run_state_path
    if not state_path.is_file() and case_state_path is not None:
        state_path = case_state_path
    state = _load_json(state_path)
    steps_path = run_dir / "steps.json"
    steps = json.loads(steps_path.read_text(encoding="utf-8"))
    observations = [
        step for step in steps
        if step.get("result", {}).get("status") == "success"
    ]
    by_tool = {
        step["result"]["tool"]: step["result"]
        for step in observations
    }
    outage_start, outage_end = state["task"]["outage_time"].split(" through ")
    evidence: dict[str, Any] = {}
    landuse_path: Path | None = None
    landuse_observation = state.get("landuse", {})
    if landuse_path is None and landuse_observation.get("artifact"):
        landuse_path = Path(landuse_observation["artifact"])
        if not landuse_path.is_absolute():
            landuse_path = Path.cwd() / landuse_path
    coverage_result = by_tool.get("query_coverage_heatmap")
    if coverage_result:
        path = Path(coverage_result["output_file"])
        if not path.is_absolute():
            path = Path.cwd() / path
        evidence["coverage"] = _coverage_summary(
            path, landuse_path, outage_prefixes(state["task"]),
        )
    for tool_name, cell_column, key in (
        ("query_lte_rrc_prb", "EUTRANCELLFDD", "lte_kpi"),
        ("query_nr_rrc_prb", "NRCELL", "nr_kpi"),
    ):
        result = by_tool.get(tool_name)
        if result:
            path = Path(result["output_file"])
            if not path.is_absolute():
                path = Path.cwd() / path
            evidence[key] = _kpi_summary(path, cell_column, outage_start, outage_end)
    report = {
        "report_type": "final_outage_investigation_report",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case": {
            "down_cell_id": state["task"]["down_cell_id"],
            "outage_cell_ids": outage_prefixes(state["task"]),
            "outage_time": state["task"]["outage_time"],
            "objective": state["task"]["objective"],
            "technology": state["task"].get("technology", "4G per basic-information evidence"),
            "source_state": state_path.as_posix(),
        },
        "live_evidence": evidence,
        "osm_landuse_state": state.get("landuse", {"available": False}),
        "run_steps": steps,
    }
    json_path = run_dir / "final_report.json"
    md_path = run_dir / "final_report.md"
    json_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return md_path
