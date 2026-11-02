# Closure audit probe: a post-run test of the territory a run never reached

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`: one
implementation, run the same way on a run directory of either core.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Builds on `Copilot_Completion_Check_v4_Per_Site_Bins_2026-10-31.md`
and `Copilot_Resource_Caps_and_Decision_Accounting_2026-10-31.md`. No
completion rule changes, no change to either decision core.

## Why

Runs leave locations covered by the down cells unqueried. Two kinds:
locations inside the run's final active area that its samples did not
hit, and locations outside the final active area that the run never
extended to. The first is sampling variance and is accepted: the check
is shared, no two runs sample the same locations, and the inside is
judged from its samples. The second is territory the core never asked
for, and it is where the cores differ: one may push the window outward,
the other may not. The audit measures the second kind only.

The audit is a program step after the run, at a fixed cost that is the
same for both cores and is not charged to the run.

## 1. Invocation and scope

A separate command, `audit_outside <run_dir> [--scan <file>]`, run
after a run has ended, for any end reason. It reads the run directory
(run.json, final state, point records, geometry) and writes
`<run_dir>/audit.json` and one picture. It never modifies run.json, the
state, the step records or the point records, and never changes the
run's end reason or resource counters. Its own calls and locations are
recorded in audit.json only.

If the run directory has no final state or no geometry, the command
fails with a message naming the missing file. No partial audit.

## 2. Constants

```
AUDIT_PER_BIN = 10
AUDIT_RADIUS_M = 10
AUDIT_REACH_M = 15000
```

`AUDIT_REACH_M` is the distance from each site out to which the audit
looks. It is the same for every run of a case and for both cores, so
the two audits test the same territory.

## 3. Candidates, per (site, bin)

For every `site/index` key of the run: the activity-area locations of
the case geometry (the full geometry, not the run's window) whose bin
for that site is the key's index, that lie outside the run's final
active area for that site, within `AUDIT_REACH_M` of the site, and that
the run never queried. Locations inside the final active area are never
candidates.

Record per bin the edge distance: the distance from the site to the
final active area edge in that wedge, from the final state.

A location in the wedges of two sites is sampled once; its result is
attributed to every site whose candidate set contains it.

## 4. Sampling

Select `AUDIT_PER_BIN` candidates with the existing `sparse` selector
restricted to the candidate set: the first pick is the candidate
nearest the site, each next pick is the candidate farthest from every
location already picked. Fewer when fewer exist; zero when none. Ties
break by ascending grid id; the same run directory gives the same
sample on two calls.

## 5. Execution

One point-coverage call per key at `AUDIT_RADIUS_M`, through the same
client the run uses, with the same per-location record. A transport
failure stops the audit with the failure recorded in audit.json and
`complete: false`; no retry inside the audit.

Covered for site s: any cell of s at or above -110 dBm in the sample.
Hole: covered for some site and no backup cell at or above -110 dBm.

## 6. Per-bin record in audit.json

```json
"WTL03023/5": {
  "status_at_end": "closed",
  "closure_reason": "resolved_boundary",
  "edge_m": 6000,
  "farthest_queried_m": 5400,
  "candidates": 940,
  "sampled": 10, "covered": 2, "holes": 1,
  "farthest_covered_past_edge_m": 2300,
  "samples": [{"grid_id": "...", "distance_m": 8300, "past_edge_m": 2300,
               "covered": true, "rsrp_dbm": -106, "hole": true}]
}
```

`status_at_end` and `closure_reason` come from the final check record
(`closed`, `open`, `closed_no_activity`, `unobserved`; reason or null).
`farthest_queried_m` is the run's farthest queried location in the
wedge, for the report only.

## 7. Totals in audit.json

```json
"summary": {
  "run_end_reason": "complete_program_stop",
  "bins": {"closed": 31, "open": 0, "closed_no_activity": 12, "unobserved": 5},
  "outside": {"candidates": 18200, "sampled": 430, "covered": 17, "holes": 6,
              "found_rate": 0.040},
  "outside_closed_bins": {"sampled": 290, "covered": 12, "holes": 4, "found_rate": 0.041},
  "outside_open_bins":   {"sampled": 140, "covered": 5,  "holes": 2, "found_rate": 0.036},
  "bins_with_coverage_outside": ["WTL03023/5", "WTL05870/2"],
  "farthest_covered_past_edge_m": {"median": 1400, "max": 4100},
  "audit_cost": {"calls": 48, "locations": 430, "seconds": 290}
}
```

- `found_rate`: covered divided by sampled. It is the share of the
  unreached territory that has coverage, the gap the run left.
- `bins_with_coverage_outside`: every bin with at least one covered
  sample; a closed bin in this list closed with coverage past its edge.
- Rates are null, never 0, when `sampled` is 0.

## 8. Scan mode

With `--scan <file>`, each bin record gains an `exact` block with the
same counts over every candidate of the bin, not a sample, using the
same covered and hole definitions, and `summary.exact` repeats the
totals. The probe still runs, so the sampled estimate and the exact
count sit side by side. Candidates the scan does not contain are
counted under `exact.not_in_scan` and are not inferred.

## 9. Picture

One picture, `audit_map`, in a window of `AUDIT_REACH_M` around the
sites: the final active area outline per site, the run's queried
locations in grey, the audit samples with covered in the RSRP colour of
the coverage map, holes marked, and a margin line:

```
audit outside: sampled 430, covered 17, holes 6, found rate 0.040 | coverage outside in 2 bins, farthest 4.1 km past edge | cost 430 locations
```

The picture code reads audit.json only.

## 10. Tests

1. Fixture: a closed bin with edge at 6 km and hidden coverage at 8.3 km
   in the service stub. The audit samples the bin, reports `covered 2`,
   `found_rate > 0`, and names the bin in `bins_with_coverage_outside`
   with `farthest_covered_past_edge_m` 2300.
2. Same fixture, no hidden coverage: `covered 0`, `found_rate 0.0`,
   empty list.
3. The run directory's run.json, state, step records and point records
   are identical before and after the audit; audit.json and the picture
   are the only new files.
4. No sampled location lies inside the final active area; every sampled
   location is in the key's wedge, within `AUDIT_REACH_M`, and
   unqueried by the run; two calls give the same sample; a bin with 3
   candidates gives 3.
5. A capped run with open bins: open bins are sampled and counted under
   `outside_open_bins`; `summary.run_end_reason` is `time_cap`.
6. Two runs of one case with different final active areas are audited
   over the same `AUDIT_REACH_M` territory: a location outside both
   windows is a candidate in both audits.
7. Scan mode on fixture 1: `exact.covered` equals the number of hidden
   covered candidates, and `exact.not_in_scan` counts a candidate
   removed from the scan file.
8. A transport failure on the third call leaves audit.json with
   `complete false`, the two finished bins recorded, and no picture.

## Questions to answer with the report

1. Where the final active area per site and wedge is stored in the
   final state (file and field), and whether the edge distance per bin
   can be read from it without recomputation.
2. The audit cost on the largest synthetic fixture: calls, locations,
   seconds, so the fixed cost per run is known before a real case.
3. Where the two packages can share the audit code without one
   importing the other's loop; if they cannot, say so and stop before
   duplicating it.
