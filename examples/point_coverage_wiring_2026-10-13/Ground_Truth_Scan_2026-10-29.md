# Ground truth by point scan: the full process (instruction for the Copilot)

This replaces the earlier ground-truth instruction in full. It keeps the
KPI steps and the report; it replaces every fetch step with a point scan
of the square. No heatmap, no OpenStreetMap query, no area derivation.

Build `make_ground_truth.py` in `outage_harness_langgraph`, run as

```
python -m outage_harness_langgraph.make_ground_truth --ticket <ticket id or JSON> --out <results root>/ground_truth
```

It is a measurement script: no language model, no verifier, no decision
loop; the only rules are the fixed numbers in the table below. Every
number it writes comes from a tool result or from a file an earlier step
wrote; where a result is absent the field is `not recorded`, never a
guess. The script is deterministic for a given set of tool results and
writes a `README.md` with the command, the constants, the calls made and
the counts per step. Function paths in angle brackets are placeholders the
author fills before you start; stop and ask if one is still a placeholder.

### Point calls: parallel, short timeout, cached per site

The scan and the refinement are about 1,300 point calls per site. They
run through `point_coverage.fetch_area_points`, which is changed once, for
the ground-truth script and the investigation packages alike:

- `POINT_WORKERS = 8`: the calls of one fetch run on a thread pool of
  eight (`fetch_area_points` already has the pool; set the constant and
  use it as the default). Lower it if the API returns rate-limit errors.
- `POINT_TIMEOUT_S = (10, 60)` in `point_by_point_cover.py` instead of
  `(15, 300)`; a call is retried twice (`POINT_RETRIES = 2`) and then
  recorded as an error point; the fetch continues.
- A per-site cache, one append-only file `<results root>/<site>/point_cache.jsonl`,
  one line per fetched point keyed by `grid_id|radius_m|epoch` (the epoch
  is the outage start date). `fetch_area_points` reads it before calling
  and appends to it after; a break in the scan therefore costs only the
  uncached remainder on the rerun, and an investigation run of the same
  site reuses the scan's points. The result summary counts `cache_hits`
  and `api_calls` separately; `calls.json` reports both.

The script's steps are restartable: each writes its output files when
complete, and on rerun a step whose outputs exist is skipped;
`--restart` deletes them. No OSM call and no heatmap call exist in this
process, so nothing else is cached.

The product is a directory `<out>/<site>_<window>/` with `scan.json`,
`outage_set.json`, `kpi_availability.json`, `refinement.json`,
`cells_seen.json`, `reference_extent.json`, `kpi_outage_hours.json`,
`ground_truth.json`, `ground_truth_report.md`, the figures, `calls.json`
and `README.md`.

Fixed numbers, all in one place at the top of the script:

| name | value | used in |
|---|---|---|
| `SQUARE_KM` | 30, centred on the site; inside the 60 km frame | step 1 |
| `SCAN_SPACING_M` | 1,000 | step 1 |
| `SCAN_RADIUS_M` | 100 | steps 1, 4 |
| `REFINE_SPACING_M` | 500 | step 4 |
| `REFINE_BLOCK_M` | 2,000: the square around a hit that is refined | step 4 |
| `EDGE_BAND_KM` | 5: the outer band of the square that must hold no hit | step 3 |
| `DOWN_MIN_HOURS` | 3; a ticket whose interval is shorter is dropped | step 2 |
| `DOWN_MAX_HOURS` | 24; a cell down longer is a long outage, not this kind of case | step 2 |
| `KPI_MONTH_DAYS` | 30 before the ticket start, 1 after its end | step 2 |
| `KPI_MIN_ROW_SHARE` | 0.5: a cell with rows for fewer than half the month's hours has no usable KPI | steps 2, 5, 6 |
| `BASELINE_MIN_SAMPLES` | 2 of the 4 same-weekday-hour samples | step 6 |
| `COVERAGE_RSRP_DBM` | -110 | steps 3 to 6 (the same constant the investigation code uses) |
| `LOAD_LIMIT_PERCENT` | 80 | step 6 (the same constant the investigation code uses) |
| `SIGNAL_MARGIN_DB`, `SERVICE_RSRP_DBM` | 10, -110 | step 6 (the same constants the investigation code uses) |

