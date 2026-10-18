# Changes of 2026-10-19: fixed grid frame, whole closure, study-area expansion by wedge

For both packages (`outage_harness_langgraph`, rendered; `outage_harness_codex_state`,
concat) unless a step says otherwise. `<pkg>` stands for the package name.
Shared modules (`state0.py`, `evidence_state.py`, `point_coverage.py`,
`completion_point.py`, `context_builder.py`, `runner_point_nodes.py`) are
the same file in both packages: edit once, copy. Every step starts with why,
then the edit. Where the edit is a refactor of existing code, the step gives
the exact signature and behaviour and names the lines to move.

Decisions already made, do not reopen: frame half-width 30,000 m (the
initial 30 km study area has 15 km of room on every side); expansion is a
wedge in one open direction, never the whole rectangle; one wedge step is a
free distance between 500 m and 5,000 m; a direction open at the study-area
edge no longer counts as closed; a direction that reaches the frame edge
closes at the cap and the report says so.

---

## 1. `state0.py`: the grid frame is fixed; the study area is a set of active cells inside it

Why: grid ids are `row * columns + column` from the study area's south-west
corner with the study area's width. Expanding west or south moves the
origin and expanding east changes the width, so every existing id, and with
it the coverage table, the artifacts and the area lists, would point at the
wrong location. Fixing origin and width once, for a frame large enough to
hold any expansion, makes expansion add ids without renumbering any. The
frame is only an indexing space: no OSM query and no point call is made for
it. The study area becomes the set of active cells inside the frame; the
initial rectangle is the first active set, each wedge adds to it.

### 1a. Constants

After `MIN_UNNAMED_PLACE_FEATURES = 20`, add:

```python
FRAME_HALF_WIDTH_M = 30_000.0   # the grid frame: site at the centre; ids never change inside it
EXPANSION_MIN_M = 500.0
EXPANSION_MAX_M = 5_000.0
WEDGE_MARGIN_DEG = 15.0         # a wedge covers its direction bin plus this margin on each side
```

### 1b. `study_area_from_metadata` is unchanged

It still returns the 30 km (rural) square. That square is the initial
active set, not the frame.

### 1c. `build_state0`: frame geometry

Find:

```python
    half = study_area["half_width_m"]
    origin_lat, origin_lon, to_m = projector(latitude, longitude, half)
    columns = rows = int(round(study_area["side_m"] / GRID_SPACING_M))
    total = columns * rows
```

Replace with:

```python
    half = study_area["half_width_m"]
    origin_lat, origin_lon, to_m = projector(latitude, longitude, FRAME_HALF_WIDTH_M)
    columns = rows = int(round(2 * FRAME_HALF_WIDTH_M / GRID_SPACING_M))
    total = columns * rows
    # The initial study area: the metadata square, as a cell set inside the frame.
    low = int(round((FRAME_HALF_WIDTH_M - half) / GRID_SPACING_M))
    high = int(round((FRAME_HALF_WIDTH_M + half) / GRID_SPACING_M))
    active = {r * columns + c for r in range(low, high) for c in range(low, high)}
    shapes = [{"type": "rectangle", "col0": low, "col1": high, "row0": low, "row1": high,
               "reason": study_area["rule"]}]
```

Then every place in `build_state0` that uses the site position `(half, half)`
must use the frame centre instead. Find `(half, half)` in the
`_add_places(...)` call and in `"x_m": half, "y_m": half` of the `site`
dict, and replace `half` by `FRAME_HALF_WIDTH_M` in those three places.

### 1d. Restrict every derived cell set to the active set

Why: `fill`, `corridor` and the activity-feature centre test clip to the
frame (`columns`, `rows`), so without a further filter a polygon that
extends past the 30 km square would be rasterised into inactive cells and
become part of an area the model can query. Every cell set that becomes an
area or a label must be intersected with `active`.

In `build_state0`, apply `& active` at these points:

- land use: `covered.update(fill(ring, ...))` becomes
  `covered.update(fill(ring, GRID_SPACING_M, columns, rows) & active)`;
- corridors: `cells.update(corridor(line, ...))` becomes
  `cells.update(corridor(line, width / 2, GRID_SPACING_M, columns, rows) & active)`;
- in `_activity_features`, after `cells = fill(...)` add `cells &= active`
  and in the centre-cell branch replace `if 0 <= column < columns and 0 <= row < rows:`
  with `if 0 <= column < columns and 0 <= row < rows and row * columns + column in active:`.
  Pass `active` into `_activity_features` as a new last parameter.

### 1e. Move the derivation into one reusable function

Why: expansion must derive settlements, corridors, relations and labels for
a wedge exactly as initialisation does for the square, with numbering that
continues from the existing areas and corridors that extend existing routes.
The code that does this is the body of `build_state0` from `nodes = ...` to
the end of the roads loop. Move it into one function and call it from
`build_state0` and from the expansion.

Signature:

```python
def derive_geography(elements: list[dict], frame: dict, active: set[int], site_xy: tuple[float, float],
                     existing: dict | None = None) -> dict:
    """Rasterise OSM elements into the active cells of the frame.

    frame: {"origin_lat", "origin_lon", "spacing_m", "columns", "rows", "site_lat", "site_lon"}.
    existing: None for initialisation; for an expansion, the current
    {"areas": [...], "area_cells": {id: set}, "geography": [...], "relations": [...],
     "labels": [...], "places": [...]} so that:
      - settlement ids continue from the highest existing S##, corridor ids from the highest R##;
      - a road whose route name (tags ref or name) matches an existing corridor area extends
        that area's cell set instead of creating a new area;
      - a mapped activity group that touches an existing settlement area joins it;
      - relations are added for new overlaps only.
    Returns {"geography", "areas", "area_cells", "relations", "labels", "places",
             "activity_counts", "places_without_activity"} covering old and new.
    """
```

`build_state0` then becomes: compute the frame and `active` (1c), call
`derive_geography(elements, frame, active, (FRAME_HALF_WIDTH_M, FRAME_HALF_WIDTH_M))`,
and assemble the State as before from the result. Behaviour for the
initial square is unchanged.

### 1f. Area names

Why: the report groups and names areas by their `kind` and `name` fields.
Settlement areas today carry `place_names` and a description but no `name`;
road corridors carry the route only in the description.

In `_add_places`, in the `add_area(f"S{index:02d}", "settlement", ...)` call,
add the keyword `name=title`. In the roads loop, in the
`add_area(road_id, "road_corridor", ...)` call, add `name=route`.

### 1g. What State 0 records about the frame and the study area

In the `state` dict of `build_state0`:

- `"grid"`: unchanged keys, now with the frame's origin and `columns = rows = 600`.
- `"site"`: `"x_m": FRAME_HALF_WIDTH_M, "y_m": FRAME_HALF_WIDTH_M`.
- `"study_area"`: add `"frame_half_width_m": FRAME_HALF_WIDTH_M`,
  `"shapes": shapes`, `"active_cells": len(active)`, `"expansions": []`.
- `"coordinate_system"`: change the text to
  `"equirectangular local metres; origin at the frame's south-west corner; x east, y north"`.

Write the active set next to the area memberships:
`(output_dir / "active_grid_ids.json").write_text(json.dumps(sorted(active)))`.

### 1h. Check

Run initialisation for one real site. `state_00.json` has
`grid.columns == 600`, `study_area.active_cells == 90000` for a rural site,
every area's `grid_count` unchanged from before this change (within the
rounding of one cell row), and every settlement area has a `name`.

---

## 2. `evidence_state.py`: `split_geography` carries the active set

Why: the geometry file is what every later module reads for grid ids. It
must hold the active set so that expansion can grow it and the completion
check can find the study-area edge per direction.

In `split_geography`, read `active_grid_ids.json` the same way
`areas_grid_ids.json` is read, and add to the `geometry` dict:

```python
        "active_grid_ids": sorted(active_ids),
        "study_area": copy.deepcopy(initial_state.get("study_area", {})),
```

(`study_area` is already copied; keep one copy.) Nothing else changes.
`_locate` and `_site_relation` read the frame from `grid` and work as they
are.

The geometry file is immutable by design (`open("xb")`). Expansion writes a
new version (section 6); `split_geography` is only called at
initialisation and keeps writing `geography.json`.

---

## 3. `completion_point.py`: whole closure, the edge as evidence, the cap

Why: a direction open at the study-area edge was accepted as closed. It is
not closed; the model must expand there. For it to decide how far, the
block must show what the edge looks like in that direction: the reach, the
edge distance, and how many fetched locations in the outermost strip list
the sector and how strong. A direction whose active cells already reach the
frame edge cannot expand further and closes at the cap.

### 3a. Constants

Find `ACCEPT_EDGE_OPEN = True` and delete the line. Add:

```python
EDGE_STRIP_M = 300.0   # the outermost strip of the active area in a direction, for the edge evidence
```

### 3b. Edge radius and edge evidence per bin

Add after `location_table`:

```python
def active_edge_by_bin(geometry: dict[str, Any], rows: dict[str, dict[str, Any]], bins_total: int) -> dict[int, float]:
    """The farthest active cell from the site in each bin: the study-area edge in that direction."""
    columns, spacing = int(geometry["grid"]["columns"]), float(geometry["grid"]["spacing_m"])
    site_x = site_y = float(geometry["study_area"]["frame_half_width_m"])
    edge: dict[int, float] = {}
    for grid_id in geometry["active_grid_ids"]:
        r, c = divmod(int(grid_id), columns)
        dx, dy = (c + 0.5) * spacing - site_x, (r + 0.5) * spacing - site_y
        b = int(_bearing_deg(dx, dy) // BIN_DEGREES)
        edge[b] = max(edge.get(b, 0.0), math.hypot(dx, dy))
    return edge


def edge_evidence(state: dict[str, Any], rows: dict[str, dict[str, Any]], cell: str, b: int, edge_m: float) -> dict[str, Any]:
    """Fetched locations of any kind in the outermost EDGE_STRIP_M of the active area in bin b."""
    table = state.get("coverage") or {}
    strip = [row for row in rows.values() if row["bin"] == b and row["distance_m"] >= edge_m - EDGE_STRIP_M
             and row["status"] == "valid"]
    listing = []
    for row in strip:
        stats = (table[row["grid_id"]].get("cells") or {}).get(cell)
        if stats is not None and stats["rsrp_max_dbm"] >= COVERAGE_RSRP_DBM:
            listing.append(stats["rsrp_max_dbm"])
    return {"fetched_in_strip": len(strip), "listing_sector": len(listing),
            "rsrp_min_dbm": min(listing) if listing else None, "rsrp_max_dbm": max(listing) if listing else None}
```

`location_table` today iterates `geometry["areas"]` only. Change it to
also add every id in `geometry["active_grid_ids"]` with `"areas": []` and
`"activity": False`, so that fetched non-activity locations near the edge
appear in `rows`. (A location is in `rows` once; areas append to its list
as before.)

### 3c. The edge-open case in `completion_evidence_status`

Find, inside the per-bin loop:

```python
            if closing is None:
                result.update({"status": "open_at_edge", "closing_area": None, "no_sample_areas": skipped,
                               "reason": "no activity location with a sample beyond the reach inside the study area"})
```

Replace with:

```python
            if closing is None:
                edge_m = edges.get(b, 0.0)
                at_cap = edge_m >= float(geometry["study_area"]["frame_half_width_m"]) - float(geometry["grid"]["spacing_m"])
                evidence = edge_evidence(state, rows, cell, b, edge_m)
                result.update({"closing_area": None, "no_sample_areas": skipped, "edge_m": round(edge_m),
                               "edge_evidence": evidence})
                if at_cap:
                    result.update({"status": "closed_at_cap",
                                   "reason": f"the study area reaches the frame edge at {edge_m:.0f} m; no activity location beyond"})
                else:
                    result.update({"status": "open_at_edge",
                                   "reason": f"no activity location beyond the reach inside the study area; edge at {edge_m:.0f} m"})
```

and before the per-sector loop add `edges = active_edge_by_bin(geometry, rows, bins_total)`.

Then the per-sector tally:

```python
        open_bins = {b: r for b, r in sector_bins.items() if r["status"] == "open"}
        edge_bins = {b: r for b, r in sector_bins.items() if r["status"] == "open_at_edge"}
        per_sector[cell] = {"checked_bins": len(sector_bins), "closed": len(sector_bins) - len(open_bins) - len(edge_bins),
                            "open": len(open_bins), "open_at_edge": len(edge_bins), "bins": sector_bins}
        if open_bins:
            unresolved[cell] = "; ".join(f"{r['label']}: {r['reason']}" for r in open_bins.values())
        elif edge_bins and not ACCEPT_EDGE_OPEN:
            unresolved[cell] = ...
```

becomes:

```python
        open_bins = {b: r for b, r in sector_bins.items() if r["status"] == "open"}
        edge_bins = {b: r for b, r in sector_bins.items() if r["status"] == "open_at_edge"}
        cap_bins = {b: r for b, r in sector_bins.items() if r["status"] == "closed_at_cap"}
        per_sector[cell] = {"checked_bins": len(sector_bins), "closed": len(sector_bins) - len(open_bins) - len(edge_bins),
                            "closed_at_cap": len(cap_bins), "open": len(open_bins), "open_at_edge": len(edge_bins),
                            "bins": sector_bins}
        if open_bins or edge_bins:
            unresolved[cell] = "; ".join(f"{r['label']}: {r['reason']}" for r in {**open_bins, **edge_bins}.values())
```

A direction open at the edge now blocks completion.

### 3d. `progress_lines`: the edge line tells the model how to expand

In `progress_lines`, inside `for r in sector["bins"].values():`, after the
`if r["status"] == "open":` block, add:

```python
                elif r["status"] == "open_at_edge":
                    e = r["edge_evidence"]
                    signal = (f"{e['listing_sector']} of {e['fetched_in_strip']} fetched locations in the outermost "
                              f"{EDGE_STRIP_M:.0f} m list the sector, RSRP {e['rsrp_min_dbm']:g} to {e['rsrp_max_dbm']:g} dBm"
                              if e["listing_sector"] else
                              f"none of {e['fetched_in_strip']} fetched locations in the outermost {EDGE_STRIP_M:.0f} m lists the sector")
                    reach = f"covers to {r['reach_m']} m" if r["active"] else "not covered"
                    lines.append(f"  {cell}, {r['label']}: {reach}; study-area edge at {r['edge_m']} m; {signal}. "
                                 f"Expand the study area in this direction to continue (expand_study_area).")
```

and change the per-sector summary line to:

```python
        cap = [r["label"] for r in sector["bins"].values() if r["status"] == "closed_at_cap"]
        lines.append(f"- {cell}: {sector['closed']} of {sector['checked_bins']} checked directions closed"
                     + (f"; closed at the frame edge: {', '.join(cap)}" if cap else "") + ".")
```

Delete the old "open at the study-area edge, not required" clause.

### 3e. `completion_context_lines` and the report

In `completion_context_lines`, the `elif r["status"] == "open_at_edge":`
branch prints `open at the study-area edge` already; add a branch for
`closed_at_cap`: `parts.append(f"{r['label']}: {reach}; closed at the frame edge")`.

In `final_report`, section 4, replace the loop that prints
`open_at_edge` bins with two loops: `open_at_edge` prints
`"... open at the study-area edge at {edge_m} m; not expanded"` and
`closed_at_cap` prints `"... closed at the frame edge ({edge_m} m); nothing beyond was mapped or queried"`.

