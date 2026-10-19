# Fix: the expansion wedge must start at the current edge, not at a circle

Why. The first southward expansion added an annular sector whose inner
boundary is a circle of about 17.3 km (the farthest active distance inside
the arc), while the old study-area edge is the straight line at 15 km. The
band between the line and the circle (white in the plot) was never added,
never sent to OSM, and can never be closed: the completion check will keep
reporting the direction open at the edge, because the activity locations
just beyond 15 km are in no area. The same gap appears at every expansion
after the first, between the previous wedge's outer arc and the new inner
circle, because a circle never matches a boundary that is a square or an
earlier arc.

The fix is a definition, then two functions. An expansion by `distance_m`
in a direction pushes the current edge outward by `distance_m` along every
bearing of the arc. The region added is: every grid cell whose bearing is
inside the arc, that is not active yet, and whose distance from the site is
at most the current edge distance along its own bearing plus `distance_m`.
Its inner boundary is the active set itself, whatever shape it has; its
outer boundary is the old boundary moved outward. Nothing is left between.

Both packages (and the third, if already copied). Shared file:
`state0.py` for the two functions, `completion_point.py` and
`runner_point_nodes.py` for their use.

---

## 1. `state0.py`: the edge distance along a bearing, from the recorded shapes

Why: the edge must be computable along any bearing, not only per 30° bin,
and it must compose across expansions. Recording each wedge as an arc plus
the distance it added makes the edge along a bearing a sum: the square's
edge plus the distance of every wedge whose arc covers that bearing.

### 1a. What `study_area` records per wedge

Find the place in the expansion state update where the wedge is appended
to `state["study_area"]` (the Copilot named it the expansion history). Make
sure every recorded wedge has exactly these fields, whatever else it keeps:

```python
{"bin": <int>, "label": <direction label>, "start_deg": <float>, "end_deg": <float>,
 "distance_m": <float the model asked for>, "cells_added": <int>}
```

`start_deg` and `end_deg` are compass degrees, clockwise, the bin plus its
15° margin on each side, as already computed. `from_m` and `to_m`, if
present, may stay for the record; nothing reads them after this fix.

### 1b. The two functions

Add after `WEDGE_MARGIN_DEG = 15.0`:

```python
def _in_arc(bearing: float, start: float, end: float) -> bool:
    """Is bearing inside the clockwise arc from start to end (degrees, mod 360)?"""
    return (bearing - start) % 360.0 <= (end - start) % 360.0


def edge_distance_m(study_area: dict, bearing: float) -> float:
    """Distance from the site to the study-area edge along a compass bearing: the initial
    square's boundary along that bearing, plus the distance of every expansion wedge whose
    arc covers the bearing. Composes across expansions in the same direction."""
    half = float(study_area["half_width_m"])
    rad = math.radians(bearing)
    distance = half / max(abs(math.sin(rad)), abs(math.cos(rad)))
    for wedge in study_area.get("expansions") or []:
        if _in_arc(bearing, float(wedge["start_deg"]), float(wedge["end_deg"])):
            distance += float(wedge["distance_m"])
    return distance


def wedge_cells(frame: dict, study_area: dict, active: set[int], bin_index: int, distance_m: float) -> set[int]:
    """The cells an expansion adds: inside the arc of the bin plus its margin, not active yet,
    and no farther from the site than the current edge along their own bearing plus distance_m.
    The inner boundary is the active set, whatever its shape; the outer boundary is the old
    boundary pushed outward by distance_m."""
    columns, rows = int(frame["columns"]), int(frame["rows"])
    spacing = float(frame["spacing_m"])
    site = FRAME_HALF_WIDTH_M
    start = (bin_index * 30.0 - WEDGE_MARGIN_DEG) % 360.0
    end = ((bin_index + 1) * 30.0 + WEDGE_MARGIN_DEG) % 360.0
    farthest = max(edge_distance_m(study_area, (start + step) % 360.0)
                   for step in range(0, int((end - start) % 360.0) + 1)) + distance_m
    cells: set[int] = set()
    c0 = max(0, int((site - farthest) // spacing)); c1 = min(columns - 1, int((site + farthest) // spacing))
    r0 = max(0, int((site - farthest) // spacing)); r1 = min(rows - 1, int((site + farthest) // spacing))
    for row in range(r0, r1 + 1):
        dy = (row + 0.5) * spacing - site
        for column in range(c0, c1 + 1):
            cell = row * columns + column
            if cell in active:
                continue
            dx = (column + 0.5) * spacing - site
            bearing = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
            if not _in_arc(bearing, start, end):
                continue
            if math.hypot(dx, dy) <= edge_distance_m(study_area, bearing) + distance_m:
                cells.add(cell)
    return cells
```

Replace the existing `wedge_cells(frame, bin_index, inner_m, outer_m)` and
its callers with this signature. If the recorded list is named differently
from `expansions`, use that name in `edge_distance_m`.

Check: with no expansions, `edge_distance_m(study_area, 180.0)` is
`half_width_m` and `edge_distance_m(study_area, 225.0)` is
`half_width_m * sqrt(2)`. After one southward expansion of 2,000 m,
`edge_distance_m(study_area, 180.0)` is `half_width_m + 2000`.

---

## 2. `runner_point_nodes.py`: execution uses the new cell set

Why: the OSM bounding box and the derived areas must cover the cells that
are added, which now reach back to the old edge.

In `execute_expand_study_area`, find the call that computes the wedge cells
(it passes `inner` and `outer` radii) and replace it with:

```python
    cells = wedge_cells(geometry["grid"], state["study_area"], active, int(r["bin"]), float(arguments["distance_m"]))
```

where `active` is the current active set (the Copilot's implementation
reads it from `active_grid_ids.json` or the geometry; use that). Then build
the OSM bounding box from the cells themselves, not from arc radii: the
minimum and maximum row and column of `cells`, converted to WGS84 with the
frame origin, plus one grid spacing of margin on each side. Everything
after (OSM call, `derive_geography` on `cells`, the artifact) is unchanged.

Validation: the frame check becomes "the farthest cell of the new set is
inside the frame", which `wedge_cells` already guarantees by clipping to
the frame; keep the explicit rejection message when
`edge_distance_m(study_area, bearing) + distance_m` exceeds the square
frame boundary along the bin's centre bearing, so the model is told the
remaining room instead of silently getting a clipped wedge.

---

## 3. `completion_point.py`: the same edge for the evidence line

Why: the edge distance shown to the model must be the one the expansion
uses, or the two disagree after the first expansion.

Find `active_edge_by_bin` (or wherever the edge distance per bin is
computed for the `open_at_edge` evidence) and make it return, per bin,
`edge_distance_m(state["study_area"], bin_index * 30.0 + 15.0)` from
`state0`. The strip evidence (`EDGE_STRIP_M`) stays as it is, measured
inward from that edge.

---

## 4. Check on the run that produced the plot

Re-run the same southward expansion from the step before it. The added
region must touch the dashed line at 15 km along its whole width inside the
arc and extend 2,000 m (or the distance asked) beyond the old edge along
every bearing, with no white band. The two dotted settlements below the
line in the plot must now belong to areas, and the next progress block must
name them as areas to fetch in that direction instead of reporting the
direction open at the edge.
