# Closure audit probe: a post-run test of what the check closed

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`: one
implementation, run the same way on a run directory of either core.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Builds on `Copilot_Completion_Check_v4_Per_Site_Bins_2026-10-31.md`
and `Copilot_Resource_Caps_and_Decision_Accounting_2026-10-31.md`. No
completion rule changes, no change to either decision core.

## Why

Runs that end complete still leave locations covered by the down cells
unqueried. The run cannot see them: its state says every bin is closed.
The audit is a program step after the run that samples unqueried
locations in every bin and queries them, at a fixed cost that is the
same for both cores and is not charged to the run. It estimates the miss
rate of the closures the check accepted, and on a capped run it also
estimates how much coverage lies in the bins still open.

## 1. Invocation and scope

A separate command, `audit_closure <run_dir> [--scan <file>]`, run after
a run has ended, for any end reason. It reads the run directory
(run.json, state, point records, geometry) and writes
`<run_dir>/audit.json` and one picture. It never modifies run.json, the
state, the step records or the point records, and it never changes the
run's end reason or resource counters. Its own calls and locations are
recorded in audit.json only.

If the run directory has no final state or no geometry, the command
fails with a message naming the missing file. No partial audit.

## 2. Constants

```
AUDIT_PER_BIN_IN_REACH = 10
AUDIT_PER_BIN_OUT_OF_REACH = 5
AUDIT_RADIUS_M = 10
```

## 3. Sampling, per (site, bin)

For every `site/index` key of the run, over the unqueried activity-area
locations whose bin for that site is the key's index:

- stratum `in_reach`: locations the check's domain covers. With a
  boundary F in the bin: farther than F and within `BEYOND_REACH_M` of
  it. Without a boundary: within the interior activity reach of the
  site, as the bin test defines it.
- stratum `out_of_reach`: the remaining unqueried activity-area
  locations in the wedge.

Select `AUDIT_PER_BIN_IN_REACH` from the first stratum and
`AUDIT_PER_BIN_OUT_OF_REACH` from the second with the existing `sparse`
selector restricted to the wedge and stratum (farthest-point sampling
seeded at the stratum's location nearest the site). Fewer when fewer
exist; zero when none. Same inputs give the same sample on two calls.

A location that lies in the wedge of two sites is sampled once and its
result is attributed to every site whose wedge contains it, as one
sample record updates every site's frame in v4 part 4.

## 4. Execution

One point-coverage call per (key, stratum) at `AUDIT_RADIUS_M`, through
the same client the run uses, with the same per-location record. A
transport failure stops the audit with the failure recorded in
audit.json and `complete: false`; no retry inside the audit.

Covered for site s: any cell of s at or above -110 dBm in the sample.
Hole: covered for some site and no backup cell at or above -110 dBm.

## 5. Per-bin record in audit.json

```json
"WTL03023/5": {
  "status_at_end": "closed",
  "closure_reason": "resolved_boundary",
  "boundary_m": 4100,
  "evidence_beyond_at_end": 11,
  "evidence_margin_m": 1850,
  "inside_unqueried_at_end": 0,
  "in_reach":     {"candidates": 212, "sampled": 10, "covered": 2, "holes": 1},
  "out_of_reach": {"candidates": 940, "sampled": 5,  "covered": 0, "holes": 0},
  "samples": [{"grid_id": "...", "stratum": "in_reach", "distance_m": 4620,
               "covered": true, "rsrp_dbm": -106, "hole": true}]
}
```

- `status_at_end`: `closed`, `open`, `closed_no_activity` or
  `unobserved`, from the final check record.
- `closure_reason`: the resolution the check closed on, or null.
- `evidence_beyond_at_end`: sampled locations beyond F in the bin at the
  end of the run, from the (area, site, bin) records.
- `evidence_margin_m`: over the unqueried in-reach locations of the bin,
  the largest distance from a location to its nearest queried location
  in the same bin, computed from the stored geometry before any audit
  query. It measures how far the run's evidence is from the locations
  it did not query.
- A closed bin with `inside_unqueried_at_end > 0` is recorded with
  `invariant_violation: true` and is still sampled.

## 6. Totals in audit.json

```json
"summary": {
  "run_end_reason": "complete_program_stop",
  "bins": {"closed": 31, "open": 0, "closed_no_activity": 12, "unobserved": 5},
  "closed_in_reach":   {"sampled": 290, "covered": 9, "holes": 3, "miss_rate": 0.031},
  "closed_out_of_reach": {"sampled": 140, "covered": 1, "holes": 0, "found_rate": 0.007},
  "open_in_reach":     {"sampled": 0, "covered": 0, "holes": 0, "found_rate": null},
  "by_closure_reason": {"resolved_boundary": {"sampled": 200, "covered": 8},
                        "resolved_sample": {"sampled": 90, "covered": 1}},
  "false_closure": true,
  "bins_with_false_closure": ["WTL03023/5"],
  "evidence_margin_m": {"median": 1200, "max": 3900},
  "audit_cost": {"calls": 74, "locations": 430, "seconds": 512}
}
```

- `miss_rate`: covered divided by sampled, closed bins, in-reach
  stratum. This is the soundness estimate of the check plus the
  evidence the core gave it.
- `found_rate` for open bins: on a capped run, the share of the open
  territory that still has coverage, the remaining work the run did
  not reach.
- `false_closure`: true when any closed bin has a covered in-reach
  sample.
- Rates are null, never 0, when `sampled` is 0.

## 7. Scan mode

With `--scan <file>`, the ground-truth scan of the case, each bin record
gains an `exact` block with the same four counts over every unqueried
location of the stratum, not a sample, using the same covered and hole
definitions, and `summary.exact` repeats the totals. The probe still
runs, so the sampled estimate and the exact count sit side by side and
the sample size can be judged. Locations the scan does not contain are
counted under `exact.not_in_scan` and are not inferred.

## 8. Picture

One picture, `audit_map`, in the run's window: the closed-bin wedges,
the run's queried locations in grey, the audit samples by stratum with
covered in the RSRP colour of the coverage map, holes marked, and a
margin line:

```
audit: closed bins 31 | in-reach sampled 290, covered 9, holes 3, miss rate 0.031 | false closure: WTL03023/5 | cost 430 locations
```

The picture code reads audit.json only.

## 9. Tests

1. Fixture: one closed bin resolved by boundary, with hidden coverage
   at 4.6 km beyond a 4.1 km boundary in the fixture's service stub.
   The audit samples the bin, reports `covered 2`, `miss_rate > 0`,
   `false_closure true` and names the bin.
2. Same fixture with no hidden coverage: `covered 0`, `miss_rate 0.0`,
   `false_closure false`.
3. The run directory's run.json, state, step records and point records
   are identical before and after the audit; audit.json and the picture
   are the only new files.
4. A capped run with open bins: open bins are sampled, labelled `open`,
   and counted under `open_in_reach`; `summary.run_end_reason` is
   `time_cap`.
5. Sampling: every sampled location lies in the key's wedge and
   stratum; two calls give the same sample; a stratum with 3
   candidates gives 3.
6. A closed bin with `inside_unqueried_at_end > 0` carries
   `invariant_violation true` and is sampled.
7. Scan mode on fixture 1: `exact.covered` equals the number of hidden
   covered locations in the stratum, and `exact.not_in_scan` counts a
   location removed from the scan file.
8. A transport failure on the third call leaves audit.json with
   `complete false`, the two finished bins recorded, and no picture.
9. `evidence_margin_m` on a fixture with one queried location and one
   unqueried in-reach location 1 850 m from it is 1850.

## Questions to answer with the report

1. Where the two packages can share the audit code without one
   importing the other's loop; if they cannot, say so and stop before
   duplicating it.
2. The audit cost on the largest synthetic fixture: calls, locations
   and seconds, so the fixed cost per run is known before it runs on a
   real case.
3. Whether the final check record stores the closure reason per
   `site/index`; if not, name the field the audit would need.
