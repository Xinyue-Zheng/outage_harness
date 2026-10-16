"""Completion check and final report for the per-point coverage path.

Both read State and the geometry file only. The model writes none of it.

Completion (the boundary check), agreed 2026-10-16:

- An outage sector covers a location when some sample there lists it at or
  above COVERAGE_RSRP_DBM, serving or not. It is absent at a location when
  the location has samples and the sector is never listed at or above the
  threshold. A location with no sample is neither.
- Only activity locations matter: grid locations inside a settlement, a road
  corridor or an activity area. Nothing else is ever required.
- Direction comes from the data. The compass around the site is divided into
  bins of BIN_DEGREES. A bin is active for a sector when the sector covers
  some fetched location in it. Active bins plus MARGIN_BINS on each side are
  checked; the others are never asked for.
- Per sector and checked bin: the reach is the farthest covered activity
  location from the site. Every activity location in the bin nearer than the
  reach must be fetched. Beyond the reach, the nearest activity locations
  (the far part of the same corridor, or the next settlement, taken as the
  nearest activity area with locations beyond the reach in that bin) must be
  fetched and show the sector absent. A margin bin has reach 0: only the
  second part applies.
- A bin with no activity location beyond the reach inside the study area is
  open at the study-area edge. It is reported, and under ACCEPT_EDGE_OPEN a
  finish may pass with it, until study-area expansion exists as an action.
- Missing data never blocks. Backup load is reported, never required.

Report: see final_report. Every served location (covered at threshold) is
put in one class: total loss, degrade by signal, degrade by capacity, both,
served by backup, or degrade with unknown cause (backup without load
baseline). Capacity comes from state["impact"], the result of the transfer
tool, when it exists.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from point_coverage import COVERAGE_RSRP_DBM, read_geometry

ACTIVITY_KINDS = {"settlement", "road_corridor", "activity_area"}
BIN_DEGREES = 30.0
MARGIN_BINS = 1
ACCEPT_EDGE_OPEN = True
# Report parameters.
SIGNAL_MARGIN_DB = 10.0      # backup weaker than the outage sector by more than this: degrade by signal
SERVICE_RSRP_DBM = COVERAGE_RSRP_DBM   # a backup below this does not count as adequate
LOAD_LIMIT_PERCENT = 80.0    # estimated PRB above this: degrade by capacity
PRB_METRIC = "MEAN_PRB_USED"   # the KPI column apply_kpi keeps as the PRB utilisation metric, in percent
REQUIRED_CHECKS = ("boundary",)

COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")

IsOutage = Callable[[str], bool]
EligibleBackups = Callable[[Iterable[str]], list[str]]


# Location table -------------------------------------------------------------------


def _bearing_deg(dx: float, dy: float) -> float:
    """Compass bearing 0..360 of (east, north) offset: 0 north, 90 east."""
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def location_table(state: dict[str, Any], geometry: dict[str, Any], is_outage: IsOutage) -> dict[str, dict[str, Any]]:
    """Per grid location: position relative to the site, activity areas, fetch status,
    and per outage sector whether it covers or is absent there."""
    grid = geometry["grid"]
    columns, spacing = int(grid["columns"]), float(grid["spacing_m"])
    site_lat, site_lon = float(geometry["site"]["lat"]), float(geometry["site"]["lon"])
    lon_scale = 111_320.0 * math.cos(math.radians(site_lat))
    site_x = (site_lon - float(grid["origin_lon"])) * lon_scale
    site_y = (site_lat - float(grid["origin_lat"])) * 111_320.0
    kinds = {a: (m.get("kind") or "") for a, m in (state["geography"].get("areas") or {}).items()}
    table = state.get("coverage") or {}
    rows: dict[str, dict[str, Any]] = {}
    for area_id, area in geometry["areas"].items():
        for grid_id in area["grid_ids"]:
            g = str(grid_id)
            row = rows.get(g)
            if row is None:
                r, c = divmod(int(g), columns)
                dx, dy = (c + 0.5) * spacing - site_x, (r + 0.5) * spacing - site_y
                entry = table.get(g)
                covered: dict[str, bool] = {}
                absent: dict[str, bool] = {}
                if entry is not None and entry["status"] == "valid":
                    for cell, stats in entry["cells"].items():
                        if is_outage(cell):
                            covered[cell] = stats["rsrp_max_dbm"] >= COVERAGE_RSRP_DBM
                row = rows[g] = {
                    "grid_id": g, "row": r, "column": c, "dx": dx, "dy": dy,
                    "distance_m": math.hypot(dx, dy), "bearing": _bearing_deg(dx, dy),
                    "bin": int(_bearing_deg(dx, dy) // BIN_DEGREES),
                    "areas": [], "activity": False,
                    "status": "unqueried" if entry is None else entry["status"],
                    "covered": covered, "absent": absent,
                }
            row["areas"].append(area_id)
            if kinds.get(area_id) in ACTIVITY_KINDS:
                row["activity"] = True
    return rows


def _absent(row: dict[str, Any], cell: str) -> bool:
    return row["status"] == "valid" and not row["covered"].get(cell, False)


# Completion ----------------------------------------------------------------------


def completion_evidence_status(state: dict[str, Any], run_dir: str | Path, is_outage: IsOutage) -> dict[str, Any]:
    geometry = read_geometry(state, run_dir)
    rows = location_table(state, geometry, is_outage)
    bins_total = int(round(360.0 / BIN_DEGREES))
    outage_cells = sorted({c for row in rows.values() for c in row["covered"]})
    area_names = {a: (m.get("name") or a) for a, m in (state["geography"].get("areas") or {}).items()}
    per_sector: dict[str, dict[str, Any]] = {}
    unresolved: dict[str, Any] = {}
    if not outage_cells:
        unresolved["outage_cells"] = "No outage sector has been observed at or above the coverage threshold"
    for cell in outage_cells:
        active = {row["bin"] for row in rows.values() if row["covered"].get(cell)}
        checked = {(b + d) % bins_total for b in active for d in range(-MARGIN_BINS, MARGIN_BINS + 1)}
        sector_bins: dict[str, Any] = {}
        for b in sorted(checked):
            in_bin = [row for row in rows.values() if row["bin"] == b and row["activity"]]
            covered_here = [row for row in in_bin if row["covered"].get(cell)]
            reach = max((row["distance_m"] for row in covered_here), default=0.0)
            reach_areas = sorted({a for row in covered_here for a in row["areas"] if a in area_names and state["geography"]["areas"][a].get("kind") in ACTIVITY_KINDS})
            inside_unfetched = [row["grid_id"] for row in in_bin if row["distance_m"] <= reach and row["status"] == "unqueried"]
            beyond = [row for row in in_bin if row["distance_m"] > reach]
            label = f"{COMPASS[int((b * BIN_DEGREES + BIN_DEGREES / 2) // 45) % 8]} {int(b * BIN_DEGREES)}-{int((b + 1) * BIN_DEGREES)} deg"
            result: dict[str, Any] = {"bin": b, "label": label,
                                      "active": b in active, "reach_m": round(reach), "reach_areas": reach_areas,
                                      "unfetched_within_reach": len(inside_unfetched)}
            # The nearest activity area beyond the reach in this bin, by its nearest location. An area that
            # is fully fetched but has no sample in this direction gives no evidence either way and is
            # passed over for the next one (missing data never blocks and never closes).
            closing = None
            skipped: list[str] = []
            remaining = list(beyond)
            while remaining:
                nearest = min(remaining, key=lambda row: row["distance_m"])
                candidate = next(a for a in nearest["areas"] if state["geography"]["areas"][a].get("kind") in ACTIVITY_KINDS)
                closing_rows = [row for row in remaining if candidate in row["areas"]]
                remaining = [row for row in remaining if candidate not in row["areas"]]
                if all(row["status"] == "missing" for row in closing_rows):
                    skipped.append(candidate)
                    continue
                closing = candidate
                break
            if closing is None:
                result.update({"status": "open_at_edge", "closing_area": None, "no_sample_areas": skipped,
                               "reason": "no activity location with a sample beyond the reach inside the study area"})
            else:
                unfetched = [row["grid_id"] for row in closing_rows if row["status"] == "unqueried"]
                sampled = [row for row in closing_rows if row["status"] == "valid"]
                covered_beyond = [row["grid_id"] for row in sampled if row["covered"].get(cell)]
                result.update({"closing_area": closing, "closing_distance_m": round(nearest["distance_m"]),
                               "closing_unfetched": len(unfetched), "closing_sampled": len(sampled),
                               "closing_covered": len(covered_beyond)})
                if inside_unfetched:
                    result.update({"status": "open", "reason": f"{len(inside_unfetched)} activity locations within the reach not fetched"})
                elif unfetched:
                    result.update({"status": "open", "reason": f"{closing} has {len(unfetched)} locations in this direction not fetched"})
                elif covered_beyond:
                    # The sector covers the closing area: the reach is wrong only because that area is partly
                    # fetched; once fully fetched it joins the reach and the next area is asked for.
                    result.update({"status": "open", "reason": f"{cell} still covers {len(covered_beyond)} locations of {closing}; the reach extends"})
                else:
                    result.update({"status": "closed", "reason": f"{closing} shows {cell} absent at {len(sampled)} sampled locations"})
            sector_bins[str(b)] = result
        open_bins = {b: r for b, r in sector_bins.items() if r["status"] == "open"}
        edge_bins = {b: r for b, r in sector_bins.items() if r["status"] == "open_at_edge"}
        per_sector[cell] = {"checked_bins": len(sector_bins), "closed": len(sector_bins) - len(open_bins) - len(edge_bins),
                            "open": len(open_bins), "open_at_edge": len(edge_bins), "bins": sector_bins}
        if open_bins:
            unresolved[cell] = "; ".join(f"{r['label']}: {r['reason']}" for r in open_bins.values())
        elif edge_bins and not ACCEPT_EDGE_OPEN:
            unresolved[cell] = "; ".join(f"{r['label']}: open at the study-area edge, reach {r['reach_m']} m" for r in edge_bins.values())
    boundary = {
        "status": "complete" if not unresolved else "unknown",
        "reason": ("Every observed outage sector is closed in every checked direction"
                   if not unresolved else "An outage sector is not closed in some checked direction"),
        "coverage_rsrp_dbm": COVERAGE_RSRP_DBM, "bin_degrees": BIN_DEGREES, "margin_bins": MARGIN_BINS,
        "sectors": per_sector, "unresolved": unresolved,
    }
    return {"boundary": boundary,
            "backup_load": {"status": "complete" if state.get("impact") else "unknown", "required": False,
                            "reason": ("Transfer and load estimate present" if state.get("impact") else
                                       "No transfer and load estimate was computed; reported, not required")}}


def unmet_required(checks: dict[str, Any]) -> dict[str, Any]:
    return {name: check for name, check in checks.items()
            if name in REQUIRED_CHECKS and check.get("status") != "complete"}


def completion_context_lines(checks: dict[str, Any]) -> list[str]:
    """The per-sector, per-direction lines for the context: what is closed and what to query next."""
    boundary = checks.get("boundary") or {}
    lines = [f"Boundary check: {boundary.get('status', 'unknown')} ({boundary.get('reason', '')})."]
    for cell, sector in (boundary.get("sectors") or {}).items():
        parts = []
        for r in sector["bins"].values():
            reach = f"covers to {r['reach_m']} m ({', '.join(r['reach_areas'])})" if r["active"] else "not covered"
            if r["status"] == "closed":
                parts.append(f"{r['label']}: {reach}; closed by {r['closing_area']}")
            elif r["status"] == "open_at_edge":
                parts.append(f"{r['label']}: {reach}; open at the study-area edge")
            else:
                parts.append(f"{r['label']}: {reach}; open: {r['reason']}")
        lines.append(f"- {cell}: " + " | ".join(parts))
    return lines


# Report ---------------------------------------------------------------------------


def _components(ids: set[str], columns: int) -> list[list[str]]:
    seen: set[str] = set()
    groups: list[list[str]] = []
    for start in sorted(ids, key=int):
        if start in seen:
            continue
        stack, group = [start], []
        seen.add(start)
        while stack:
            g = stack.pop(); group.append(g)
            r, c = divmod(int(g), columns)
            for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
                if 0 <= c + dc < columns:
                    n = str((r + dr) * columns + c + dc)
                    if n in ids and n not in seen:
                        seen.add(n); stack.append(n)
        groups.append(sorted(group, key=int))
    return sorted(groups, key=len, reverse=True)


def _position(ids: Iterable[str], area_ids: Iterable[str], rows: dict[str, dict[str, Any]]) -> str:
    """Compass word of the centroid of ids relative to the centroid of the area."""
    pts = [rows[g] for g in ids]
    area = [rows[g] for g in area_ids]
    if not pts or not area:
        return "centre"
    cx = sum(p["dx"] for p in area) / len(area); cy = sum(p["dy"] for p in area) / len(area)
    px = sum(p["dx"] for p in pts) / len(pts); py = sum(p["dy"] for p in pts) / len(pts)
    radius = max(math.hypot(p["dx"] - cx, p["dy"] - cy) for p in area) or 1.0
    if math.hypot(px - cx, py - cy) < 0.25 * radius:
        return "centre"
    return COMPASS[int(((_bearing_deg(px - cx, py - cy) + 22.5) % 360) // 45)]


def _where(ids: set[str], area_id: str, geometry: dict[str, Any], rows: dict[str, dict[str, Any]], noun: str) -> str:
    columns = int(geometry["grid"]["columns"])
    area_ids = [str(g) for g in geometry["areas"][area_id]["grid_ids"]]
    groups = _components(ids, columns)
    if not groups:
        return ""
    if len(groups) == 1 or len(groups[0]) >= 0.7 * len(ids):
        return f"gathered in the {_position(groups[0], area_ids, rows)} part of the {noun}"
    if len(groups) <= 3:
        positions = []
        for g in groups:
            word = _position(g, area_ids, rows)
            if word not in positions:
                positions.append(word)
        return f"in {len(groups)} groups, in the " + " and ".join(positions) + f" part{'s' if len(positions) > 1 else ''} of the {noun}"
    return f"scattered across the {noun}"


def classify_locations(state: dict[str, Any], rows: dict[str, dict[str, Any]], is_outage: IsOutage,
                       eligible_backups: EligibleBackups) -> dict[str, dict[str, Any]]:
    """Per served location: its class and the facts behind it."""
    table = state.get("coverage") or {}
    impact = state.get("impact") or {}
    loads = {b["cell_id"]: b for b in impact.get("backup_loads", [])} if impact else {}
    baselines = ((state.get("kpi_baselines") or {}).get("cells") or {})
    out: dict[str, dict[str, Any]] = {}
    for g, row in rows.items():
        if not any(row["covered"].values()):
            continue
        entry = table[g]
        best_outage = max(r for s in entry["samples"] for c, r in s["cells"].items() if is_outage(c))
        living = set(eligible_backups(c for s in entry["samples"] for c in s["cells"]))
        # Living backup observed in the same sample as a covered outage sector.
        candidates: dict[str, float] = {}
        for s in entry["samples"]:
            if not any(is_outage(c) and r >= COVERAGE_RSRP_DBM for c, r in s["cells"].items()):
                continue
            for c, r in s["cells"].items():
                if c in living:
                    candidates[c] = max(candidates.get(c, -1e9), r)
        if not candidates:
            out[g] = {"class": "total_loss", "outage_rsrp_dbm": best_outage, "backup": None}
            continue
        backup, rsrp = max(candidates.items(), key=lambda kv: (kv[1], kv[0]))
        signal_bad = rsrp < SERVICE_RSRP_DBM or best_outage - rsrp > SIGNAL_MARGIN_DB
        if backup in loads:
            capacity_bad = float(loads[backup].get("estimated_prb_percent", 0.0)) > LOAD_LIMIT_PERCENT
            capacity_known = True
        else:
            capacity_known = bool(impact) and PRB_METRIC in (baselines.get(backup) or {})
            capacity_bad = False
        if signal_bad and capacity_bad:
            cls = "degrade_both"
        elif signal_bad:
            cls = "degrade_signal"
        elif capacity_bad:
            cls = "degrade_capacity"
        elif not capacity_known:
            cls = "degrade_unknown"
        else:
            cls = "served_by_backup"
        out[g] = {"class": cls, "outage_rsrp_dbm": best_outage, "backup": backup, "backup_rsrp_dbm": rsrp,
                  "capacity_known": capacity_known}
    return out


CLASS_ORDER = ("total_loss", "degrade_signal", "degrade_capacity", "degrade_both", "served_by_backup", "degrade_unknown")
CLASS_PHRASE = {
    "total_loss": "lose connection entirely",
    "degrade_signal": "may degrade by signal",
    "degrade_capacity": "may degrade by capacity",
    "degrade_both": "may degrade by signal and capacity",
    "served_by_backup": "keep service through a backup",
    "degrade_unknown": "have a backup whose load cannot be assessed",
}


def final_report(state: dict[str, Any], run_dir: str | Path, is_outage: IsOutage,
                 eligible_backups: EligibleBackups, checks: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The report text and its JSON twin. Reads State only."""
    geometry = read_geometry(state, run_dir)
    rows = location_table(state, geometry, is_outage)
    classes = classify_locations(state, rows, is_outage, eligible_backups)
    areas_meta = state["geography"].get("areas") or {}
    task = state.get("task") or {}
    boundary = checks.get("boundary") or {}
    outage_cells = sorted(boundary.get("sectors") or {})
    whole_site = all("_" in c and c.split("_")[0] == str(task.get("down_cell_id")) for c in outage_cells) and "-" not in str(task.get("down_cell_id"))
    study = (state.get("summaries") or {}).get("study_area") or {}
    lines = [
        "OUTAGE IMPACT REPORT",
        f"Case: {task.get('down_cell_id')}, planned outage {task.get('start_time')} to {task.get('end_time')}",
        f"Outage sectors observed: {', '.join(outage_cells) or 'none'}"
        + (" (whole site down: no sector of it is a backup)" if whole_site and outage_cells else ""),
        f"Completion: boundary check {boundary.get('status')}; "
        + "; ".join(f"{c}: {s['closed']} of {s['checked_bins']} directions closed, {s['open']} open, {s['open_at_edge']} open at the study-area edge"
                    for c, s in (boundary.get("sectors") or {}).items()),
        f"Evidence: {study.get('queried', 0)} locations fetched, {study.get('valid', 0)} with samples; "
        f"coverage threshold {COVERAGE_RSRP_DBM:g} dBm; signal margin {SIGNAL_MARGIN_DB:g} dB; load limit {LOAD_LIMIT_PERCENT:g}% PRB.",
        "",
        "1. Where service is lost or degraded (locations where an outage sector covers at or above the threshold)",
        "",
        f"   {'area':<32}{'covered':>8}" + "".join(f"{h:>10}" for h in ("loss", "signal", "capacity", "both", "backup", "unknown")),
    ]
    per_area: dict[str, dict[str, Any]] = {}
    totals = {c: 0 for c in CLASS_ORDER}
    for area_id, meta in areas_meta.items():
        if meta.get("kind") not in ACTIVITY_KINDS:
            continue
        ids = {str(g) for g in geometry["areas"][area_id]["grid_ids"]}
        served = {g for g in ids if g in classes}
        if not served:
            continue
        counts = {c: sorted((g for g in served if classes[g]["class"] == c), key=int) for c in CLASS_ORDER}
        valid = (state.get("summaries") or {}).get(area_id, {}).get("valid", 0)
        per_area[area_id] = {"name": meta.get("name") or area_id, "covered": len(served), "valid": valid,
                             "classes": {c: {"count": len(v), "share_of_covered": round(len(v) / len(served), 3),
                                             "share_of_valid": round(len(v) / valid, 3) if valid else None, "grid_ids": v}
                                         for c, v in counts.items()}}
        for c, v in counts.items():
            totals[c] += len(v)
        lines.append(f"   {area_id + ' (' + (meta.get('name') or '') + ')':<32}{len(served):>8}" + "".join(f"{len(counts[c]):>10}" for c in CLASS_ORDER))
    lines.append(f"   {'total':<32}{sum(v['covered'] for v in per_area.values()):>8}" + "".join(f"{totals[c]:>10}" for c in CLASS_ORDER))
    lines.append("")
    for area_id, a in per_area.items():
        noun = "corridor" if areas_meta[area_id].get("kind") == "road_corridor" else "area"
        sentences = []
        for c in CLASS_ORDER:
            v = a["classes"][c]
            if not v["count"]:
                continue
            where = _where(set(v["grid_ids"]), area_id, geometry, rows, noun)
            sentences.append(f"{v['share_of_covered']:.0%} of the covered locations {CLASS_PHRASE[c]} ({v['count']} of {a['covered']}), {where}.")
        lines.append(f"   {area_id} ({a['name']}): " + " ".join(sentences))
    lines += ["", "2. Why: per backup cell"]
    impact = state.get("impact") or {}
    loads = {b["cell_id"]: b for b in impact.get("backup_loads", [])} if impact else {}
    baselines = ((state.get("kpi_baselines") or {}).get("cells") or {})
    by_backup: dict[str, list[str]] = {}
    for g, c in classes.items():
        if c.get("backup"):
            by_backup.setdefault(c["backup"], []).append(g)
    total_served = len(classes)
    for backup, gs in sorted(by_backup.items()):
        weaker = sum(classes[g]["outage_rsrp_dbm"] - classes[g]["backup_rsrp_dbm"] > SIGNAL_MARGIN_DB for g in gs)
        below = sum(classes[g]["backup_rsrp_dbm"] < SERVICE_RSRP_DBM for g in gs)
        adequate = sum(not (classes[g]["backup_rsrp_dbm"] < SERVICE_RSRP_DBM
                            or classes[g]["outage_rsrp_dbm"] - classes[g]["backup_rsrp_dbm"] > SIGNAL_MARGIN_DB) for g in gs)
        text = (f"   {backup}: strongest living backup at {len(gs)} locations ({len(gs) / total_served:.0%} of covered locations). "
                f"Signal: adequate at {adequate}; weaker than the outage sector by more than {SIGNAL_MARGIN_DB:g} dB at {weaker}; "
                f"below {SERVICE_RSRP_DBM:g} dBm at {below}.")
        if backup in loads:
            b = loads[backup]
            text += (f" Load: baseline PRB {b.get('baseline_prb_percent'):g}%, estimated after transfer {b.get('estimated_prb_percent'):g}%; "
                     f"limit {LOAD_LIMIT_PERCENT:g}%: {'exceeded' if float(b.get('estimated_prb_percent', 0)) > LOAD_LIMIT_PERCENT else 'within limit'}.")
        elif PRB_METRIC in (baselines.get(backup) or {}):
            text += (f" Load: baseline PRB {baselines[backup][PRB_METRIC].get('mean'):g}% present; no transfer estimate "
                     "was computed, so capacity is not assessed.")
        else:
            text += (f" Load: whether service degrades cannot be assessed because the historical load data of {backup} is missing.")
        lines.append(text)
    for cell in sorted(set(state.get("cells_seen") or []) - set(by_backup) - set(outage_cells)):
        lines.append(f"   {cell}: observed but not an eligible backup, or never the strongest living backup at a covered location.")
    lines += ["", "3. Total loss, by location"]
    for area_id, a in per_area.items():
        gs = a["classes"]["total_loss"]["grid_ids"]
        if gs:
            lines.append(f"   {area_id}: grid " + ", ".join(gs))
    if not totals["total_loss"]:
        lines.append("   none")
    lines += ["", "4. What this report does not establish"]
    for area_id, meta in areas_meta.items():
        m = (state.get("summaries") or {}).get(area_id, {}).get("missing", 0)
        if meta.get("kind") in ACTIVITY_KINDS and m:
            lines.append(f"   - {area_id}: {m} locations with missing data; coverage there is unknown.")
    for cell, s in (boundary.get("sectors") or {}).items():
        for r in s["bins"].values():
            if r["status"] == "open_at_edge":
                lines.append(f"   - {cell}, {r['label']}: covered to {r['reach_m']} m; no activity location beyond inside the study area; "
                             "expand the study area to close this direction.")
    lines.append("   - Counts are analysis grid locations, not users or traffic; land use is not demand.")
    unrequired = [a for a, m in areas_meta.items() if m.get("kind") in ACTIVITY_KINDS and a not in per_area
                  and (state.get("summaries") or {}).get(a, {}).get("queried", 0) == 0]
    if unrequired:
        lines.append(f"   - Activity areas not queried and not required by the closure: {', '.join(unrequired)}.")
    text = "\n".join(lines) + "\n"
    return text, {"areas": per_area, "totals": totals, "locations": classes, "completion": checks,
                  "parameters": {"coverage_rsrp_dbm": COVERAGE_RSRP_DBM, "signal_margin_db": SIGNAL_MARGIN_DB,
                                 "service_rsrp_dbm": SERVICE_RSRP_DBM, "load_limit_percent": LOAD_LIMIT_PERCENT}}


