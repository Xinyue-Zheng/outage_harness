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

v1 is the check as it is today. v2 changes the boundary test in two places and adds one optional switch.

### 1.1 Resolution by sample and by extent are unchanged

An area still resolves by sample with ten sampled locations and no down
cell, wherever they lie, and by extent with ten clean sampled locations
past the farthest covered point. Partial querying stays partial. The
far-side blind spot of a near-edge sample therefore remains, by decision;
the evaluation reports it as false closure against the ground truth, and
it is the cost of the partial policy, not a defect to hide.

One optional switch, default off, for the strictness curve:

```
SAMPLE_TWO_HALVES = False
```

When on, the ten samples must include at least three from the far half of
the area (locations farther from the site than the area's median
distance). Near-edge alone cannot resolve an area; near-edge plus far-edge
or sparse can. It never requires the whole area.

### 1.2 The boundary test names every area within reach beyond, not only the nearest

Today the bin test names only the nearest activity area beyond the
farthest covered location F; once it resolves clean, the bin closes. In
v2:

```
BEYOND_REACH_M = 5000
```

A bin closes only when every activity area in the bin whose nearest
location lies within `BEYOND_REACH_M` beyond F is resolved and shows no
down cell. If any of them shows the down cell, F moves to its farthest
covered location and the test repeats. The open item for the bin lists all
such areas, nearest first, with their unqueried counts. An area that is
all-missing after a full query still counts as resolved and still sets
`closed_without_sample` when it is the last evidence.

### 1.3 Unobserved bins block

A bin where neither ring probe returned a sample is today reported and
not tested. In v2 it is tested like this: the nearest activity area in
the bin within `OBSERVED_RADIUS_M` (2 000 m) must be resolved by sample or
in full and show no down cell; then the bin is `closed`. If the bin has no
activity area within that radius, it is `closed_no_activity`, reported,
not blocking. If the area shows the down cell, the bin becomes active and
takes the ordinary test from 1.2.

### 1.4 Rule policy under v2

R1 is unchanged: it fetches the areas the check names, nearest first, up
to four, with the setting's pattern. The areas named under 1.2 and 1.3
reach it with no new rule. With `SAMPLE_TWO_HALVES` on, settings B and C
use `far_edge` n = N_MIN_SAMPLED on an area whose samples lack the far
half.

### 1.5 Tests

1. With `SAMPLE_TWO_HALVES` on, ten near-edge samples clean leave the area
   open; three far-half samples added resolve it. With the switch off it
   resolves as in v1.
2. A bin with areas A (clean), B (covered) within 5 km beyond F: v1 closes
   after A; v2 names B, and after B is queried moves F outward.
3. An unobserved bin with a village at 1.5 km: v1 ignores it; v2 names it;
   after a clean sample resolution the bin is closed; with no activity
   area the bin is `closed_no_activity`.
4. `run.json` records `CHECK_VERSION`, `BEYOND_REACH_M` and `SAMPLE_TWO_HALVES`.

## 2. Resource accounting

The point coverage service is an API; KPI is a Snowflake query whose
history the run's role cannot read. Every run records, in `run.json`
under `resources`:

| counter | definition | source |
|---|---|---|
| `coverage_calls`, `coverage_locations` | point coverage API calls and locations sent | the existing budget counter plus a call counter |
| `coverage_seconds` | wall time inside coverage calls | client timing |
| `kpi_calls`, `kpi_cells`, `kpi_rows` | KPI calls, cells named, rows returned | client |
| `kpi_seconds` | wall time from sending the KPI query to receiving the last row, per call and in total | client timing |
| `time` | wall time by node class: `service` (coverage, KPI, OSM, initialization), `decision` (model calls and verifier), `program` (everything else), `total` | the step spans already recorded |

`kpi_seconds` is the cost of a KPI query for this work: without the
history view, the time the warehouse is busy for this call is not
separable from queueing, so the client's wall time is the number, and
`run.json` says it is client-measured. Record the `query_id` from the
cursor anyway, so the warehouse time can be attributed later by a role
that can read the history.

### 2.1 Caps

```
max_query_locations   (binding budget, as today)
max_kpi_calls         (new; a count, since warehouse time is not readable)
max_time_seconds      (total wall time, safety)
```

The round cap stays as a guard only, set high (40).

## 3. Timing probe

A script that calls the services with fixed synthetic inputs and records
latency. It makes no decision and writes no run. Copilot writes it; the
author runs it three times at different hours.

- 60 point coverage calls at 10 m and 60 at 4 m, on fixed grid ids near
  the test site, one call each, sequential: record each latency.
- 3 KPI calls: 1 cell, 10 cells, 30 cells, one technology, the standard
  8-week window: record latency, rows and `query_id`.
- 1 OSM request for a 4 km square: record latency.
- Output: a CSV with one row per call and a summary of median and 90th
  percentile per call type.

With the probe's numbers and one rule run's counts, the time of any run
decomposes into service time (count times latency) and decision time (the
rest), and `max_kpi_warehouse_seconds` can be set to a multiple of the
30-cell call.

## Question to answer with the report

The current value of the activity reach used by the interior test, so
that `BEYOND_REACH_M` is set consistently with it.