### 3f. The skill text (both variants)

In the "Inspection and completion" paragraph, replace the sentence about
open study-area edges with:

> A direction open at the study-area edge is not closed. The progress lines
> show the edge distance and how many fetched locations in the outermost
> strip still list the sector and how strong; expand the study area in that
> direction with expand_study_area, a larger step when the signal at the
> edge is strong, a smaller one when it is weak or listed at few locations.
> A direction that reaches the frame edge closes there and is reported.

The concat variant gets the same sentence minus "The progress lines show
...; " (it has no progress lines) and keeps the rest.

---

## 4. The action `expand_study_area`

Why: the model decides where and how far; the program does the geometry
and the OSM query for the wedge only. The wedge is the open direction bin
plus a margin on each side, from the current edge in that direction out by
the chosen distance. OSM is queried for the wedge's bounding box, which is
small, and only elements that rasterise into wedge cells become areas.

### 4a. Declaration, both packages

Add to the tools shown to the model (next to `query_area_coverage` in
`runner_point_nodes.py`, and to the filter list in `initialize_node`):

```python
EXPAND_STUDY_AREA = {
    "name": "expand_study_area",
    "description": ("Grow the study area in one direction that the completion progress reports as open at the "
                    "study-area edge. direction is the label exactly as printed, for example \\"east 90-120 deg\\"; "
                    "distance_m is how far beyond the current edge to go, 500 to 5000. The program fetches the mapped "
                    "geography of that wedge and adds its settlements and road corridors as new areas. Costs one "
                    "OpenStreetMap query and no coverage calls."),
    "input_schema": {"type": "object",
                     "properties": {"direction": {"type": "string"}, "distance_m": {"type": "number"}},
                     "required": ["direction", "distance_m"], "additionalProperties": False},
}
```

`runner.py`: add `"expand_study_area": {"direction", "distance_m"}` to
`PARAMETERS` and `"expand_study_area"` to the `function` enum of
`DECISION_SCHEMA`. `gap_checks.py`: an expansion's gap targets may be
empty or name the sector ids; add it to `_NO_TARGET_NEEDED`.

### 4b. Validation, both packages (`runner_point_nodes.py`)

```python
def validate_expand_study_area(arguments: dict[str, Any], state: dict[str, Any], run_dir: str | Path) -> dict[str, Any]:
    """The direction must be a bin reported open at the study-area edge; the step must fit the frame.
    Returns the bin record to expand."""
    distance = arguments.get("distance_m")
    if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not (EXPANSION_MIN_M <= distance <= EXPANSION_MAX_M):
        raise ValueError(f"distance_m must be a number between {EXPANSION_MIN_M:g} and {EXPANSION_MAX_M:g}")
    label = str(arguments.get("direction", "")).strip()
    checks = state.get("completion_checks") or {}
    candidates = {}
    for sector in (checks.get("boundary") or {}).get("sectors", {}).values():
        for r in sector["bins"].values():
            if r["status"] == "open_at_edge":
                candidates[r["label"]] = r
    if label not in candidates:
        raise ValueError("direction must be one of the directions reported open at the study-area edge: "
                         + (", ".join(sorted(candidates)) or "none"))
    r = candidates[label]
    frame_half = float(read_geometry(state, run_dir)["study_area"]["frame_half_width_m"])
    if r["edge_m"] + distance > frame_half:
        raise ValueError(f"the step would leave the frame: edge {r['edge_m']} m plus {distance:g} m exceeds {frame_half:g} m; "
                         f"at most {frame_half - r['edge_m']:.0f} m is possible")
    return r
```

`EXPANSION_MIN_M`, `EXPANSION_MAX_M` are imported from `state0`. In
`validate_node` (both packages, both branches), add before the
`inspect_observation` branch:

```python
            elif action_name == "expand_study_area":
                validate_expand_study_area(arguments, state["state"], state["output_dir"])
```

