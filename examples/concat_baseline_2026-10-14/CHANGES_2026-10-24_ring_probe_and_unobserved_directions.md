# Changes of 2026-10-24: a ring probe at initialization; unobserved directions named

All three packages. Shared files `point_coverage.py`, `completion_point.py`,
`context_builder.py`; `langgraph_runner.py` in each package. Every step
starts with why, then the edit with the code pasted.

---

## 1. Why

The completion check asks only about directions where an outage sector has
already been seen in a fetched location, plus one margin bin on each side.
The investigation therefore follows its own first observations: if the
first queried areas lie between 90° and 180°, only those directions are ever
checked, and a run can end with every checked direction closed while a
whole quadrant was never fetched. The reviewed run shows this: 270° to 360°
was never activated, and the report's "4 of 4 closed" counts only the
checked directions.

Two changes close the gap. First, a ring probe at initialization: the
program fetches a ring of grid locations around the site in every bin
before the first model decision, so every sector's bearing appears in the
coverage table from real observation and no sector can hide. Second, the
check records, per bin, whether any location near the site was fetched,
and the progress block and the report name the directions never observed,
so an unobserved direction is visible rather than silently uncounted. A
direction that was observed and showed no outage sector stays unchecked,
which is correct: there is nothing there to close.

The probe is a program step, not a model action: there is no choice in it,
and every run must have it. It costs 24 point calls once.

---

## 2. `point_coverage.py`: the probe

### 2a. Constants

After `COVERAGE_RSRP_DBM = -110.0`, add:

```python
# The initialization probe: one grid location per direction bin on each ring, fetched before the
# first model decision so that every outage sector's bearing is observed. Radii in metres.
PROBE_RING_RADII_M = (500.0, 1000.0)
PROBE_BIN_DEGREES = 30.0
PROBE_RESOLUTION_M = 10.0
PROBE_AREA_ID = "probe_ring"
```

### 2b. The probe locations

Add after `grid_center`:

```python
def probe_ring_ids(geometry: Mapping[str, Any]) -> list[str]:
    """One grid location per bin on each probe ring: the cell whose centre is nearest the
    point at the ring radius along the bin's centre bearing. Duplicates and cells outside the
    frame are dropped. Bearings are compass degrees, 0 north, clockwise."""
    grid, site = geometry["grid"], geometry["site"]
    columns, rows, spacing = int(grid["columns"]), int(grid["rows"]), float(grid["spacing_m"])
    sx, sy = float(site["x_m"]), float(site["y_m"])
    ids: list[str] = []
    bins = int(round(360.0 / PROBE_BIN_DEGREES))
    for radius in PROBE_RING_RADII_M:
        for b in range(bins):
            bearing = math.radians(b * PROBE_BIN_DEGREES + PROBE_BIN_DEGREES / 2)
            x, y = sx + radius * math.sin(bearing), sy + radius * math.cos(bearing)
            column, row = int(x // spacing), int(y // spacing)
            if 0 <= column < columns and 0 <= row < rows:
                grid_id = str(row * columns + column)
                if grid_id not in ids:
                    ids.append(grid_id)
    return ids
```

### 2c. Fetching an explicit id list

`fetch_area_points` resolves an area id to grid ids. Give it a way to take
the ids directly. Find its signature:

```python
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
```

Add one keyword at the end: `grid_ids: list[str] | None = None,`. Then find
the two lines that resolve the area:

```python
    if area_id not in geometry["areas"]:
        raise ValueError(f"Unknown area {area_id!r}")
```
and
```python
    requested = [str(g) for g in geometry["areas"][area_id]["grid_ids"]]
```

Replace them with:

```python
    if grid_ids is None and area_id not in geometry["areas"]:
        raise ValueError(f"Unknown area {area_id!r}")
```
and
```python
    requested = [str(g) for g in (grid_ids if grid_ids is not None else geometry["areas"][area_id]["grid_ids"])]
```

Everything else in the function (the point calls, the artifact, the result
summary) is unchanged; the artifact's `area_id` is whatever was passed, here
`probe_ring`.

### 2d. The table accepts locations outside every area

`apply_point_coverage` raises for a grid id that belongs to no area
("Artifact lists grid id ... outside every area"). Probe locations may lie
in forest. Find that check:

```python
        if grid_id not in memberships:
            raise ValueError(f"Artifact lists grid id {grid_id} outside every area")
```

Replace with:

```python
        if grid_id not in memberships and artifact.get("area_id") != PROBE_AREA_ID:
            raise ValueError(f"Artifact lists grid id {grid_id} outside every area")
```

and where the entry is built, `_point_entry(point, observation_id, memberships[grid_id])`,
use `memberships.get(grid_id, [])` so a probe location gets an empty area
list. `area_summary` and `refresh_summaries` iterate areas by their grid
ids, so probe locations outside every area enter no area summary; the
study-area summary counts them only if the study area is itself an area in
`geometry["areas"]`, which is the existing behaviour for every location.

---

## 3. `langgraph_runner.py`, `initialize_node`: run the probe

Why: initialization is where the program gathers the facts that need no
decision. The probe is one of them.

Find, in `initialize_node`, the line that writes `initialization_observations.json`:

```python
        _write_json(output_dir / "initialization_observations.json", initial_observations)
```

Add directly before it:

```python
        if fetch_landuse_before_decision:
            from outage_harness_<pkg>.point_coverage import (
                PROBE_AREA_ID, PROBE_RESOLUTION_M, apply_point_coverage, fetch_area_points, probe_ring_ids, read_geometry,
            )
            from outage_harness_<pkg>.radio import eligible_backup_cells, is_outage_cell

            task = case_state["task"]
            geometry = read_geometry(case_state, output_dir)
            probe_ids = probe_ring_ids(geometry)
            probe_result = fetch_area_points(case_state, PROBE_AREA_ID, output_dir, point_query,
                                             radius_m=PROBE_RESOLUTION_M, call_id="init_probe", grid_ids=probe_ids)
            probe_observation = {
                "id": "init_obs_03", "purpose": "Observe every direction around the site before the first decision.",
                "information_gaps": [], "action": {"function": "probe_ring", "parameters": {"radii_m": list(PROBE_RING_RADII_M)}},
                "result": probe_result,
            }
            case_state = apply_point_coverage(case_state, probe_observation, output_dir,
                                              lambda c: is_outage_cell(c, task), lambda cells: eligible_backup_cells(cells, task))
            case_state["query_budget"]["locations_spent"] += probe_result["details"]["fetched"]
            initial_observations = [*initial_observations, probe_observation]
```

This must come after `split_geography` (the geometry file exists) and
after `query_budget` is set, which is the order the node already has.
`point_query` is the builder's parameter (part E of the TODO list). Add
`PROBE_RING_RADII_M` to the import line.

The concat packages run the same code: the probe is initialization, and
its observation joins the initialization message of 2026-10-23 as a third
`[tool probe_ring(...) output]` block, shown truncated like the others.

---

## 4. `completion_point.py`: observed and unobserved directions

### 4a. Constant

After `EDGE_STRIP_CELLS = 3`, add:

```python
OBSERVED_RADIUS_M = 2_000.0   # a direction counts as observed when some location within this distance of the site was fetched
```

### 4b. Record it per bin

In `completion_evidence_status`, find where `per_sector` is assembled (the
loop `for cell in outage_cells:`). Before that loop, add:

```python
    observed_bins = {row["bin"] for row in rows.values() if row["status"] != "unqueried" and row["distance_m"] <= OBSERVED_RADIUS_M}
    activity_bins = {row["bin"] for row in rows.values() if row["activity"]}
    unobserved = []
    for b in range(bins_total):
        if b in observed_bins:
            continue
        label = COMPASS[int((b * BIN_DEGREES + BIN_DEGREES / 2) // 45) % 8] + f" {int(b * BIN_DEGREES)}-{int((b + 1) * BIN_DEGREES)} deg"
        unobserved.append({"bin": b, "label": label,
                           "activity_inside": b in activity_bins,
                           "reason": ("activity location present but not fetched" if b in activity_bins
                                      else "no activity location there inside the study area")})
```

(`rows` is the location table and `bins_total` the bin count, both already
computed in the function. `rows` holds only area locations; probe locations
outside every area are not in it. Extend `location_table` so that every
entry of `state["coverage"]` is a row, with `"areas": []` and
`"activity": False` when it belongs to no area: in `location_table`, after
the loop over `geometry["areas"]`, add a loop over
`(state.get("coverage") or {}).items()` that creates a row for any grid id
not yet in `rows`, with the same distance, bearing and bin computation.)

Then, in the returned `boundary` dict, add:

```python
        "unobserved_directions": unobserved,
```

### 4c. The progress block

In `progress_lines`, after the per-sector lines and before the
`backup_load` line, add:

```python
    unobserved = boundary.get("unobserved_directions") or []
    if unobserved:
        with_activity = [u["label"] for u in unobserved if u["activity_inside"]]
        without = [u["label"] for u in unobserved if not u["activity_inside"]]
        if with_activity:
            lines.append("- directions never observed, with activity locations inside the study area not fetched: "
                         + ", ".join(with_activity) + ". Query the nearest area in those directions.")
        if without:
            lines.append("- directions never observed, no activity location there inside the study area: "
                         + ", ".join(without) + ".")
```

### 4d. The report

In `final_report`, in section 4 ("What this report does not establish"),
add after the missing-data lines:

```python
    for u in (boundary.get("unobserved_directions") or []):
        lines.append(f"   - {u['label']}: never observed; {u['reason']}.")
```

and change the per-sector completion line in the header from
"<closed> of <checked> directions closed" to
"<closed> of <checked> checked directions closed; <n> directions never observed",
where `n` is the length of `unobserved_directions`.

---

## 5. The skill text (all three)

Find the paragraph on the boundary check. Append:

```
Initialization probes a ring of locations around the site in every direction, so every outage sector's bearing is observed before your first decision. A direction the progress block lists as never observed with activity locations inside the study area needs a coverage query of the nearest area there; a direction with no activity location needs nothing.
```

---

## 6. Check

1. A new run's `state_00.json` coverage table has about 24 entries before
   the first decision, with `observation: init_obs_03`; `run_log.md`'s
   step 0 row mentions the probe.
2. The first progress block shows active directions for every outage
   sector that the probe observed, not only for the first queried area.
3. On the reviewed case, the report's section 4 names 270 to 360 deg as
   either "no activity location there" or "activity location present but
   not fetched", and the header shows "n directions never observed".
4. The concat run's initialization message has three tool blocks.
