# Boundary and interior: the current completion specification, and cost

Apply to `outage_harness_langgraph` and `outage_harness_rule_based` only.
Synthetic fixtures and tests; no real cases. Report every change as file
and line.

This file supersedes part 2 of
`Copilot_Partial_Area_Query_Amendment_2026-10-28.md` (resolution by
extent) and parts 1.1 and 2 of
`Copilot_Completion_Check_v2_and_Cost_2026-10-29.md`. Part 1 of the
amendment (covered-point detail on the area line) and parts 1.2 to 1.5
and 3 of the v2 file stay, with `BEYOND_REACH_M = 5000`.

## 1. The specification in one paragraph

Per bin, the boundary is the farthest location F where the down cell was
seen, plus clean evidence beyond F. Clean evidence may be sampled. Every
activity location at or nearer than F in the bin is interior and must be
queried; nothing inside the boundary is sampled. Partial patterns exist to
find the boundary; the interior is counted in full.

## 2. Area state

Keep the state record of the partial-query instruction and the
covered-point fields of the amendment. Replace `resolved_extent`,
`beyond_with_sample` and `unqueried_within_extent` by:

```json
"boundary_m": 5600,
"inside_unqueried": 41,
"beyond_with_sample": 12,
"resolution": "open"
```

`boundary_m` is the bin's current F for this area (the farthest covered
distance among all areas in the bin, including this one); null when the
bin has no covered location. `inside_unqueried` counts unqueried
locations of the area at or nearer than `boundary_m`. `beyond_with_sample`
counts sampled locations of the area farther than `boundary_m`.

Resolution values:

| value | condition |
|---|---|
| `unqueried` | nothing queried |
| `open` | none of the below |
| `resolved_sample` | `covered == 0`, `with_sample >= N_MIN_SAMPLED` |
| `resolved_boundary` | `inside_unqueried == 0` and `beyond_with_sample >= N_MIN_SAMPLED` and no sampled location beyond `boundary_m` shows the down cell |
| `resolved_full` | `unqueried == 0` |

Precedence: full, boundary, sample, open, unqueried. An area entirely
nearer than F resolves only in full. An area entirely beyond F resolves by
sample or in full. An area straddling F resolves by boundary or in full.

When a query moves F outward, `boundary_m` and `inside_unqueried` are
recomputed for every area in the bin; areas can return from
`resolved_boundary` or `resolved_sample` to `open`. The list of open
items grows and never shrinks for that reason.

## 3. Patterns

The six patterns of the partial-query instruction and the amendment,
plus one:

| pattern | selection | legal when |
|---|---|---|
| `inside` | every unqueried location of the area at or nearer than `boundary_m` | `inside_unqueried > 0` |

`beyond` stays: the n unqueried locations just past `boundary_m`, legal
when the bin has a covered location. `near_edge`, `far_edge`, `sparse`,
`roadside` are legal on an area with no covered location and no interior
part. `all` is always legal. Rejection messages name the legal set.

## 4. The bin test

For each active-plus-margin bin, and for each unobserved bin as in part
1.3 of the v2 file:

1. F = farthest covered location in the bin, or none.
2. F within `EDGE_STRIP_M` of the active edge: `open_at_edge`, legal
   action expand.
3. Interior: every area with `inside_unqueried > 0` is an open item of
   kind `inside`.
4. Boundary: every activity area whose nearest location lies within
   `BEYOND_REACH_M = 5000` beyond F (or, with no F, within the activity
   reach of the site) must be `resolved_sample`, `resolved_boundary` or
   `resolved_full` with no covered location beyond F. Each that is not is
   an open item of kind `beyond`.
5. If any area beyond F shows the down cell, F moves outward and the test
   repeats from 2.
6. No open item of either kind: `closed`. All-missing evidence sets
   `closed_without_sample` as before.

The check passes when every tested bin is closed, at the cap, or
legacy-accepted.

## 5. Rendering

Area line, when the area has an interior part:

```
S07 village, 5.8 km NE, 140 locations, crossed by R02 (trunk)
    covered 3 at 5.4 to 5.6 km, RSRP -109 to -104 dBm; 41 unqueried inside the boundary; 12 sampled beyond, none covered
```