In the concat package this is one of the few program checks the baseline
keeps, because an expansion with a nonsense direction has no meaning as a
tool call; it is the same kind of check as "area id exists".

### 4c. Wedge cells (`state0.py`)

```python
def wedge_cells(frame: dict, bin_index: int, inner_m: float, outer_m: float) -> set[int]:
    """Frame cells whose centre lies between inner_m and outer_m from the site and within the bin's
    angular span widened by WEDGE_MARGIN_DEG on each side."""
    columns, rows, spacing = int(frame["columns"]), int(frame["rows"]), float(frame["spacing_m"])
    site = FRAME_HALF_WIDTH_M
    a0 = bin_index * BIN_DEGREES - WEDGE_MARGIN_DEG
    a1 = (bin_index + 1) * BIN_DEGREES + WEDGE_MARGIN_DEG
    cells = set()
    r_lo = max(0, int((site - outer_m) // spacing)); r_hi = min(rows, int((site + outer_m) // spacing) + 2)
    for r in range(r_lo, r_hi):
        y = (r + 0.5) * spacing - site
        for c in range(max(0, int((site - outer_m) // spacing)), min(columns, int((site + outer_m) // spacing) + 2)):
            x = (c + 0.5) * spacing - site
            d = math.hypot(x, y)
            if not (inner_m < d <= outer_m):
                continue
            bearing = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
            if a0 <= bearing <= a1 or a0 <= bearing - 360.0 <= a1 or a0 <= bearing + 360.0 <= a1:
                cells.add(r * columns + c)
    return cells
```

`BIN_DEGREES` is imported from `completion_point` (or duplicated as a
constant in `state0` with the same value; one source is better: move
`BIN_DEGREES = 30.0` to `state0.py` and import it in `completion_point.py`).

### 4d. Execution (`runner_point_nodes.py`)

```python
def execute_expand_study_area(state: dict[str, Any], arguments: dict[str, Any], run_dir: str | Path,
                              step_index: int, client: Any) -> dict[str, Any]:
    """Grow the active set by one wedge, fetch the wedge's OSM elements through the client's
    query_osm_landuse, derive its areas, and write the next geography version."""
    geometry = read_geometry(state, run_dir)
    r = validate_expand_study_area(arguments, state, run_dir)
    inner, outer = float(r["edge_m"]), float(r["edge_m"]) + float(arguments["distance_m"])
    cells = wedge_cells(geometry["grid"], int(r["bin"]), inner, outer)
    new_cells = cells - set(map(int, geometry["active_grid_ids"]))
    if not new_cells:
        raise ValueError("the wedge adds no cell inside the frame")
    # Bounding box of the new cells in WGS84, for the OSM query.
    columns, spacing = int(geometry["grid"]["columns"]), float(geometry["grid"]["spacing_m"])
    rs = [c // columns for c in new_cells]; cs = [c % columns for c in new_cells]
    lat0, lon0 = float(geometry["grid"]["origin_lat"]), float(geometry["grid"]["origin_lon"])
    lon_scale = 111_320.0 * math.cos(math.radians(float(geometry["site"]["lat"])))
    bbox = {"min_lng": lon0 + min(cs) * spacing / lon_scale, "max_lng": lon0 + (max(cs) + 1) * spacing / lon_scale,
            "min_lat": lat0 + min(rs) * spacing / 111_320.0, "max_lat": lat0 + (max(rs) + 1) * spacing / 111_320.0}
    result = client.call("query_osm_landuse", bbox, call_id=f"step_{step_index:02d}_expand")
    summary = _summarize(result)   # the runner's helper; import it where this function lives
    step_dir = Path(run_dir) / "steps" / f"step_{step_index:02d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "resolved_parameters.json").write_text(json.dumps({**arguments, "bin": r["bin"], "inner_m": inner, "outer_m": outer,
                                                                  "new_cells": len(new_cells), "bbox": bbox}, indent=2) + "\n")
    if summary["status"] != "success":
        return {**summary, "tool": "expand_study_area"}
    collection = json.loads(Path(summary["output_file"]).read_text(encoding="utf-8"))
    raw_path = (summary.get("details") or {}).get("raw_osm_file") or collection.get("raw_osm_file")
    payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    return {**summary, "tool": "expand_study_area",
            "details": {**(summary.get("details") or {}), "wedge": {"bin": r["bin"], "label": r["label"], "inner_m": inner,
                                                                       "outer_m": outer, "new_cells": sorted(new_cells)},
                        "raw_osm_file": raw_path}}
```

