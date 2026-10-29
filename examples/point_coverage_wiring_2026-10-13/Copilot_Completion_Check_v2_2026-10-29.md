# Completion check v2: boundary and interior, rule policy, cost

Apply to `outage_harness_langgraph` and `outage_harness_rule_based` only.
Synthetic fixtures and tests; no real cases. The timing probe in part 8
is the one exception: it calls the services with fixed inputs and the
author runs it. Report every change as file and line.

This is the single current specification after the partial-query change.
It builds on `Copilot_Partial_Area_Query_2026-10-28.md` and on part 1 of
`Copilot_Partial_Area_Query_Amendment_2026-10-28.md` (covered-point
detail on the area line). It replaces part 2 of that amendment
(resolution by extent, the `beyond` pattern is kept) and the whole of the
earlier v2 file. Where an earlier file disagrees with this one, this one
wins.

Why: on a case with a ground truth, the boundary check passed for the
rule run while areas the rule never queried are covered by the down cell
and contain coverage holes. The check closed directions on the nearest
area only, skipped unobserved directions, and let sampled evidence stand
in for the interior. v2 fixes the boundary test and counts the interior
in full; partial queries stay for finding the boundary.

```
CHECK_VERSION   = "v1" | "v2"      # recorded in run.json; v1 is the check as it is today
BEYOND_REACH_M  = 5000
N_MIN_SAMPLED   = 10
```

## 1. The specification in one paragraph

Per bin, the boundary is the farthest location F where the down cell was
seen, plus clean evidence beyond F. Clean evidence may be sampled. Every
activity location at or nearer than F in the bin is interior and must be
queried; nothing inside the boundary is sampled. Partial patterns exist to
find the boundary; the interior is counted in full.

## 2. Area state

Keep the state record of the partial-query instruction and the
covered-point fields of the amendment (`covered_distance_m`,
`covered_rsrp_dbm`, `farthest_covered_m`). Add:

```json
"boundary_m": 5600,
"inside_unqueried": 41,
"beyond_with_sample": 12,
"resolution": "open"
```

`boundary_m` is the bin's current F (the farthest covered distance among
all areas in the bin); null when the bin has no covered location.
`inside_unqueried` counts unqueried locations of the area at or nearer
than `boundary_m`. `beyond_with_sample` counts sampled locations of the
area farther than `boundary_m`.

| resolution | condition |
|---|---|
| `unqueried` | nothing queried |
| `open` | none of the below |
| `resolved_sample` | `covered == 0`, `with_sample >= N_MIN_SAMPLED` |
| `resolved_boundary` | `inside_unqueried == 0`, `beyond_with_sample >= N_MIN_SAMPLED`, no sampled location beyond `boundary_m` shows the down cell |
| `resolved_full` | `unqueried == 0` |

Precedence: full, boundary, sample, open, unqueried. An area entirely
nearer than F resolves only in full. An area entirely beyond F resolves by
sample or in full. An area straddling F resolves by boundary or in full.

When a query moves F outward, `boundary_m` and `inside_unqueried` are
recomputed for every area in the bin; areas can return from
`resolved_boundary` or `resolved_sample` to `open`. The open list grows
for that reason and never shrinks.

## 3. Patterns

The patterns of the partial-query instruction (`all`, `near_edge`,
`far_edge`, `sparse`, `roadside`), `beyond` from the amendment, plus one:

| pattern | selection | legal when |
|---|---|---|
| `inside` | every unqueried location of the area at or nearer than `boundary_m` | `inside_unqueried > 0` |
| `beyond` n | the n unqueried locations just past `boundary_m`, nearest first | the bin has a covered location |
| `near_edge`, `far_edge`, `sparse`, `roadside` n | as defined | the area has no covered location and no interior part |
| `all` | every unqueried location | always |

Rejection messages name the legal set for that area.

## 4. The bin test

For each active-plus-margin bin, and for each unobserved bin as in 4.1:

1. F = farthest covered location in the bin, or none.
2. F within `EDGE_STRIP_M` of the active edge: `open_at_edge`, legal
   action expand.
3. Interior: every area with `inside_unqueried > 0` is an open item of
   kind `inside`.
4. Boundary: every activity area whose nearest location lies within
   `BEYOND_REACH_M` beyond F (with no F: within the interior activity
   reach of the site) must be `resolved_sample`, `resolved_boundary` or
   `resolved_full` with no covered location beyond F. Each that is not is
   an open item of kind `beyond`. This replaces the v1 rule that tested
   the nearest area only.
5. If any area beyond F shows the down cell, F moves outward and the test
   repeats from 2.
6. No open item of either kind: `closed`. All-missing evidence sets
   `closed_without_sample` as before.

The check passes when every tested bin is closed, at the cap, or
legacy-accepted.

### 4.1 Unobserved bins block

A bin where neither ring probe returned a sample is today reported and not
tested. In v2: the nearest activity area in the bin within
`OBSERVED_RADIUS_M` (2 000 m) must be `resolved_sample` or
`resolved_full` with no covered location; then the bin is `closed`. With
no activity area within that radius the bin is `closed_no_activity`,
reported, not blocking. If the area shows the down cell, the bin becomes
active and takes the test of part 4.

## 5. Rendering

Area line, when the area has an interior part:

```
S07 village, 5.8 km NE, 140 locations, crossed by R02 (trunk)
    covered 3 at 5.4 to 5.6 km, RSRP -109 to -104 dBm; 41 unqueried inside the boundary; 12 sampled beyond, none covered
```

Open items, two kinds, inside items first within a bin:

```
Open (inside):  S07: 41 locations nearer than 5.6 km not queried. Legal: query_coverage S07 inside (41).
Open (beyond):  S09 at 7.4 km, unqueried, 31 locations. Legal: all (31), or near_edge / far_edge / sparse n>=10.
Open (beyond):  S07: 12 of 10 sampled beyond 5.6 km, none covered. Resolved once inside is done.
```

The progress block adds one line per open bin:
`N bin: 2 open items (1 inside, 1 beyond), minimum 51 locations to close`.
The minimum is the sum of `inside_unqueried` plus `N_MIN_SAMPLED` per
unresolved beyond area: a computed floor, not a recommendation.

## 6. Rule policy

The setting is fixed before the run (`RULE_PATTERN` = `all`, `near_edge`
or `near_edge_extent`, called A, B, C below) and recorded in `run.json`.
Each round, the rule runs this procedure and nothing else:

```
N = 2 * N_MIN_SAMPLED

items = open items from the check, sorted by the area's distance from the
        site, nearest first; inside before beyond at equal distance
take the first MAX_REQUESTS_PER_ACTION items
for each item:
    if item.kind == "inside":
        pattern = inside
    else:                                   # item.kind == "beyond"
        if SETTING == A:
            pattern = all
        elif SETTING == B:
            if area.covered > 0:   pattern = all
            else:                  pattern = near_edge, n = min(N, area.unqueried)
        elif SETTING == C:
            if area.covered == 0:  pattern = near_edge, n = min(N, area.unqueried)
            elif unqueried locations exist beyond boundary_m:
                                   pattern = beyond, n = min(N, that count)
            else:                  pattern = all
        if pattern is not all and n < N_MIN_SAMPLED:  pattern = all
    radius = 10
send one query_coverage action with those requests
```

The rule reads the item kind, `covered`, `unqueried` and the count beyond
the boundary. It never reads the budget, RSRP, area size, sample rate or
costs; never queries an area the check did not name; never changes the
radius. R2 (expand), R3 (KPI batch) and R4 (finish) are unchanged.

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

The point coverage service is an API; KPI is a Snowflake query whose
history the run's role cannot read, so `kpi_seconds` is client-measured
wall time per call and `run.json` says so. The `query_id` is recorded
anyway for later attribution by a role that can read the history.

Caps: `max_query_locations` (binding), `max_kpi_calls` (new),
`max_time_seconds` (safety), rounds 40 as a guard.

## 8. Timing probe and the cost line in the context

A script that calls the services with fixed synthetic inputs and records
latency. It makes no decision and writes no run. Copilot writes it; the
author runs it three times at different hours.

- 60 point coverage calls at 10 m and 60 at 4 m, on fixed grid ids near
  the test site, sequential: record each latency.
- 3 KPI calls: 1 cell, 10 cells, 30 cells, one technology, the standard
  8-week window: record latency, rows and `query_id`.
- 1 OSM request for a 4 km square: record latency.
- Output: a CSV with one row per call, a summary of median and 90th
  percentile per call type, and `unit_costs.json`:

```json
{"measured_at": "...", "coverage_s_per_location": {"4": 1.1, "10": 1.3},
 "coverage_s_per_call": 0.4, "kpi_s_per_call": 25.0, "kpi_s_per_cell": 0.4,
 "osm_s_per_call": 9.0, "decision_s_per_call": 20.0}
```

When the file exists and `RENDER_COSTS = True`, the context gets one line
in the cached prefix,
`Costs (measured): coverage 1.3 s per location at 10 m, 1.1 s at 4 m; KPI 25 s per call plus 0.4 s per cell; expansion 9 s.`,
and an estimated time beside each open item's location count,
`Legal: query_coverage S07 inside (41 locations, about 53 s)`.
`RENDER_COSTS` defaults to False until the probe has run. The rule policy
does not read costs. `run.json` records the unit-costs file used.

## 9. Tests

1. Area straddling F: `inside_unqueried` and `beyond_with_sample` right;
   `inside` selects exactly the inside locations; resolution becomes
   `resolved_boundary` only when inside is zero and ten clean beyond.
2. F moves outward after a beyond query finds coverage: an area that was
   `resolved_boundary` returns to `open` with a new `inside_unqueried`.
3. Bin test: areas at 7 and 9 km beyond F = 5.6 km are both named with
   reach 5 km; an area at 11 km is not. Under v1 only the 7 km area is
   named.
4. Unobserved bin with a village at 1.5 km: v1 ignores it; v2 names it;
   after a clean sample resolution the bin is closed; with no activity
   area the bin is `closed_no_activity`.
5. Rendering: the lines of part 5, character for character.
6. Rules: each setting produces the pattern of part 6 on a fixture with
   one inside item and one beyond item; the fallback to `all` fires when
   fewer than ten locations remain.
7. Resources: all counters present; `calibrated_seconds` present only
   with a unit-costs file; `RENDER_COSTS` off renders no cost text.
8. `run.json` records `CHECK_VERSION`, `BEYOND_REACH_M`, `RULE_PATTERN`.

## Question to answer with the report

The interior activity reach used when a bin has no F, so that the clause
in part 4 step 4 names the right constant.