# finish node ------------------------------------------------------------------------


def finish_check(state: dict[str, Any], is_outage: IsOutage, eligible_backups: EligibleBackups, *,
                 write_json: Any, model_name: str) -> dict[str, Any]:
    """finish_check_node for langgraph_runner.py: checks first, then the program writes the report."""
    run_dir = Path(state["output_dir"])
    checks = completion_evidence_status(state["state"], run_dir, is_outage)
    unmet = unmet_required(checks)
    index = state["step_index"]
    if unmet:
        return {"state": {**state["state"], "completion_checks": checks},
                "error": "Completion refused: " + json.dumps({k: v.get("unresolved", v.get("reason")) for k, v in unmet.items()})}
    from report import build_report  # the same report the tool writes

    markdown, data = build_report({**state["state"], "completion_checks": checks}, run_dir)
    (run_dir / "final_report.md").write_text(markdown, encoding="utf-8")
    write_json(run_dir / "final_report.json", data)
    final_state = {**state["state"], "completion_checks": checks, "final_report": "final_report.md"}
    finish_step = {"step": index, "decision": state["decision"], "status": "finished",
                   "completion_checks": checks, "final_report": "final_report.md"}
    steps = [*state["steps"], finish_step]
    step_dir = run_dir / "steps" / f"step_{index:02d}"
    write_json(run_dir / "steps.json", steps)
    write_json(run_dir / "state.json", final_state)
    write_json(step_dir / "finish.json", {"status": "finished", "completion_checks": checks})
    write_json(step_dir / "state_after.json", final_state)
    write_json(run_dir / f"state_{index:02d}.json", final_state)
    write_json(step_dir / "step.json", finish_step)
    write_json(run_dir / "run.json", {
        "case_state": state["case_state_path"], "model": model_name, "steps": len(steps),
        "finished": True, "end_reason": "complete", "observations": len(state["observations"]),
        "tool_declaration_count": len(state["tools"]), "final_report": "final_report.md",
        "orchestrator": "langgraph",
    })
    return {"state": final_state, "steps": steps, "finished": True, "error": None}