Open items, two kinds, listed inside items first within a bin:

```
Open (inside):  S07: 41 locations nearer than 5.6 km not queried. Legal: query_coverage S07 inside (41).
Open (beyond):  S09 at 7.4 km, unqueried, 31 locations. Legal: all (31), or near_edge / far_edge / sparse n>=10.
Open (beyond):  S07: 12 of 10 sampled beyond 5.6 km, none covered. Resolved once inside is done.
```

The progress block adds one line per open bin:
`N bin: 2 open items (1 inside, 1 beyond), minimum 51 locations to close`.
The minimum is the sum of `inside_unqueried` plus `N_MIN_SAMPLED` per
unresolved beyond area; it is a computed floor, not a recommendation.

## 6. Rule policy

R1 fetches the areas the check names, nearest first, up to four, with:

| item kind | setting A | setting B | setting C |
|---|---|---|---|
| inside | `inside` | `inside` | `inside` |
| beyond, area unqueried | `all` | `near_edge` n 20 | `near_edge` n 20 |
| beyond, area open, no coverage | `all` | `near_edge` n 20 | `near_edge` n 20 |
| beyond, bin has F, area straddles | `all` | `all` | `beyond` n 20 |

Setting names stay `all`, `near_edge`, `near_edge_extent`. Inside items
are taken before beyond items at equal distance.

## 7. Resource accounting

`run.json` records under `resources`:

| counter | source |
|---|---|
| `coverage_calls`, `coverage_locations` (by radius) | budget counter plus a call counter |
| `kpi_calls`, `kpi_cells`, `kpi_rows`, `kpi_query_ids` | client |
| `osm_calls` | client |
| `decision_calls` (model), `verifier_calls` | runner |
| `seconds`: `coverage`, `kpi`, `osm`, `decision`, `program`, `total` | the step spans |
| `calibrated_seconds` | counts times the unit costs of part 8, when a calibration file exists |

Caps: `max_query_locations` (binding), `max_kpi_calls` (new),
`max_time_seconds` (safety), rounds 40 as a guard. KPI cost is
client-measured wall time per call; `run.json` says so.

## 8. Unit costs and the cost line in the context

The timing probe (part 3 of the v2 file) writes `unit_costs.json`:

```json
{"measured_at": "...", "coverage_s_per_location": {"4": 1.1, "10": 1.3},
 "coverage_s_per_call": 0.4, "kpi_s_per_call": 25.0, "kpi_s_per_cell": 0.4,
 "osm_s_per_call": 9.0, "decision_s_per_call": 20.0}
```

When the file exists and `RENDER_COSTS = True`, the context gets:

- one line in the cached prefix:
  `Costs (measured): coverage 1.3 s per location at 10 m, 1.1 s at 4 m; KPI 25 s per call plus 0.4 s per cell; expansion 9 s.`
- an estimated time beside each open item's location count:
  `Legal: query_coverage S07 inside (41 locations, about 53 s)`.
- `budget` gains `seconds_used` and `seconds_limit`, already present as
  time.

`RENDER_COSTS` defaults to False until the probe has run. The rule policy
does not read costs. `run.json` records the unit-costs file used.

## 9. Tests

1. Area straddling F: `inside_unqueried` and `beyond_with_sample` right;
   `inside` selects exactly the inside locations; resolution becomes
   `resolved_boundary` only when inside is zero and ten clean beyond.
2. F moves outward after a beyond query finds coverage: an area that was
   `resolved_boundary` returns to `open` with a new `inside_unqueried`.
3. Bin test: areas at 7 and 9 km beyond F = 5.6 km are both named with
   reach 5 km; an area at 11 km is not.
4. Rendering: the lines of part 5, character for character.
5. Rules: each setting produces the row of part 6 on a fixture with one
   inside item and one beyond item.
6. Resources: all counters present; `calibrated_seconds` present only
   with a unit-costs file; `RENDER_COSTS` off renders no cost text.

## Question to answer with the report

The interior activity reach used when a bin has no F, so that the
"within the activity reach of the site" clause in part 4 names the right
constant.
