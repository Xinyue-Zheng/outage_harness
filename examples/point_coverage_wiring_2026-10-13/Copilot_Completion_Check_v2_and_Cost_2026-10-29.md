# Completion check v2 and resource accounting

Apply to `outage_harness_langgraph` and `outage_harness_rule_based` only.
Synthetic fixtures and tests; no real cases. The timing probe in part 3
is the one exception: it calls the services with fixed inputs and the
author runs it. Report every change as file and line.

Why: on a case with a ground truth, the boundary check passed for the
rule run while areas the rule never queried are covered by the down cell
and contain coverage holes. The check closed directions on evidence that
did not cover the areas it judged. This file tightens the check and makes
its strictness a setting, so the cost of strictness can be measured.

## 1. Completion check v2

One constant selects the version, so both cores run under the same check
and both versions can be compared on the same case:

```
CHECK_VERSION = "v1" | "v2"      # recorded in run.json
```

v1 is the check as it is today. v2 changes four things.

### 1.1 Sampled evidence must cover the area

Today an area resolves by sample when ten queried locations returned
samples and none shows the down cell, wherever those ten lie. In v2 add a
spatial condition:

```
SAMPLE_COVER_M = 300
```

An area resolves by sample only when, in addition, every unqueried
location of the area lies within `SAMPLE_COVER_M` of a queried location
that returned a sample. A location that returned no sample covers
nothing.

The area state record gets `uncovered_by_samples`: the number of
unqueried locations farther than `SAMPLE_COVER_M` from any sampled
location. Zero is the condition. The area line shows it when the area is
open and `covered == 0`:

```
S09 hamlet, 7.4 km N, 31 locations
    queried 10 (near_edge), with sample 8, covered 0, open: 14 locations not within 300 m of a sample
```

The open item lists, as before, the legal actions; `sparse` is the one
that reduces this number fastest, but the line does not say so.

### 1.2 Extent evidence must cover the part beyond

Resolution by extent keeps its ten-clean-samples condition and adds the
same spatial condition applied to the part of the area beyond the
farthest covered location: every unqueried location beyond
`farthest_covered_m` lies within `SAMPLE_COVER_M` of a sampled location.
`unqueried_within_extent` stays reported as the undercount of the part
before.

### 1.3 Every area within reach beyond is required, not only the nearest

Today the bin test names only the nearest activity area beyond the
farthest covered location F; once it resolves clean, the bin closes. In
v2:

```
BEYOND_REACH_M = 3000
```

A bin closes only when every activity area in the bin whose nearest
location lies within `BEYOND_REACH_M` beyond F is resolved and shows no
down cell. If any of them shows the down cell, F moves to its farthest
covered location and the test repeats. The open item for the bin lists all
such areas, nearest first, with their unqueried counts. An area that is
all-missing after a full query still counts as resolved and still sets
`closed_without_sample` when it is the last evidence.

### 1.4 Unobserved bins block

A bin where neither ring probe returned a sample is today reported and
not tested. In v2 it is tested like this: the nearest activity area in
the bin within `OBSERVED_RADIUS_M` (2 000 m) must be resolved by sample or
in full and show no down cell; then the bin is `closed`. If the bin has no
activity area within that radius, it is `closed_no_activity`, reported,
not blocking. If the area shows the down cell, the bin becomes active and
takes the ordinary test from 1.3.

### 1.5 Rule policy under v2

R1 is unchanged in form: it fetches the areas the check names, nearest
first, up to four, with the setting's pattern. Two additions:

- An area that is open with `uncovered_by_samples > 0` and `covered == 0`
  gets `sparse`, n = max(N_MIN_SAMPLED, ceil(uncovered_by_samples / 4)),
  in settings B and C. Setting A stays `all`.
- Unobserved bins (1.4) are named by the check, so R1 reaches them with no
  new rule.

### 1.6 Tests

1. A 2 km by 1 km area, ten near-edge samples clean: v1 resolves, v2 stays
   open with the right `uncovered_by_samples`; after `sparse` with enough
   samples, v2 resolves.
2. A bin with areas A (clean), B (covered) within 3 km beyond F: v1 closes
   after A; v2 names B, and after B is queried moves F outward.
3. An unobserved bin with a village at 1.5 km: v1 ignores it; v2 names it;
   after a clean sample resolution the bin is closed; with no activity
   area the bin is `closed_no_activity`.
4. `run.json` records `CHECK_VERSION`, and the three constants.

## 2. Resource accounting

Every run records, in `run.json` under `resources`, four counters. The
caps use the first two; time is a safety cap.

| counter | definition | source |
|---|---|---|
| `coverage_locations` | locations sent to the point coverage service | the existing budget counter |
| `kpi_warehouse_seconds` | sum over KPI calls of the warehouse execution time of the query | see 2.1 |
| `kpi_calls`, `kpi_rows` | number of KPI calls and rows returned | client |
| `time` | wall time split by node class: `service` (execute_query and initialization calls), `decision` (model calls and verifier), `program` (everything else), and `total` | the step spans already recorded |

### 2.1 Warehouse cost of a KPI query

Snowflake does not bill per query; it bills warehouse time. Attribute it
per query as follows. The client records the `query_id` returned for every
KPI query. At end of run, or in a separate script run later, read for
each id from the query history view (`INFORMATION_SCHEMA.QUERY_HISTORY`
for the last 7 days, or `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` if the
role has access): `TOTAL_ELAPSED_TIME`, `EXECUTION_TIME`, `BYTES_SCANNED`,
`WAREHOUSE_SIZE`. Define:

```
kpi_warehouse_seconds = sum(EXECUTION_TIME) / 1000
kpi_credits_estimate  = kpi_warehouse_seconds * credits_per_hour(WAREHOUSE_SIZE) / 3600
```

Store both per query and in total. If the history view is not readable,
store `EXECUTION_TIME` from the client's own timing of the call and say
in `run.json` that it is client-measured. Do not query the history view
during a run.

If the point coverage service is also a Snowflake query, record its
`query_id` the same way and report `coverage_warehouse_seconds` beside
`coverage_locations`. If it is an API, locations and calls are its cost.

### 2.2 Caps

```
max_query_locations        (points, binding budget)
max_kpi_warehouse_seconds  (new; None until the timing probe gives a scale)
max_time_seconds           (total wall time, safety)
```

The round cap stays as a guard only, set high (40).

## 3. Timing probe

A script that calls the services with fixed synthetic inputs and records
latency. It makes no decision and writes no run. Copilot writes it; the
author runs it three times at different hours.

- 60 point coverage calls at 10 m and 60 at 4 m, on fixed grid ids near
  the test site, one call each, sequential: record each latency.
- 3 KPI calls: 1 cell, 10 cells, 30 cells, one technology, the standard
  8-week window: record latency and `query_id`, then the history fields
  of 2.1.
- 1 OSM request for a 4 km square: record latency.
- Output: a CSV with one row per call and a summary of median and 90th
  percentile per call type.

With the probe's numbers and one rule run's counts, the time of any run
decomposes into service time (count times latency) and decision time (the
rest), and `max_kpi_warehouse_seconds` can be set to a multiple of the
30-cell call.

## Questions to answer with the report

1. Whether the point coverage service is a Snowflake query or an API, and
   whether the client sees a `query_id`.
2. Which role the run uses, and whether it can read the query history
   view.
3. The current value of the activity reach used by the interior test, so
   that `BEYOND_REACH_M` can be set consistently with it.
