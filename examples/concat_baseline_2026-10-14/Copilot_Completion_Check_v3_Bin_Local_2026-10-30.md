# Completion check v3: bin-local evidence

Apply to `outage_harness_langgraph` and `outage_harness_rule_based` only.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. This amends `Copilot_Completion_Check_v2_2026-10-29.md`; where
the two disagree, this file wins. `CHECK_VERSION` gains the value `"v3"`.

## Why

A rule run ended `complete_program_stop` while 123 locations covered by
the down cell were never queried (R02 31, R06 10, R08 82). Cause: the v2
state record computes `beyond_with_sample`, `inside_unqueried` and
`resolution` once per area, and the bin test accepts that area-wide
status in every bin the area crosses. R08 had 16 clean samples beyond the
boundary in bin 0 and none in bin 5, with 205 locations unqueried beyond
bin 5's boundary; bin 5 closed on bin 0's evidence.

Closure is a property of a bin. Every count the bin test reads must be
computed from locations inside that bin.

## 1. Location to bin

Every location has one bin: the 30 degree sector of its bearing from the
site. A location belongs to exactly one bin; margin bins do not widen the
wedge for this purpose. Store `bin` on every point record and on every
geometry location, computed once at initialization and at expansion.

## 2. Area state is per (area, bin)

For every area and every bin the area has locations in, keep one record:

```json
"R08": {
  "locations_total": 310, "queried": 96, "with_sample": 71, "covered": 12,
  "bins": {
    "0": {"locations": 120, "queried": 80, "with_sample": 61, "covered": 12,
          "farthest_covered_m": 4100, "boundary_m": 4100,
          "inside_unqueried": 0, "beyond_with_sample": 16, "covered_beyond": 0,
          "resolution": "resolved_boundary"},
    "5": {"locations": 190, "queried": 16, "with_sample": 10, "covered": 0,
          "farthest_covered_m": null, "boundary_m": 3300,
          "inside_unqueried": 0, "beyond_with_sample": 0, "covered_beyond": 0,
          "unqueried_beyond": 205, "resolution": "open"}
  }
}
```

The area-level counts stay for the area line and `run.json`; they are
never read by the bin test. Per bin:

- `boundary_m` is that bin's F (farthest covered location among all
  areas in that bin).
- `inside_unqueried`: unqueried locations of the area in that bin at or
  nearer than `boundary_m`.
- `beyond_with_sample`: sampled locations of the area in that bin farther
  than `boundary_m`.
- `covered_beyond`: of those, the ones showing the down cell (must be 0
  for closure; if above 0, F moves).
- `unqueried_beyond`: unqueried locations of the area in that bin farther
  than `boundary_m`.
- `resolution` by the v2 table, evaluated on the bin-local counts only.
  `resolved_sample` needs `with_sample >= N_MIN_SAMPLED` in that bin and
  `covered == 0` in that bin.

An area crossing k bins therefore has k resolutions. "R08 resolved" is
not a statement the code can make; "R08 resolved in bin 0" is.

## 3. The bin test reads bin-local records only

Part 4 of v2 is unchanged in wording, with one substitution throughout:
wherever it reads an area's `inside_unqueried`, `beyond_with_sample`,
`covered` beyond F, or `resolution`, it reads the (area, bin) record of
the bin under test. The reach test in step 4 uses the nearest location of
the area that lies in the bin.

The unobserved-bin rule (4.1) likewise reads the (area, bin) record.

## 4. Open items name the bin

Every open item is (bin, area, kind). The same area can appear under
several bins. Rendering:

```
Open (beyond), bin 5 (150-180 deg): R08: 0 of 10 sampled beyond 3.3 km; 205 unqueried beyond. Legal: query_coverage R08 beyond bin=5 n>=10, or all.
Open (beyond), bin 0 (0-30 deg):    R08: 16 of 10 sampled beyond 4.1 km, none covered. Resolved in this bin.
```

The progress line per bin ("minimum N locations to close") sums the
bin-local counts.

## 5. Requests carry the bin for `inside` and `beyond`

`inside` and `beyond` requests take a required `bin` field (the bin index
0 to 11, as shown in the open item). Selection is restricted to the
area's locations in that bin: `inside` takes every unqueried location in
the bin at or nearer than the bin's `boundary_m`; `beyond` takes the n
unqueried locations in the bin just past it, nearest first. A request
without `bin`, or with a bin the area has no locations in, is rejected
with a message that lists the bins the area crosses.

`all`, `near_edge`, `far_edge`, `sparse` and `roadside` stay area-wide
and keep their v2 legality rules, evaluated on the area-level counts.

Rule policy (v2 part 6): the item carries the bin, and the rule passes it
through. No other change.

## 6. Invariant at end_run

On every run that ends `complete` or `complete_program_stop`, end_run
asserts, for every bin that is `closed`:

- `inside_unqueried == 0` for every area in the bin;
- for every area within reach beyond F in the bin, either
  `beyond_with_sample >= N_MIN_SAMPLED` with `covered_beyond == 0` in that
  bin, or `resolution == resolved_full` for that bin, or `resolved_sample`
  on that bin's counts.

If the assertion fails, the run does not end complete: `end_reason` is
`completion_invariant_failed`, the failing bins and areas are written to
`run.json`, and the report is still produced. No fallback to a cap
reason.

`run.json` records, per closed bin, the evidence it closed on: the
sampled location ids beyond F in that bin.

## 7. Tests

1. One corridor across bins 0 and 5. Sixteen clean sampled locations
   beyond F in bin 0, none in bin 5, 205 unqueried beyond in bin 5. Bin 0
   closes, bin 5 stays open with one `beyond` item naming bin 5, and
   finish is refused.
2. Same fixture, then ten clean samples beyond F in bin 5: bin 5 closes.
3. Same fixture, then one covered location beyond F in bin 5: bin 5's F
   moves, `inside_unqueried` in bin 5 recomputes, the item becomes
   `inside`.
4. `resolved_sample` pooling: a settlement across two bins with ten clean
   samples in one bin only is `resolved_sample` in that bin and `open` in
   the other.
5. A `beyond` request without `bin`, and one with a bin the area does
   not cross, are rejected with the listing message.
6. The invariant: a state hand-built with a closed bin and zero bin-local
   evidence makes end_run end with `completion_invariant_failed`, with the
   bin and area named in `run.json`.
7. Rule policy: on fixture 1 the rule proposes `beyond` on R08 with
   `bin=5`.

## Questions to answer with the report

1. Where the bearing of a location is computed today (file and line), and
   whether the same function serves the ring probe, the direction records
   and this change.
2. The number of (area, bin) records on the largest synthetic fixture,
   to confirm the rendered area lines stay within the context size you
   report.
