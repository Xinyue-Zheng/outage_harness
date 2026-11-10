# Reference by full scan: every location of every activity area in a 100 km window (instruction for the Copilot)

Apply to the repository that holds `outage_harness_langgraph`,
`outage_harness_rule_based` and `outage_harness_evolution`. This builds a
reference for one case that the investigation runs are scored against. It
replaces the lattice part of `Ground_Truth_Scan_2026-10-29.md` (steps 1,
3 and 4: the 1 km scan, the edge rule, the 500 m refinement) with a full
read of every 100 m location inside every activity area in a 100 km
square. It keeps that instruction's KPI steps (2, 2b, 2c, 5, 6) and its
report layout (7) unchanged, and it keeps the per-point record and the
scoring rules of `Evaluation_From_Stored_Data_2026-10-25.md`.

Why. The 30 km window and the lattice were case-specific choices. A run
that ends with every bin closed may still have missed covered locations
outside its window, and the closure audit samples that territory rather
than reading it. For one case we want a reference with no sampling: every
location where people are, out to 50 km from the site in every direction,
read at the finest grain the data has. The two numbers this reference
gives that nothing else gives are: how many covered locations lie outside
the 30 km window, and the per-location class for every activity area, so
a run's classification can be scored point by point.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory, any file in the
  three harness packages (`outage_harness_langgraph`,
  `outage_harness_rule_based`, the concat packages).
- Do not run `uv sync` and do not add dependencies.
- New code goes into a new module `outage_harness_evolution/reference.py`
  (and helpers beside it). It imports the harness packages read-only. If a
  harness function has the window or the area rule hard-coded, do not
  change it: call the lower-level helpers it uses (grid construction,
  disc and buffer selection, `point_coverage.fetch_area_points`,
  `point_fractions`, `radio.eligible_backup_cells`) with the constants of
  this file. If a helper cannot be called that way, stop and report which
  one; do not copy harness code into the new module.
- Tests write only under `tmp_path` or the scratch directory the existing
  evolution tests use.
- Outputs go to `<results root>/reference/<site>_100km/`.

Run as

```
python -m outage_harness_evolution.reference --ticket <ticket id or JSON> --out <results root>/reference [--count-only] [--rings 1,2,3] [--restart]
```

It is a measurement script: no language model, no decision loop. Every
number it writes comes from a tool result or from a file an earlier step
wrote; an absent result is `not recorded`, never a guess. Each step writes
its outputs when complete and is skipped on rerun if they exist;
`--restart` deletes them.

## 0. Constants, all at the top of the module

| name | value | meaning |
|---|---|---|
| `WINDOW_KM` | 100 | square centred on the site: 50 km in every direction |
| `GRID_M` | 100 | location spacing, the same as the harness grid |
| `RINGS_KM` | (15, 30, 50) | distance bands from the site; ring 1 is the 30 km window the runs use, ring 2 from 15 to 30 km, ring 3 from 30 to 50 km |
| `TILE_KM` | 25 | side of one Overpass request; 16 tiles cover the window |
| `TILE_PAUSE_S` | 5 | pause between Overpass requests |
| `SETTLEMENT_RADIUS_M` | city 3000, town 2000, village 1000, hamlet 500 | the harness's disc rule, unchanged |
| `CORRIDOR_HALF_WIDTH_M` | motorway 200, trunk 150, primary 150, secondary 100 | the harness's buffer rule, unchanged |
| `CORRIDOR_MIN_LOCATIONS` | 50 | the harness's rule, unchanged |
| `ACTIVITY_LANDUSE` | residential, industrial, commercial, retail | land-use polygons that are activity areas in their own right |
| `SCAN_RADIUS_M` | 10 | the only radius the point API serves |
| `POINT_WORKERS`, `POINT_TIMEOUT_S`, `POINT_RETRIES` | as `point_coverage` already defines them | |
| `THROUGHPUT_SAMPLE` | 200 | point calls timed before the projection in `--count-only` |
| `COVERAGE_RSRP_DBM`, `LOAD_LIMIT_PERCENT`, `SIGNAL_MARGIN_DB`, `SERVICE_RSRP_DBM` | imported from `completion_point` | one definition |

The settlement and corridor constants must be read from the harness
module that defines them, not retyped; if the harness keeps them in a
table keyed by environment class, read the rural row and record the
values used in `README.md`.