`query_osm_landuse` in the tool library takes the bbox as four arguments
and tiles it in `OVERPASS_TILES x OVERPASS_TILES` requests. For a wedge the
box is small; pass one tile. Add an optional `tiles: int = OVERPASS_TILES`
parameter to `query_osm_landuse` and have the client forward it when the
arguments carry `"tiles": 1`; include `"tiles": 1` in `bbox` above.

### 4e. State update (`evidence_state.py`)

```python
def apply_expansion(state: dict, observation: dict, run_dir: str | Path) -> dict:
    """Add the wedge's cells to the active set, derive the wedge's areas with derive_geography,
    write geography_vN.json, move the pointer, refresh summaries."""
    from .state0 import derive_geography, FRAME_HALF_WIDTH_M
    geometry = _geometry(state, run_dir)
    details = observation["result"]["details"]
    wedge = details["wedge"]
    payload = json.loads(Path(details["raw_osm_file"]).read_text(encoding="utf-8"))
    active = set(map(int, geometry["active_grid_ids"])) | set(wedge["new_cells"])
    frame = {**geometry["grid"], "site_lat": geometry["site"]["lat"], "site_lon": geometry["site"]["lon"]}
    existing = {"areas": list(state["areas"]), "area_cells": {a: set(map(int, g["grid_ids"])) for a, g in geometry["areas"].items()},
                "geography": [], "relations": list(state["geography"].get("relations", [])),
                "labels": None, "places": list((state.get("geography_summary") or {}).get("places", []))}
    derived = derive_geography(payload["elements"], frame, set(wedge["new_cells"]), (FRAME_HALF_WIDTH_M, FRAME_HALF_WIDTH_M), existing)
    updated = copy.deepcopy(state)
    # Versioned geometry file: the previous one is never rewritten.
    version = len(updated["study_area"].get("expansions", [])) + 2
    new_geometry = {**geometry, "active_grid_ids": sorted(active),
                    "areas": {a: {"geometry": _area_geometry(meta), "grid_ids": sorted(map(str, derived["area_cells"][a]))}
                              for a, meta in ((m["id"], m) for m in derived["areas"])},
                    "objects": {**geometry["objects"], **{o["id"]: o.get("geometry") for o in derived["geography"]}}}
    encoded = (json.dumps(new_geometry, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    name = f"geography_v{version}.json"
    with (Path(run_dir) / name).open("xb") as stream:
        stream.write(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    updated["geography"]["geometry"] = {"path": name, "sha256": digest}
    updated["geography"]["source"]["geometry"] = {"path": name, "sha256": digest}
    updated["geography"]["areas"] = {m["id"]: {**_metadata(m), "id": m["id"], "grid_count": len(derived["area_cells"][m["id"]]),
                                               "locations": len(derived["area_cells"][m["id"]]),
                                               **_site_relation(sorted(map(str, derived["area_cells"][m["id"]])), updated)}
                                     for m in derived["areas"]}
    updated["areas"] = list(updated["geography"]["areas"].values())
    updated["geography"]["relations"] = _metadata(derived["relations"])
    updated["study_area"]["expansions"] = [*updated["study_area"].get("expansions", []),
                                           {"step": observation.get("step"), "direction": wedge["label"], "inner_m": wedge["inner_m"],
                                            "outer_m": wedge["outer_m"], "new_cells": len(wedge["new_cells"]),
                                            "new_areas": [m["id"] for m in derived["areas"] if m["id"] not in {a["id"] for a in state["areas"]}]}]
    updated["study_area"]["active_cells"] = len(active)
    _record(updated, observation, Path(details.get("output_file", "")), run_dir, new_cells=len(wedge["new_cells"]))
    _refresh(updated, new_geometry)
    return updated
```