Every scan and refinement point is a cell of the 100 m frame grid (the
nearest cell centre to the lattice point), so the point cache is shared
with the investigation runs of the same site.

---

## Step 1. The scan

Reads: the site metadata (`<path>.query_basic_information`) for the site
position; the 60 km frame laid as the investigation code lays it
(`state0`'s frame constants), with the site at the centre.

Decides: the scan lattice, `SCAN_SPACING_M` in both directions over the
`SQUARE_KM` square, 31 by 31 points; one point call per lattice point
with `SCAN_RADIUS_M`. Every cell listed in any sample, with its RSRP, is
recorded per point. Points with no sample are recorded as such.

Writes: `scan.json`: per lattice point its grid id, the samples' cells
with RSRP or `no_sample`; `cells_seen.json` (first version): every cell
seen, where, and its technology (step 2c's pattern).

Functions: `point_coverage.fetch_area_points` with `grid_ids` (the
lattice), the cache, `POINT_WORKERS` in parallel; a new helper
`scan_lattice(geometry, square_km, spacing_m) -> list[str]`.

## Step 2. Who was down, and when

Reads: the ticket names a site id; the cells of that site are every cell
whose id starts with the site id, among the cells the scan (step 1) saw.
Every other cell the scan saw is a candidate. For every cell of the site
and every candidate cell, the hourly KPI (RRC, PRB) over one month: from 30 days before the ticket's start to 24
hours after its end. One month is what separates a real outage from a
cell whose RRC goes to zero every night or every weekend.

Decides, per cell:

- the runs of consecutive hours with RRC equal to zero or no row returned,
  over the whole month;
- a cell with such runs at the same weekday and hours in other weeks of
  the month is a regular zero, not an outage, for those hours (flagged
  `regular_zero`, excluded from the outage set);
- a run of at least `DOWN_MIN_HOURS` and at most `DOWN_MAX_HOURS` hours
  that overlaps the ticket interval, and is not a regular zero, makes the
  cell down for that run: this is the kind of outage the case is about,
  hours to one day;
- a cell whose zero run is longer than `DOWN_MAX_HOURS`, or that is at
  zero through most of the month, is a long outage (flagged
  `long_outage`): excluded from the outage set and from the backups, since
  it was not serving before the outage either;
- a cell of the site with no qualifying run is `site_up` (flagged):
  excluded from the outage set, but a backup like any other cell of its
  technology, flagged `same_site` in the backup tables. A surviving sector
  of the outage site serves normally and takes traffic; the radio rule in
  `radio.eligible_backup_cells`, which excludes every cell matching the
  outage prefix, must be changed in all packages to exclude only the cells
  of the confirmed outage set (the task's `outage_cell_ids`), not the
  whole site;
- a ticket whose own interval is shorter than `DOWN_MIN_HOURS` is dropped
  before any query (flagged `ticket_too_short`, no directory written);
- a cell whose RRC is zero through the month is idle (flagged, excluded).

The outage set is the site's cells with a qualifying run plus every
candidate found down for a qualifying run. A ticket whose site has no cell
with a qualifying run is dropped (flagged `no_short_outage`, no directory
written): the case is either not an outage or a long one, and neither is
what the comparison is about. The outage interval
is the intersection of the outage set's down runs. If the runs do not
overlap, the case is flagged `staggered`, the interval is the longest
single run, and step 7 draws every outage-set and candidate cell's RRC and
PRB over the month as one figure (`kpi_month.png`, one panel per cell,
the ticket interval and each down run marked) so the reviewer can see
what happened.

Writes: `outage_set.json`: per cell the hourly RRC and PRB over the month,
its runs, the verdict (down, site_up, long_outage, idle, regular_zero,
up); the confirmed outage set; the derived interval; the flags
(no_short_outage; candidate down beyond the ticket; long_outage; idle;
regular_zero; staggered).

Functions: `<path>.query_lte_rrc_prb`, `<path>.query_nr_rrc_prb` over the
month window (the KPI calls with a window inside the outage are yours to
supply); routing by id pattern from `policy.route_kpi_cells`; new helpers
`zero_runs(rows) -> list[(start, end)]` and `regular_zero(runs, ticket_interval) -> bool`.

## Step 2b. Missing KPI

KPI is often missing: a cell has no rows at all for the month, or rows for
some hours and not others. "No row" means two different things, outage or
missing data, and the script must not read one as the other.

- **Row share.** For every cell queried, the share of the month's hours
  that returned a row. Below `KPI_MIN_ROW_SHARE` the cell's KPI is
  unusable: verdict `no_kpi`. Such a cell is excluded from the outage set
  (it cannot be shown down) and, as a backup, carries `no_data` in every
  hour of step 6. It is never silently treated as zero.
- **Gaps inside a usable month.** A missing hour in a cell that has rows
  for most of the month counts as zero only inside a run that also has
  explicit zero rows next to it (the gap is the tail or the middle of a
  real outage); a missing hour with populated non-zero hours on both sides
  is `no_data` for that hour, not zero. A run made only of missing hours
  is `no_data`, not a down run.
- **The site.** If every cell of the site is `no_kpi`, the ticket is
  dropped (flagged `no_kpi`); if some are, the outage set is built from
  the others and the `no_kpi` cells are listed in the flags.
- **Baselines (step 6).** The same-weekday-hour baseline needs at least
  `BASELINE_MIN_SAMPLES` of its four samples; with fewer, the month's mean
  at the same hour of day is used and the baseline is marked `fallback`;
  with no sample at all, `no_baseline`, and the RRC gain for that hour is
  `no_data`.
- **Per point (step 6).** The two fractions exclude `no_data` backups from
  the denominator and record how many were excluded; a point whose
  reachable backups all lack data for an hour is `no_backup_data` for that
  hour, distinct from `no_backup`.
- **The report.** A section "KPI availability": per cell its row share
  and verdict; per outage hour the share of backups with data; the counts
  of `no_backup_data` points per area. The two caveats become three.

Writes: `kpi_availability.json`, read by steps 6 and 7.

## Step 2c. Technology

Every cell id gives its technology by its prefix pattern: three letters
and five digits is LTE (`CCL06069...`), four letters and six digits is NR
(`CCSN003553...`). Before anything else, check that `radio.radio_technology`
in every package and the KPI routing in `policy.route_kpi_cells` implement
exactly these two patterns (regular expressions `^[A-Z]{3}\d{5}` and
`^[A-Z]{4}\d{6}`); a recent edit may have set NR to five digits, which
would route every NR cell to the LTE tool. Fix it and add a test with the
two example ids. The outage set's technologies
decide which backups exist for this case:

- the outage set is LTE only: only LTE cells are backup candidates;
  NR cells seen in coverage are recorded (`other_technology`) and
  neither fetched for KPI nor counted at any point;
- the outage set is NR only: the same with the roles swapped;
- the outage set holds both: each technology is handled separately, LTE
  backups for LTE outage cells and NR backups for NR outage cells, with
  separate fractions per point and separate tables in the report.

This is the rule `radio.eligible_backup_cells` already applies; the
ground-truth script applies it before any KPI call so that no call is
made for a cell that cannot be a backup. Routing of KPI calls follows the
same pattern: LTE ids to `query_lte_rrc_prb`, NR ids to
`query_nr_rrc_prb`, one call per technology per step.

## Step 3. Hits and the edge

Reads: `scan.json`; the confirmed outage set (step 2).

Decides: a scan point is a *hit* when a sample lists a confirmed outage
sector at or above `COVERAGE_RSRP_DBM`. The edge rule: no hit may lie in
the outer `EDGE_BAND_KM` of the square. If one does, the square extends by
one band on that side (new lattice points at `SCAN_SPACING_M`, fetched as
in step 1, still inside the frame) and the rule runs again; a hit that
reaches the frame edge is recorded as `at_frame`.

Writes: `scan.json` updated with the hit flag per point and the final
square; `README.md` records the extensions.

## Step 4. Refinement around hits

Reads: the hits of step 3.

Decides: around every hit, the `REFINE_BLOCK_M` square centred on it is
refined to `REFINE_SPACING_M` in both directions, skipping points already
queried (the 1 km points inside the block, and points shared with a
neighbouring hit's block). The new points sample the gaps between the hit
and its neighbouring scan points, those that did not register a hit
included. A new point that lists an outage sector at or above the
threshold is a hit; refinement repeats around it. Stop when a pass adds
no hit.

The reference extent is every fetched point (scan and refinement) where
an outage sector is listed at or above the threshold, with every cell
listed in the same sample and its RSRP. Its resolution is 500 m inside
the footprint and 1 km outside.

Writes: `refinement.json`: per pass the hits refined, the new points, the
new hits; `reference_extent.json`: the extent points with their samples.

Functions: `fetch_area_points` with `grid_ids`; a new helper
`refine_block(hit_grid_id, geometry, block_m, spacing_m, already) -> list[str]`.

## Step 5. Cells first seen in the refinement

Reads: every cell listed in any sample fetched in step 4, against the
cells the scan saw (step 1) and the outage set of step 2.

Decides: the cells first seen in the refinement points, absent from the
scan's samples. For each new cell: query its hourly KPI
over the derived outage interval widened as in step 2, and apply the down
rule. A new cell found down joins the outage set; the hits of steps 3
and 4 are then re-evaluated with the enlarged set (a scan point that was
clear may become a hit), and the refinement runs again. A new cell not down joins
the backup candidates and its outage-hour KPI is kept for step 6.

Repeat after every refinement pass until no cell is new. This closes the
candidate list by observation.

When a newly seen cell is found down, the re-evaluation and refill do not
overwrite the extent built so far: the script writes a new directory
`ground_truth/<site>_<window>/pass_<n>/` with its own `outage_set.json`,
`scan.json`, `refinement.json` and coverage entries, copies the
coverage fetched so far into it (no location is fetched twice), and
continues there. The previous directory stays as the record of what the
smaller outage set gave. `README.md` at the top level lists the passes
and names the final one.

Writes: `cells_seen.json`: every cell seen in coverage, where it was first
seen (scan, refinement), whether the scan had it,
its KPI verdict (down, up, idle, no rows); `outage_set.json` updated with
any addition and the pass in which it was added.

Functions: the KPI tools as in step 2; `zero_runs`; the refinement of step 4.

## Step 6. The quantified truth

Reads: the reference extent (step 4); `outage_set.json` (steps 2 and 5);
for every backup cell seen in any sample of the extent, the hourly RRC and
PRB over the derived outage interval (fetched in steps 2 and 5) and over
the previous month (same source).

Decides, in two layers that are recorded separately and never mixed.

**Per backup cell, per outage hour:**
- observed RRC and observed PRB;
- the RRC baseline: the previous month's mean RRC at the same day of week
  and hour of day (four samples), the same baseline form `apply_kpi` computes;
- the RRC gain: observed minus baseline, as a number and as a ratio;
- `prb_issue`: observed PRB above `LOAD_LIMIT_PERCENT`;
- an hour with no row is `no_data` for that cell, not zero (rules in step 2b).

The RRC gain is what says where the outage traffic went; the PRB says
whether the cell could carry it.

**Per covered point, per outage hour:**
- the cells with coverage at the point: every eligible backup (same
  technology as the outage set, step 2c) listed in a sample together with
  an outage sector at or above `COVERAGE_RSRP_DBM`, with its RSRP;
- `prb_issue_fraction`: the share of those cells with `prb_issue` in that
  hour (cells with `no_data` excluded from the denominator and counted);
- `rsrp_issue_fraction`: the share of those cells whose RSRP is weaker than
  the outage sector by more than `SIGNAL_MARGIN_DB` or below
  `SERVICE_RSRP_DBM`;
- `no_backup`: true when the set is empty; `no_backup_data`: true when the
  set is not empty but no member has KPI for the hour (step 2b).

Two fractions per point and hour, kept apart. No class is derived from
them in this version; the class rule can read them later.

**Per site, per hour:** the mean of each fraction over the covered points,
the count of `no_backup` points, the count of points with each fraction
above one half. Per area as well, when the site's investigation run has a
geography file: a point belongs to the area whose grid ids contain its
100 m cell; otherwise the truth is per point only.

**Per site:** the sum of the backups' RRC gains against the outage sectors'
previous-month mean RRC at the same hours, as a ratio: how much of the
lost traffic shows up on the backups.

Writes: `kpi_outage_hours.json` (per cell, per hour, the four numbers);
`ground_truth.json`: per point the cells, the two fractions and
`no_backup` per hour; per area and site the aggregates per hour; per
backup the hourly table; the site ratio; the two caveats as fields
(observed PRB includes everything that happened in the hour; missing
hours are `no_data`, not zero).

Functions: KPI tools as in step 2; `radio.eligible_backup_cells`,
`radio.is_outage_cell` with the confirmed outage set as the task's
`outage_cell_ids`; a new `point_fractions(state, kpi_hours) -> dict`.

## Step 7. The report and the record

Reads: `ground_truth.json`, `calls.json`.

Writes: `ground_truth_report.md` in the final report's layout: section 1
the site table for the worst hour (covered points, no-backup points,
mean PRB-issue fraction, mean RSRP-issue fraction), per area when areas
are known, then the per-hour lines;
section 2 per backup the hourly table (observed and baseline RRC and PRB,
the increases, prb_issue); section 1 per area and hour the two fractions
and the total-loss count in place of the class table; section 3 total-loss locations; section 2b per point fractions summarised per area; section 4 what is
not established: the two caveats, flagged cells, missing hours,
scan extensions. For a `staggered` case, `kpi_month.png` (step 2) next to
the report. `calls.json` with every point and KPI call and its
latency.

Figures, all from `ground_truth.json` with matplotlib, same frame and
colours as the walkthrough page:
- `map_prb_issue.png` and `map_rsrp_issue.png`: the covered points on the
  grid for the worst hour, coloured by the fraction from 0 (green) to 1
  (red), `no_backup` points black, the site and, when known, area outlines; title with
  the hour and the site mean;
- `maps_by_hour.png`: the same two maps for every outage hour, one row per
  hour, so the reader sees the fractions move through the outage;
- `backup_rrc_gain.png`: one panel per backup cell, the whole month of
  hourly RRC as a line with the outage hours highlighted, the same-weekday
  same-hour baseline marked at each outage hour, and PRB on a second axis
  with the limit; the gain is read as the highlighted hours above the
  marks;
- `kpi_month.png` (step 2) for every case. `README.md` with the command, the constants, and the counts
(areas sampled, hit, filled; locations fetched; calls).

Functions: `completion_point.final_report`'s layout, with a second class
source: a new `report_from_truth(ground_truth) -> str`; `end_run`'s
`calls.json` writer.

---

## What the investigation runs get from this

- The task: the confirmed outage set and the derived interval (from
  `outage_set.json`), so an investigation run is given the outage that
  happened.
- The scorer: `reference_extent.json` and `ground_truth.json`. A run is
  scored at the truth's points: for each, the run's class at the 100 m
  cell under it, or `not fetched`.

## Cost, for planning

Scan 961 calls; refinement about 300 to 400 new points for a footprint of
40 to 80 km²; extensions a few dozen. About 1,300 to 1,400 point calls per
site, cached; about ten minutes with eight parallel calls. KPI: one call
per technology per step.

## Progress display

The script shows what it is doing with `tqdm` (already importable in the
environment; add it to the dependencies if not). One bar per step, named
for the step ("step 1: scan, 961 points"), advanced once per unit of work
the step loops over: cells for the KPI steps, areas for sampling and
filling, locations for every point fetch (the bar inside
`fetch_area_points` is passed in by the caller so the ground-truth script
and the investigation packages share it), passes for the fill loop,
figures for step 7. Each bar's postfix shows the running counts that
matter for that step (hit areas, cache hits, api calls, errors). The bars
go to stderr; the files are unchanged by them; `--quiet` turns them off
for batch runs.

## Check

1. On the closed case: step 1 writes 961 scan points; step 2 drops no
   ticket, finds the listed sectors down, derives an interval of at least
   three hours; `kpi_month.png` shows the zero run inside the ticket.
2. Step 3 ends with no hit in the outer band (or records the extensions);
   step 4 ends with a pass that adds no hit; `refinement.json` shows the
   passes; `calls.json` gives the point-call total.
3. If step 5 finds a new down cell, a `pass_2/` directory exists and the
   top README names it as final.
4. `ground_truth.json` has, for every extent point and every outage hour,
   the two fractions and `no_backup`; the four figures exist; the report's
   section 1 sums match the point counts.
5. Running the script twice on the same tool results gives identical
   files.