## 1. The window and the grid

Reads: the site position from `query_basic_information`.

Decides: the 100 km square centred on the site, in the same local
equirectangular metres the harness uses, with `GRID_M` spacing and the
origin at the square's south-west corner. One million locations.

Alignment requirement: every location centre of the harness's 30 km grid
for this site must coincide with a centre of the 100 km grid (both grids
are centred on the site with the same spacing, so the offsets differ by a
whole number of cells). Test it on the real site position: build both
grids, pick 100 random harness cells, assert the nearest 100 km centre is
within 1 m. If the harness grid origin is not the window corner, stop and
report how it is laid; do not guess.

Point identity: the reference does not use the harness's grid ids as
keys, because they depend on the window. Every reference point is keyed
by its centre, `lat,lon` rounded to 6 decimals. The reference cache is
`<out>/<site>_100km/reference_cache.jsonl`, one line per fetched point,
key `lat,lon|radius_m|epoch`, append-only, read before any call. A
mapping file `grid_map.json` gives, for the harness's 30 km grid, each
grid id and its reference key, so the scorer and the point cache of the
investigation runs can be joined.

Writes: `window.json` (centre, corners, origin, rows, columns, the three
ring boundaries), `grid_map.json`.

## 2. OpenStreetMap over the window

Reads: the Overpass query text the harness uses at initialization
(places, land use, water, major roads), with the bounding box replaced per
tile.

Decides: 16 tiles of `TILE_KM`, requested one after another with
`TILE_PAUSE_S` between them, through the harness's `query_osm_landuse`
tool if it accepts a bounding box, else through the same HTTP call the
tool makes with the saved query text. Objects are merged by OSM type and
id; an object in two tiles is kept once. A tile that fails after two
retries is recorded as `tile_failed` with the error text and the script
stops: an incomplete map would give an incomplete reference, and the
report must not be built on it.

Writes: `osm_raw/tile_<r>_<c>.json` (the raw answers), `osm_merged.json`,
`osm_calls.json` (per tile: bounding box, seconds, bytes, object count,
status).

## 3. Activity areas

Reads: `osm_merged.json`, the grid of step 1.

Decides, with the harness's own rules and helpers:

- settlements: one disc per `place` node by class (`SETTLEMENT_RADIUS_M`);
  a place polygon, if OSM has one, is used as the area instead of the disc
  and flagged `polygon`;
- corridors: centreline buffers by road class
  (`CORRIDOR_HALF_WIDTH_M`), grouped by `ref` or name, kept when the route
  has at least `CORRIDOR_MIN_LOCATIONS` locations;
- land-use areas: polygons tagged with a value in `ACTIVITY_LANDUSE`,
  each its own area, grouped by polygon;
- a location in two areas belongs to both; the per-area counts say so
  and the per-point record lists all its areas.

Land use defines where people are, not how much traffic a location
carries (handoff, section 3). The report says this in its first section.

Everything else in the window (farmland, forest, grassland, water,
unmapped) is not read at all. The reference therefore says nothing about
coverage loss outside activity areas; the report states this as its one
scope assumption, with the share of the window's locations it leaves out.

Writes: `areas.json`: per area its id, kind, OSM source object, class,
ring of its nearest location, location count, and the list of reference
keys; `area_counts.md`: a table per ring and kind with the location
totals.

## 4. Count first

`--count-only` runs steps 1 to 3, then:

- fetches `THROUGHPUT_SAMPLE` activity locations nearest the site (these
  are not wasted; they are cached), measures calls per second with
  `POINT_WORKERS` workers, and records the error count;
- prints and writes `plan.md`: locations per ring and kind, the
  projected hours per ring at the measured rate, the projected cache
  size;
- stops.

Do not start the full read until the author has seen `plan.md`. Point
counts for a rural 100 km window are expected in the range of 50,000 to
200,000 activity locations, and the projection may be a day or more. The author decides which rings to run
(`--rings`).

## 5. The read

Reads: `areas.json`, `window.json`, the outage date from the ticket as
the epoch.

Decides: every activity location, ring by ring in the order of `--rings`
(default all three), nearest the site first inside a ring, with
`point_coverage.fetch_area_points` on the reference keys' centres,
`SCAN_RADIUS_M`, the pool, the cache. No location outside an activity
area is read. A call that fails after `POINT_RETRIES` is an error point;
the read continues and the error count is in the ring file.