`_refresh` must take the summaries from `point_coverage.refresh_summaries`
in the per-point packages; call whichever the package uses after
`apply_point_coverage`. The area memberships file `areas_grid_ids.json` is
written again with the full mapping, and `active_grid_ids.json` with the
new active set.

### 4f. Runner nodes, both packages

`execute_tool_node`: add before the `query_area_coverage` branch:

```python
        if state["action_name"] == "expand_study_area":
            summary = execute_expand_study_area(state["state"], state["arguments"], state["output_dir"],
                                                state["step_index"], client)
            result = (ToolSuccess(summary["tool"], summary["output_file"], summary.get("row_count", 0), (),
                                  source="openstreetmap", details=summary["details"])
                      if summary["status"] == "success" else ToolFailure("expand_study_area", "ExpansionFailure", summary.get("error", "")))
            _write_json(step_dir / "tool_result.json", _summarize(result))
            return {"tool_result": result}
```

`update_state_node`: add next to the coverage branch:

```python
        if state["action_name"] == "expand_study_area" and summary["status"] == "success":
            new_state = apply_expansion(new_state, {**observation, "step": index}, state["output_dir"])
```

The budget is untouched; the step counts as a tool call for the caps.

### 4g. Context, rendered package

In `_task_lines`, after the study-area line, add when expansions exist:

```python
    for e in (study.get("expansions") or []):
        lines.append(f"Study area expanded at step {e['step']}: {e['direction']}, {e['inner_m']:g} to {e['outer_m']:g} m "
                     f"from the site; new areas: {', '.join(e['new_areas']) or 'none'}.")
```

The areas list and the progress block already pick up the new areas and the
new edge from State.

---

## 5. `point_coverage.py`

Nothing changes. `grid_center` and `_memberships` read the frame and the
areas from the geometry file. `fetch_area_points` skips already fetched
locations, so a corridor area that grew by a wedge fetches only its new
part.

---

## 6. Tests to add

- `state0`: a synthetic Overpass payload with one settlement and one road
  crossing the 30 km edge; assert the initial square has 90,000 active
  cells, the areas stop at the square's edge, and `derive_geography` with an
  `existing` set extends the road corridor instead of creating a second one.
- `wedge_cells`: for bin 3 (east, 90 to 120 deg) with inner 15,000 and outer
  17,000, every returned cell has bearing between 75 and 135 deg and
  distance in range; none repeats an active cell after the set difference.
- `completion`: a sector covering to the edge in one bin yields
  `open_at_edge` with `edge_evidence`, and `unmet_required` reports it;
  with the active set pushed to the frame edge in that bin it yields
  `closed_at_cap` and passes.
- `validate_expand_study_area`: wrong label, distance out of range, and a
  step past the frame are rejected with the messages above.
- Runner integration with a fake OSM client: an expansion step adds areas,
  writes `geography_v2.json`, and the next context lists the new areas.

---

## 7. Check on a real run

1. Initialise one site: `grid.columns == 600`, `study_area.active_cells == 90000`.
2. Run the rendered package until a direction is open at the edge. The
   progress block shows the edge line with the strip evidence.
3. Let the model (or a scripted decision) call
   `expand_study_area(direction=<that label>, distance_m=2000)`. The run
   directory gains `geography_v2.json`; `state_NN.json` lists the new
   areas; the next progress block either names an area to fetch in that
   direction or reports the edge farther out.
4. A fourth 5,000 m step in the same direction is rejected with the frame
   message (three steps reach the 15 km of room).
