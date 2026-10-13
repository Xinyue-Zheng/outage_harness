"""Context builder for the per-point coverage State.

Same contract as context_builder.py: build_context(state, tools, feedback) ->
Rendered(prefix, variable). The prefix (skill, task, KPI windows, geography,
areas, actions, completion checks) is fixed for the run; the variable part is
rendered from State every round.

Changes against the heatmap builder:
- The coverage section explains the point-query semantics once: every
  queried location was fetched by one point call; each sample lists its
  serving sector and the strongest neighbours; cells in one sample are
  observed together; a cell that is not listed is not shown to be absent.
- Each queried area reports how many valid locations list an outage cell,
  how many of those also list an eligible backup cell (in any sample, and in
  the same sample), and how many list none.
- Per-cell lines report present, strongest, serving and with-down-cell
  counts over grid locations, from the summaries.
- query_area_coverage takes only area_id; the cost note counts locations.

The two helpers the photographed builder lost (_parse_time, _is_outage) are
defined here.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Any

from outage_harness_langgraph.radio import eligible_backup_cells, is_outage_cell, outage_prefixes


@dataclass(frozen=True)
class Rendered:
    prefix: str
    variable: str

    @property
    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.prefix},
            {"role": "user", "content": self.variable},
        ]

    @property
    def text(self) -> str:
        return self.prefix + "\n\n" + self.variable


def load_skill() -> str:
    return files("outage_harness_langgraph").joinpath("investigation_skill.txt").read_text(
        encoding="utf-8"
    )


_SPATIAL_KEYS = frozenset({
    "geometry", "coordinates", "lat", "lon", "lng", "latitude", "longitude",
    "x", "y", "x_m", "y_m", "site_x_m", "site_y_m", "center", "center_wgs84",
    "bbox", "bbox_wgs84", "bounds", "south", "north", "east", "west",
    "min_lat", "max_lat", "min_lng", "max_lng", "grid_ids", "area_grid_ids",
    "rings", "vertices", "points", "origin_lat", "origin_lon",
})
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_UNKNOWN = "unknown"
_DETAILED_OTHERS = 5


def _metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _metadata(item) for key, item in value.items()
                if str(key).lower() not in _SPATIAL_KEYS}
    if isinstance(value, (list, tuple)):
        return [_metadata(item) for item in value]
    return value


def _compact(value: Any) -> str:
    return json.dumps(_metadata(value), sort_keys=True, ensure_ascii=True, default=str)


def _num(value: Any) -> str:
    if value is None:
        return _UNKNOWN
    if isinstance(value, float) and not isinstance(value, bool):
        return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _mapping(value: Any, id_key: str = "id") -> dict[str, dict[str, Any]]:
    if isinstance(value, Mapping):
        return {str(key): dict(item) if isinstance(item, Mapping) else {"value": item}
                for key, item in value.items()}
    result: dict[str, dict[str, Any]] = {}
    for item in value or []:
        if isinstance(item, Mapping):
            identifier = item.get(id_key, item.get("id", item.get("area_id")))
            if identifier is not None:
                result[str(identifier)] = dict(item)
    return result


def _down_id(task: Mapping[str, Any]) -> str:
    return ",".join(outage_prefixes(task))


def _is_outage(cell: str, down: str) -> bool:
    """Outage membership by prefix, as radio.is_outage_cell decides it."""
    return is_outage_cell(cell, {"outage_cell_ids": [p for p in down.split(",") if p]})


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _geography(state: Mapping[str, Any]) -> tuple[dict, dict, list, dict]:
    geography = state.get("geography", {})
    if isinstance(geography, Mapping):
        return (_mapping(geography.get("objects", {})),
                _mapping(geography.get("areas") or state.get("areas", [])),
                list(geography.get("relations", state.get("relations", [])) or []),
                dict(geography.get("source", {}) or {}))
    return _mapping(geography), _mapping(state.get("areas", [])), list(state.get("relations", []) or []), {}


def _initialized_functions(state: Mapping[str, Any]) -> set[str]:
    _, _, _, source = _geography(state)
    functions = {name for name, value in source.items() if isinstance(value, str)}
    for item in state.get("observations") or []:
        if isinstance(item, Mapping) and isinstance(item.get("action"), Mapping):
            if str(item.get("id", "")).startswith("init_"):
                functions.add(str(item["action"].get("function")))
    return functions


# Prefix.


def _task_lines(state: Mapping[str, Any]) -> list[str]:
    task = state.get("task", {}) or {}
    prefixes = outage_prefixes(task)
    down = prefixes[0] if prefixes else ""
    lines = ["Task:"]
    if len(prefixes) > 1:
        lines.append(
            "Explicit outage prefixes: " + ", ".join(prefixes) + ". Treat each prefix as a separate outage technology; "
            "do not infer that LTE and NR prefixes belong to the same site."
        )
    elif down and "-" in down:
        lines.append(f"Investigate the impact of the planned outage of cell {down}.")
    elif down:
        lines.append(
            f"Investigate the impact of the planned outage of EnodeB {down}. The ID has no dash, "
            f"so the whole EnodeB is down: every sector whose ID starts with {down} is an outage "
            "cell, and none of them can be a backup."
        )
    start, end = task.get("start_time"), task.get("end_time")
    if start or end:
        lines.append(f"Planned outage interval: {start} through {end} (UTC).")
        begin, finish = _parse_time(start), _parse_time(end)
        if begin and finish and begin.date() == finish.date():
            lines.append(f"The interval covers {_WEEKDAYS[begin.weekday()]} {begin:%H:%M} to {finish:%H:%M}.")
        elif begin:
            lines.append(f"The interval starts on a {_WEEKDAYS[begin.weekday()]}.")
        lines.append("The interval is a plan; it is not evidence that the outage happened.")
        lines.append(
            "Coverage evidence describes the network before the outage. KPI queries must end strictly "
            f"before {start}; a baseline compares the same weekday and hours in prior weeks."
        )
    if task.get("objective"):
        lines.append(f"Analysis objective: {task['objective']}")
    site = _metadata((state.get("site") or {}).get("metadata") or {})
    details, seen_values = [], set()
    for key, value in site.items():
        if value in (None, "") or str(value) == down or str(value).lower() in seen_values:
            continue
        seen_values.add(str(value).lower())
        details.append(f"{str(key).lower().replace('_', ' ')} {value}")
    if down and details:
        lines.append(f"Site of {down}: {', '.join(details)}.")
    study = state.get("study_area") or {}
    if study.get("side_m"):
        text = f"Study area: square of side {_num(study['side_m'])} m centred on the site"
        lines.append(text + (f" ({study['rule']})." if study.get("rule") else "."))
    _, areas, _, _ = _geography(state)
    containing = [area_id for area_id, area in areas.items() if area.get("contains_site")]
    if containing:
        lines.append(f"The down site lies inside areas: {', '.join(containing)}.")
    return lines


def _kpi_window_lines(state: Mapping[str, Any]) -> list[str]:
    windows = state.get("kpi_windows") or []
    if not windows:
        return []
    lines = [f"KPI windows (the planned outage interval moved back 1 to {len(windows)} whole weeks: the same "
             "weekday and hours; take KPI start_time and end_time from these):"]
    for window in windows:
        begin, finish = _parse_time(window["start_time"]), _parse_time(window["end_time"])
        days = (f"{_WEEKDAYS[begin.weekday()]}" if begin.date() == finish.date()
                else f"{_WEEKDAYS[begin.weekday()]} to {_WEEKDAYS[finish.weekday()]}") if begin and finish else ""
        weeks = window.get("weeks_before")
        lines.append(f"- {window['id']}: {window['start_time']} to {window['end_time']} "
                     f"({days}, {weeks} week{'s' if weeks != 1 else ''} before)")
    return lines


def _object_line(identifier: str, item: Mapping[str, Any], areas: Mapping[str, Any]) -> str:
    tags = item.get("tags") or {}
    name = item.get("name") or tags.get("name")
    kind = str(item.get("kind", "object")).replace("_", " ")
    text = f"- {identifier} is a {kind}" + (f" named {name}" if name else "")
    detail = tags.get("place") or tags.get("highway")
    text += (f" ({detail})." if detail else ".")
    if item.get("description"):
        text += f" {item['description']}"
    if tags.get("population"):
        text += f" OSM population tag {tags['population']} (a map tag, not measured demand)."
    if item.get("kind") == "road" or item.get("geometry_kind") == "polyline":
        text += " It is a centerline, not an area"
        text += f"; its query corridor is area {identifier}." if identifier in areas else "."
    elif name:
        matches = [area_id for area_id, area in areas.items()
                   if str(area.get("description", "")).startswith(f"{name} (")]
        if matches:
            text += f" Its settlement area is {matches[0]}."
    return text


def _relation_line(relation: Any) -> str:
    if not isinstance(relation, Mapping):
        return f"- {relation}"
    subject = relation.get("subject_id", relation.get("subject"))
    target = relation.get("object_id", relation.get("object"))
    text = f"- {subject} {relation.get('predicate', 'relates to')} {target}."
    if relation.get("evidence"):
        text += f" Spatial evidence: {relation['evidence']}."
    return text


def _geography_lines(state: Mapping[str, Any]) -> list[str]:
    objects, areas, relations, source = _geography(state)
    grid = state.get("grid") or {}
    lines = ["Known geography:"]
    parts = [str(state["coordinate_system"])] if state.get("coordinate_system") else []
    if grid.get("spacing_m"):
        parts.append(f"analysis grid of {grid.get('rows')} x {grid.get('columns')} locations "
                     f"with {_num(grid['spacing_m'])} m spacing")
    if parts:
        lines.append("Coordinate system: " + "; ".join(parts) + ". Coordinates are not shown; refer to areas by id.")
    sources = [f"{name} observation {value}" for name, value in sorted(source.items()) if isinstance(value, str)]
    if sources:
        lines.append("Source: " + ", ".join(sources) + ".")
    summarized: Counter[str] = Counter()
    listed = []
    for identifier, item in objects.items():
        if item.get("kind") in {"landuse", "water"}:
            tags = item.get("tags") or {}
            tag = next((f"{key}={tags[key]}" for key in ("landuse", "natural") if key in tags),
                       item.get("label", item["kind"]))
            summarized[f"{tag} {item.get('geometry_kind', 'polygon')}s"] += 1
        else:
            listed.append(_object_line(identifier, item, areas))
    lines += listed
    lines += [_relation_line(relation) for relation in relations]
    if summarized:
        lines.append(
            f"Mapped land-use and water objects: {sum(summarized.values())} ("
            + ", ".join(f"{count} {label}" for label, count in summarized.most_common())
            + "). They are summarized in the area descriptions, not listed individually."
        )
    activity = (state.get("geography_summary") or {}).get("activity_feature_counts") or {}
    if activity:
        lines.append("Mapped human-activity features, grouped into activity areas A##: " + ", ".join(
            f"{tag} {count}" for tag, count in activity.items()) + ".")
    by_label = (state.get("geography_summary") or {}).get("grid_cells_by_label") or {}
    if by_label:
        lines.append("Analysis grid locations by mapped land use: " + ", ".join(
            f"{label} {count}" for label, count in sorted(by_label.items(), key=lambda kv: (-kv[1], kv[0]))) + ".")
    lines.append("Land-use labels are mapped types, not measured demand: settlements and commercial or "
                 "industrial land usually hold most users; farmland, grassland, forest and water usually "
                 "hold few or none.")
    return lines


def _area_lines(state: Mapping[str, Any]) -> list[str]:
    _, areas, _, _ = _geography(state)
    lines = ["Areas (overlapping areas share analysis grid locations; their counts are not additive):"]
    for identifier, area in areas.items():
        description = str(area.get("description", "")).strip()
        count = area.get("locations", area.get("grid_count"))
        text = f"- {identifier}" + (f" ({area['kind']})" if area.get("kind") else "") + ":"
        text += f" {description}" if description else ""
        if count is not None:
            text += f" Resolves to {count} analysis grid locations."
        if area.get("contains_site"):
            text += " Contains the down site."
        elif area.get("nearest_distance_from_site_m") is not None:
            text += (f" Nearest point {area['nearest_distance_from_site_m'] / 1000:.1f} km from the down site; "
                     f"centre {area['center_distance_from_site_m'] / 1000:.1f} km to the "
                     f"{area.get('center_direction_from_site', 'unknown direction')}.")
        labels = area.get("label_counts") or {}
        if len(labels) > 1 and "land use" not in description.lower():
            text += " Land use: " + ", ".join(
                f"{label} {value}" for label, value in sorted(labels.items(), key=lambda kv: (-kv[1], kv[0]))
            ) + "."
        lines.append(text)
    if not areas:
        lines.append("- None known.")
    return lines


def _declarations(tools: Iterable[Any]) -> list[dict[str, Any]]:
    declarations = [
        {key: tool[key] if isinstance(tool, Mapping) else getattr(tool, key)
         for key in ("name", "description", "input_schema")}
        for tool in tools
    ]
    return sorted(declarations, key=lambda tool: tool["name"])


def _parameters(schema: Mapping[str, Any]) -> str:
    required = set(schema.get("required", []))
    parts = []
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type", "value")
        if kind == "array":
            kind = f"list of {spec.get('items', {}).get('type', 'value')}"
        if spec.get("enum"):
            kind = "one of " + ", ".join(map(str, spec["enum"]))
        parts.append(f"{name}: {kind}" + ("" if name in required else ", optional"))
    return "; ".join(parts)


def _action_note(name: str, state: Mapping[str, Any]) -> str:
    task = state.get("task", {}) or {}
    start, down = task.get("start_time"), _down_id(task)
    initialized = _initialized_functions(state)
    kpi = ("Hourly rows. end_time must be strictly before {start}. Take start_time and end_time from "
           "the KPI windows; explain in purpose why if you use any other window. Longer windows and "
           "more cells increase cost. Cells are routed by ID: "
           "four letters + six digits (CCSN003553...) to query_nr_rrc_prb, three letters + five digits "
           "(CCL06069...) to query_lte_rrc_prb; a mixed list is split into both queries.")
    notes = {
        "query_area_coverage": "One point call per analysis grid location of the area that is not "
                               "queried yet; the cost is that number of locations, counted against "
                               "the query budget.",
        "query_lte_rrc_prb": "For LTE cells. " + kpi.format(start=start),
        "query_nr_rrc_prb": "For NR cells. " + kpi.format(start=start),
        "query_basic_information": f"Already run for {down} during initialization."
        if "query_basic_information" in initialized else "",
        "query_osm_landuse": "Already run for the study area during initialization."
        if "query_osm_landuse" in initialized else "",
        "final_step_report": "Use run_dir and case_state_path exactly as listed under Final report inputs.",
        "inspect_observation": "No API query and no API cost. Use an observation id from Evidence "
                               "provenance and an area id from Areas; offset >= 0, limit 1 to 100.",
    }
    return notes.get(name, "")


def _action_lines(state: Mapping[str, Any], tools: Iterable[Any]) -> list[str]:
    lines = ["Available actions:"]
    for tool in _declarations(tools):
        text = f"- {tool['name']}({_parameters(tool['input_schema'] or {})}). {str(tool['description']).strip()}"
        note = _action_note(tool["name"], state)
        lines.append(text + (f" {note}" if note else ""))
    lines.append("- finish(). Propose to end the investigation. The run ends only when the completion "
                 "checks pass; otherwise the unmet checks come back as feedback.")
    return lines


def _completion_lines() -> list[str]:
    return [
        "Completion checks, applied when you choose finish:",
        "- report: final_step_report has produced the final report.",
        "- boundary: for every observed outage sector, a fully queried settlement or road corridor "
        "farther from the down site than its last observed service shows the sector absent.",
        "- backup_load: verified evidence of backup-cell load after the outage traffic moves.",
        "Backup-load evidence is not currently computed, so that check remains unknown. Only LTE cells "
        "are backups for LTE outage sectors; only NR cells are backups for NR outage sectors. If both "
        "technologies are explicitly listed as outage prefixes, assess each technology separately.",
    ]


# Variable part.


def _summaries(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    summaries = state.get("summaries")
    return _mapping(summaries if summaries is not None else state.get("regions", []), "area_id")


def _total(summary: Mapping[str, Any], area: Mapping[str, Any]) -> Any:
    if summary.get("total") is not None:
        return summary["total"]
    if isinstance(summary.get("queried"), int) and isinstance(summary.get("unqueried"), int):
        return summary["queried"] + summary["unqueried"]
    return area.get("locations", area.get("grid_count"))


def _progress_lines(state: Mapping[str, Any], summaries: dict, areas: dict, down: str) -> list[str]:
    lines = ["Investigation progress:", "Counts are per area; overlapping areas must not be added together."]
    untouched, all_missing = [], []
    for identifier in [*areas, *(key for key in summaries if key not in areas)]:
        summary, area = summaries.get(identifier, {}), areas.get(identifier, {})
        total = _total(summary, area)
        if not summary.get("queried"):
            untouched.append(f"{identifier} ({_num(total)})")
            continue
        if summary.get("valid") == 0 and summary.get("missing") == summary["queried"]:
            all_missing.append(f"{identifier} ({_num(summary['queried'])} of {_num(total)})")
            continue
        lines.append(f"- {identifier} contains {_num(total)} analysis grid locations; "
                     f"{_num(summary.get('queried'))} queried, {_num(summary.get('unqueried'))} not queried.")
        lines.append(f"  {_num(summary.get('valid'))} queried locations have valid data; "
                     f"{_num(summary.get('missing'))} have missing data.")
        lines.append(f"  Valid locations: {_num(summary.get('no_coverage'))} list no cell; "
                     f"{_num(summary.get('down_cell_present'))} list an outage sector; "
                     f"{_num(summary.get('other_cells_only'))} list other cells only.")
        if summary.get("boundary") is not None:
            lines.append(f"  Query boundary facing the unqueried interior: {_num(summary['boundary'])} locations "
                         f"({_num(summary.get('boundary_missing'))} missing, "
                         f"{_num(summary.get('boundary_with_down_cell'))} with an outage sector).")
    if all_missing:
        lines.append("- Queried, but every queried location has missing data, so coverage is unknown "
                     "(queried of total locations): " + ", ".join(all_missing) + ".")
    if untouched:
        lines.append("- Not queried yet, coverage unknown (analysis grid locations): " + ", ".join(untouched) + ".")
    return lines


def _cell_line(cell: str, stats: Mapping[str, Any], outage: bool, eligible: set[str] | None = None) -> str:
    label = " (outage sector)" if outage else (
        "" if eligible is None or cell in eligible else " (not an eligible backup: other technology)")
    text = f"{cell}{label}: present at {_num(stats.get('present'))} valid locations"
    if stats.get("serving") is not None:
        text += f", serving at {_num(stats['serving'])}"
    if stats.get("strongest") is not None:
        text += f", strongest at {_num(stats['strongest'])}"
    if not outage and stats.get("with_down_cell") is not None:
        text += f", in the same sample as an outage sector at {_num(stats['with_down_cell'])}"
    if stats.get("rsrp_min_dbm") is not None:
        text += (f"; RSRP {_num(stats['rsrp_min_dbm'])} to {_num(stats.get('rsrp_max_dbm'))} dBm, "
                 f"mean {_num(stats.get('rsrp_mean_dbm'))}")
    if stats.get("sample_count"):
        text += f" over {_num(stats['sample_count'])} samples"
    return text + "."


def _coverage_lines(summaries: dict, down: str) -> list[str]:
    lines = [
        "Coverage observations:",
        "Each queried location was fetched by one point call. Every returned sample lists its serving "
        "sector and the strongest neighbour cells with RSRP, so cells listed in one sample are observed "
        "together at one measurement. A cell that is not listed at a location is not shown to be absent "
        "there. A location with no sample has missing data.",
    ]
    queried = False
    all_missing = []
    for identifier, summary in summaries.items():
        if not summary.get("queried"):
            continue
        queried = True
        cells = _mapping(summary.get("cells"))
        if not summary.get("valid") and not cells:
            all_missing.append(identifier)
            continue
        outage = sorted(cell for cell in cells if _is_outage(cell, down))
        others = sorted((cell for cell in cells if cell not in outage),
                        key=lambda cell: (-(cells[cell].get("present") or 0), cell))
        present = summary.get("down_cell_present")
        if outage:
            noun = "outage sector" if len(outage) == 1 else "outage sectors"
            verb = "is" if len(outage) == 1 else "are"
            lines.append(f"- {identifier}: {noun} {', '.join(outage)} {verb} listed at {_num(present)} of the "
                         f"{_num(summary.get('valid'))} valid locations.")
            lines.append(f"  Of those {_num(present)} locations, {_num(summary.get('down_cell_with_backup'))} also list "
                         f"an eligible backup cell ({_num(summary.get('down_cell_with_backup_same_sample'))} in the "
                         f"same sample as the outage sector) and {_num(summary.get('down_cell_without_backup'))} "
                         "list no eligible backup.")
        else:
            lines.append(f"- {identifier}: no outage sector is listed at the {_num(summary.get('valid'))} valid locations.")
        eligible = set(summary.get("backup_candidates") or [])
        lines += ["  " + _cell_line(cell, cells[cell], cell in outage, eligible or None)
                  for cell in [*outage, *others[:_DETAILED_OTHERS]]]
        if others[_DETAILED_OTHERS:]:
            lines.append("  Also present (valid locations): " + ", ".join(
                f"{cell} ({_num(cells[cell].get('present'))})" for cell in others[_DETAILED_OTHERS:]) + ".")
        if summary.get("unqueried"):
            lines.append(f"  {_num(summary['unqueried'])} locations of {identifier} are not queried; coverage there remains unknown.")
        if summary.get("missing"):
            lines.append("  Coverage at locations with missing data also remains unknown.")
    if all_missing:
        lines.append("- No valid record (every queried location missing; coverage unknown): "
                     + ", ".join(all_missing) + ".")
    if not queried:
        lines.append("- No coverage has been queried yet.")
    return lines


def _inspection_lines(state: Mapping[str, Any]) -> list[str]:
    inspection = state.get("inspection")
    if not inspection:
        return []
    if not isinstance(inspection, Mapping):
        return ["Inspection:", f"- {_compact(inspection)}"]
    rows = inspection.get("rows") or []
    offset = inspection.get("offset", 0)
    head = (f"Inspection (step {_num(inspection.get('step_index'))}) of observation "
            f"{inspection.get('observation_id')}, area {inspection.get('area_id')}")
    if not rows:
        return [head + ": no rows returned." if "rows" in inspection else head + "."]
    lines = [head + f", rows {offset} to {offset + len(rows) - 1}, in grid order:"]
    runs: list[tuple[str, list[Any]]] = []
    for row in rows:
        cells = _mapping(row.get("cells"))
        status = row.get("status", _UNKNOWN)
        if cells:
            detail = ", ".join(
                f"{cell} {_num(stats.get('rsrp_max_dbm'))} dBm"
                + (" serving" if stats.get("serving_count") else "")
                for cell, stats in sorted(cells.items(), key=lambda kv: -(kv[1].get("rsrp_max_dbm") or -999)))
            count = row.get("sample_count")
            detail += f" ({_num(count)} sample{'' if count == 1 else 's'})"
        else:
            detail = "no cell listed" if status == "valid" else "missing data"
        detail = f"{status}, {detail}"
        if runs and runs[-1][0] == detail:
            runs[-1][1].append(row.get("grid_id"))
        else:
            runs.append((detail, [row.get("grid_id")]))
    for detail, grids in runs:
        if len(grids) < 3:
            lines += [f"- grid {grid}: {detail}" for grid in grids]
        else:
            lines.append(f"- {len(grids)} consecutive rows, grids {grids[0]} to {grids[-1]}: {detail}")
    return lines


def _weekday_hour(slot: str) -> str:
    parts = slot.split("_")
    if len(parts) == 4 and parts[1].isdigit() and int(parts[1]) < 7:
        return f"{_WEEKDAYS[int(parts[1])][:3]} {parts[3]}:00"
    return slot


def _impact_lines(state: Mapping[str, Any], summaries: dict, down: str) -> list[str]:
    seen = set(state.get("cells_seen") or [])
    for summary in summaries.values():
        seen |= set(_mapping(summary.get("cells")))
    outage = sorted({cell for cell in seen if _is_outage(cell, down)} | set(state.get("outage_cells") or []))
    candidates = eligible_backup_cells(
        set(state.get("backup_candidates") or []) | seen,
        state.get("task", {"down_cell_id": down}),
    )
    lines = [
        "Impact and backup analysis:",
        "Outage sectors seen in valid coverage records (unavailable as backups): "
        + (", ".join(outage) or "none yet") + ".",
        "Backup candidates seen in valid coverage records (presence only; available load not verified): "
        + (", ".join(candidates) or "none yet") + ".",
    ]
    kpis = [item for item in state.get("kpis") or [] if isinstance(item, Mapping)]
    if kpis:
        cells = sorted({str(item.get("cell_id")) for item in kpis})
        times = sorted(str(item["timestamp"]) for item in kpis if item.get("timestamp"))
        metrics = sorted({metric for item in kpis for metric in (item.get("values") or {})})
        text = f"KPI records: {len(kpis)} rows for {len(cells)} cells ({', '.join(cells)})"
        text += f", {times[0]} to {times[-1]}" if times else ""
        text += f"; metrics {', '.join(metrics)}." if metrics else "."
        lines.append(text)
    else:
        lines.append("KPI records: none yet.")
    baseline = state.get("kpi_baseline", state.get("KPI_baseline"))
    covered = set()
    if isinstance(baseline, Mapping) and isinstance(baseline.get("cells"), Mapping) and baseline["cells"]:
        lines.append(f"KPI baseline ({baseline.get('selection', 'selection unknown')}; reference "
                     f"{baseline.get('reference_time', _UNKNOWN)}):")
        for cell, metrics in sorted(baseline["cells"].items()):
            covered.add(cell)
            for metric, stats in sorted((metrics or {}).items()):
                text = (f"- {cell} {metric}: mean {_num(stats.get('mean'))} over "
                        f"{_num(stats.get('prior_week_count'))} prior weeks ({_num(stats.get('sample_count'))} "
                        f"samples); range {_num(stats.get('min'))} to {_num(stats.get('max'))}")
                hours = stats.get("by_weekday_hour") or {}
                if hours:
                    text += "; by hour: " + ", ".join(
                        f"{_weekday_hour(slot)} {_num(value.get('mean'))}" for slot, value in sorted(hours.items()))
                lines.append(text + ".")
    elif baseline:
        lines.append(f"KPI baseline: {_compact(baseline)}")
    else:
        lines.append("KPI baseline: none yet.")
    if kpis or covered:
        missing = [cell for cell in candidates if cell not in covered]
        if missing:
            lines.append("No same-weekday/hour baseline yet for backup candidates: " + ", ".join(missing) + ".")
    impact = state.get("impact")
    lines.append("Impact estimate: not computed." if impact is None
                 else f"Impact estimate recorded (not inferred by the program): {_compact(impact)}")
    return lines


def _unknown_lines(state: Mapping[str, Any]) -> list[str]:
    lines = ["Remaining unknowns:"]
    unknowns = state.get("unknowns") or {}
    coverage = unknowns.get("coverage") if isinstance(unknowns, Mapping) else None
    if isinstance(coverage, Mapping):
        lines.append(f"- Coverage at {_num(coverage.get('locations_unqueried'))} unqueried analysis grid locations "
                     f"is unknown; {_num(coverage.get('areas_unqueried'))} areas have no queried location.")
        lines.append(f"- Coverage at {_num(coverage.get('locations_missing'))} queried locations with missing data is unknown.")
        for key in ("not_listed", "cooccurrence"):
            if coverage.get(key):
                lines.append(f"- {coverage[key]}")
    if isinstance(unknowns, Mapping):
        for key, value in unknowns.items():
            if key != "coverage":
                label = str(key).replace("_", " ")
                lines.append(f"- {label}: {value if isinstance(value, str) else _compact(value)}")
    lines += [
        "- Coverage beyond the study area is unknown.",
        "- Land-use labels do not establish population or complete network demand.",
        "- Unqueried and missing coverage are distinct; neither is evidence of absence.",
    ]
    return lines


def _completion_state_lines(state: Mapping[str, Any]) -> list[str]:
    checks = state.get("completion_checks")
    if not checks:
        lines = ["Completion checks: not yet evaluated; status unknown."]
    else:
        lines = ["Completion checks from the last finish attempt:"]
        for name, check in checks.items() if isinstance(checks, Mapping) else enumerate(checks):
            if isinstance(check, Mapping):
                lines.append(f"- {name}: {check.get('status', _UNKNOWN)}"
                             + (f" ({check['reason']})" if check.get("reason") else ""))
            else:
                lines.append(f"- {name}: {check}")
    inputs = state.get("final_report_inputs") or {}
    if inputs:
        lines.append("Final report inputs (use exactly for final_step_report): "
                     + "; ".join(f"{key} {value}" for key, value in inputs.items()) + ".")
    if state.get("final_report"):
        lines.append(f"Final report produced: {state['final_report']}.")
    return lines


def _budget_lines(state: Mapping[str, Any]) -> list[str]:
    budget = state.get("query_budget")
    if not isinstance(budget, Mapping):
        return []
    spent, limit = budget.get("locations_spent"), budget.get("locations_limit")
    if limit is None:
        return [f"Query budget: {_num(spent)} locations fetched; no limit."]
    remaining = int(limit) - int(spent or 0)
    return [f"Query budget: {_num(spent)} of {_num(limit)} locations used; {remaining} remain. "
            "A coverage query costs the locations it fetches for the first time."]


def _relative(path: Any, run_dir: str) -> str:
    text = str(path)
    if run_dir and text.startswith(run_dir.rstrip("/") + "/"):
        return text[len(run_dir.rstrip("/")) + 1:]
    return text


def _parameter_text(parameters: Any) -> str:
    parts = []
    for key, value in (_metadata(parameters) or {}).items() if isinstance(parameters, Mapping) else []:
        value = ",".join(map(str, value)) if isinstance(value, list) else _num(value)
        parts.append(f"{key} {value}")
    return "; ".join(parts)


def _provenance_lines(state: Mapping[str, Any]) -> list[str]:
    run_dir = str((state.get("final_report_inputs") or {}).get("run_dir", ""))
    merged: dict[str, dict[str, Any]] = {}
    for item in state.get("observations") or []:
        if not isinstance(item, Mapping):
            continue
        identifier = str(item.get("id", item.get("observation_id", "")))
        entry = merged.setdefault(identifier, {})
        for key, value in item.items():
            if isinstance(value, Mapping) and isinstance(entry.get(key), Mapping):
                entry[key] = {**value, **entry[key]}
            else:
                entry.setdefault(key, value)
    lines = ["Evidence provenance:"]
    for identifier, entry in merged.items():
        result = entry.get("result")
        if not isinstance(result, Mapping):
            continue
        action = entry.get("action") if isinstance(entry.get("action"), Mapping) else {}
        function = (action.get("function") or entry.get("function") or result.get("tool") or "observation")
        text = f"- {identifier}: {function}"
        area = action.get("requested_area_id") or entry.get("requested_area_id")
        text += f" area {area}" if area else ""
        parameters = _parameter_text(action.get("parameters", entry.get("params")))
        text += f" ({parameters})" if parameters else ""
        text += f"; {result.get('status', 'recorded')}"
        if result.get("error"):
            text += f": {str(result['error']).rstrip('.')}"
        for key, label in (("fetched", "locations fetched"), ("valid_points", "valid"),
                           ("missing_points", "missing"), ("error_points", "failed, left unqueried"),
                           ("skipped_already_queried", "already queried, skipped"),
                           ("row_count", "rows"), ("retained_row_count", "rows retained")):
            if result.get(key) is not None and (key != "row_count" or "fetched" not in result):
                text += f"; {_num(result[key])} {label}"
        path = result.get("csv_path") or result.get("output_file")
        text += f"; file {_relative(path, run_dir)}" if path else ""
        lines.append(text + ".")
    if len(lines) == 1:
        lines.append("- None.")
    lines.append("The state coverage table keeps every queried location with each sample's cells and RSRP; "
                 "inspect_observation shows those rows.")
    return lines


def _feedback_lines(state: Mapping[str, Any], feedback: Iterable[Any]) -> list[str]:
    lines = ["Feedback from earlier rounds:"]
    for note in state.get("notes") or []:
        if isinstance(note, Mapping):
            lines.append(f"- Round {_num(note.get('step_index'))}: {note.get('kind', 'note')}: {note.get('text', '')}")
        else:
            lines.append(f"- {note}")
    for concern in state.get("verifier_concerns") or []:
        reason = concern.get("reason") if isinstance(concern, Mapping) else concern
        lines.append(f"- Reviewer concern: {reason}")
    reported = set()
    for item in state.get("observations") or []:
        result = item.get("result") if isinstance(item, Mapping) else None
        if not isinstance(result, Mapping) or result.get("status") != "error" or item.get("id") in reported:
            continue
        reported.add(item.get("id"))
        action = item.get("action") if isinstance(item.get("action"), Mapping) else {}
        parameters = _parameter_text(action.get("parameters"))
        lines.append(f"- {item.get('id')}: {action.get('function', 'query')}" + (f" ({parameters})" if parameters else "")
                     + f" failed: {str(result.get('error', 'no detail')).rstrip('.')}. It is not evidence.")
    errors = state.get("errors", state.get("error")) or []
    for error in [errors] if isinstance(errors, str) else errors:
        lines.append(f"- Error: {error if isinstance(error, str) else _compact(error)}")
    for item in [*(state.get("feedback") or []), *feedback]:
        lines.append(f"- {item if isinstance(item, str) else _compact(item)}")
    if len(lines) == 1:
        lines.append("- None.")
    return lines


def build_context(
    state: Mapping[str, Any], tools: Iterable[Any], feedback: Iterable[Any] = ()
) -> Rendered:
    """Fixed skill/task/geography/actions prefix; all evolving evidence is variable.

    The caller keeps the first prefix as its system message for the whole run.
    No clock, notebook, artifact or geometry file is consulted.
    """
    tools = list(tools)
    prefix = "\n\n".join("\n".join(block) for block in (
        [load_skill().rstrip()], _task_lines(state), _kpi_window_lines(state), _geography_lines(state),
        _area_lines(state), _action_lines(state, tools), _completion_lines(),
    ) if block)
    down = _down_id(state.get("task", {}) or {})
    _, areas, _, _ = _geography(state)
    summaries = _summaries(state)
    blocks = [
        _progress_lines(state, summaries, areas, down),
        _coverage_lines(summaries, down),
        _inspection_lines(state),
        _impact_lines(state, summaries, down),
        _unknown_lines(state),
        _completion_state_lines(state),
        _budget_lines(state),
        _provenance_lines(state),
        _feedback_lines(state, feedback),
        ["Reply with your next decision as one JSON object in the decision format of the skill."],
    ]
    variable = "\n\n".join("\n".join(block) for block in blocks if block)
    return Rendered(prefix=prefix, variable=variable)