Writes: `ring_<k>.json` when a ring is complete (per point: key, areas,
`n_samples`, the cells listed with RSRP, or `no_sample`, or `error`),
`calls.json` (every call with latency, cache hit or
API call, status). A ring file is written only when every location of
the ring has a record; a break leaves the cache and the next run resumes
from it.

## 6. Outage set, KPI, backups

Steps 2, 2b, 2c, 5 and 6 of `Ground_Truth_Scan_2026-10-29.md` apply
unchanged, with two substitutions:

- "the cells the scan saw" means every cell listed in any sample of any
  ring file;
- the per-point record of section 1 of
  `Evaluation_From_Stored_Data_2026-10-25.md` is computed for every point
  of every ring, by the same `point_fractions`.

A cell first seen in ring 3 and found down joins the outage set, and the
classes of every ring are recomputed; the pass directories of the earlier
instruction apply.

## 7. Classes

Per point, from the record, one class:

| class | condition |
|---|---|
| `no_sample` | `n_samples == 0` |
| `not_covered` | sampled; no outage sector at or above `COVERAGE_RSRP_DBM` |
| `covered_backup` | an outage sector at or above the threshold and at least one eligible backup in the same sample |
| `covered_no_backup` | an outage sector at or above the threshold and no eligible backup |

The four classes are exhaustive and exclusive. `error` points are listed
separately and are in no class. The fractions `f_rsrp` and `f_prb[h]`
stay on the record for the `covered_backup` points; no class is derived
from them.

Writes: `reference.json`: every point with its areas, ring, class, and
record; per area and per ring the count per class; `extent.json`: the
covered points (both covered classes) with the distance from the site and
the harness's 12-wedge bin index, and per wedge the farthest covered
point.

## 8. The two numbers, and the scorer

`reference_report.md` opens with:

1. Covered locations outside the 30 km window: the count of covered
   points in rings 2 and 3, per wedge, with the farthest distance; the
   count of activity areas outside the window with at least one covered
   point. This is the test of the 30 km choice. The activity-area choice
   is not tested: the report names it as the scope assumption.
2. The class table per area and per ring, with `no_sample` and `error`
   counts beside the point counts, as the evaluation instruction requires.

Then the layout of step 7 of the earlier instruction (site table for the
worst hour, per backup the hourly table, what is not established), with
the figures of that step drawn over the 100 km window, the 30 km window
outlined, and the activity areas filled by their majority class.

Scorer: `evolution score-reference <run_dir> <reference_dir>` joins a
run's queried grid cells to reference points through `grid_map.json` and
reports: the number of reference covered points the run queried,
classified, or never reached (inside its window, outside its window);
per-point agreement between the run's class and the reference class on
the points both hold; per-class precision and recall; the run's cost and
end reason from `run.json`. It never fetches. If a run's window is not the
30 km window `grid_map.json` was built for, it fails with both sizes.

## 9. Tests (synthetic fixtures)

1. Grid alignment on a synthetic site: 100 random harness cells match a
   100 km centre within 1 m; a deliberately shifted origin fails.
2. Tile merge: two synthetic tiles sharing an object yield one object;
   a failed tile stops the script with `tile_failed`.
3. Area derivation: a place node of each class, one route above and one
   below `CORRIDOR_MIN_LOCATIONS`, one residential polygon; counts match
   the harness's own derivation on the same fixture inside 30 km.
4. Rings: every location is in exactly one ring; ring 1 equals the 30 km
   window's locations.
5. Classes: four hand-built samples give the four classes; an empty
   sample gives `no_sample`; a failed call is in no class.
6. Resume: a read interrupted after half a ring resumes from the cache
   and makes no API call for cached points.
7. Scorer: a synthetic run with 50 queried cells, 10 of them covered in
   the reference and 3 outside its window, reports 7 and 3.

## 10. Run once, then stop

Run `--count-only` on the closed case and report `plan.md`. Do not start
the full read.

## 11. Report back

File and line for every change; `plan.md`; the alignment test output on
the real site position; the values read for the settlement and corridor
constants and where they came from; any helper that could not be called
without editing a harness package.
