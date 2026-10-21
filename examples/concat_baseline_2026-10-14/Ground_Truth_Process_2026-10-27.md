# Ground truth: the full process, for review

One site, one ticket, one run of `make_ground_truth.py`. Ten steps (step 6 has two halves). Each
step says what it reads, what it decides, what it writes, and which
existing function does the work. Function paths are placeholders in angle
brackets where I do not know them; the ones I know are filled in.

The product is a directory `ground_truth/<site>_<window>/` with
`reference_extent.json`, `outage_set.json`, `kpi_outage_hours.json`,
`ground_truth.json`, `ground_truth_report.md`, `calls.json` and
`README.md`. Every number in the report comes from those files.

Fixed numbers, all in one place at the top of the script:

| name | value | used in |
|---|---|---|
| `WINDOW_KM` | rural 50, suburban 20, urban 20 | step 3 |
| `EDGE_BAND_KM` | rural 5, suburban and urban 2 | step 7 |
| `SAMPLE_SPACING_M` | 1,000 | step 5 |
| `NEIGHBOUR_BAND_M` | 1,000 | step 6 |
| `DOWN_MIN_HOURS` | 3; a ticket whose interval is shorter is dropped | step 2 |
| `KPI_MONTH_DAYS` | 30 before the ticket start, 1 after its end | step 2 |
| `COVERAGE_RSRP_DBM` | -110 | steps 5 to 8 (the harness's constant) |
| `LOAD_LIMIT_PERCENT` | 80 | step 8 (the harness's constant) |
| `SIGNAL_MARGIN_DB`, `SERVICE_RSRP_DBM` | 10, -110 | step 8 (the harness's constants) |

---

## Step 1. The ticket and the candidate neighbours

Reads: the ticket (site id, listed sectors, ticket interval); the site
metadata (`query_basic_information`); the heatmap over the 30 km square
around the site.

Decides: the candidate cell set, every cell the heatmap shows as serving
anywhere in the square. The heatmap is used only for this list; its
footprints are not used.

Writes: `candidates.json`: the ticket as given, the site metadata, the
candidate cells with the number of heatmap points each serves.

Functions: `<path>.query_basic_information`; `<path>.query_coverage_heatmap`
(bbox from `state0.study_area_from_metadata`); a new helper
`candidate_cells(heatmap_csv) -> set[str]` that reads the serving-sector
column.

## Step 2. Who was down, and when

Reads: for the ticket's sectors and every candidate cell, the hourly KPI
(RRC, PRB) over one month: from 30 days before the ticket's start to 24
hours after its end. One month is what separates a real outage from a
cell whose RRC goes to zero every night or every weekend.

Decides, per cell:

- the runs of consecutive hours with RRC equal to zero or no row returned,
  over the whole month;
- a cell with such runs at the same weekday and hours in other weeks of
  the month is a regular zero, not an outage, for those hours (flagged
  `regular_zero`, excluded from the outage set);
- a run of at least `DOWN_MIN_HOURS` hours that overlaps the ticket
  interval, and is not a regular zero, makes the cell down for that run;
- a ticket whose own interval is shorter than `DOWN_MIN_HOURS` is dropped
  before any query (flagged `ticket_too_short`, no directory written);
- a cell whose RRC is zero through the month is idle (flagged, excluded).

The outage set is the ticket's sectors confirmed down plus every candidate
found down; ticket sectors not found down are flagged. The outage interval
is the intersection of the outage set's down runs. If the runs do not
overlap, the case is flagged `staggered`, the interval is the longest
single run, and step 9 draws every outage-set and candidate cell's RRC and
PRB over the month as one figure (`kpi_month.png`, one panel per cell,
the ticket interval and each down run marked) so the reviewer can see
what happened.

Writes: `outage_set.json`: per cell the hourly RRC and PRB over the month,
its runs, the verdict (down, up, idle, regular_zero); the confirmed outage
set; the derived interval; the flags (ticket sector not down; candidate
down beyond the ticket; idle; regular_zero; staggered).

Functions: `<path>.query_lte_rrc_prb`, `<path>.query_nr_rrc_prb` over the
month window (the KPI calls with a window inside the outage are yours to
supply); routing by id pattern from `policy.route_kpi_cells`; new helpers
`zero_runs(rows) -> list[(start, end)]` and `regular_zero(runs, ticket_interval) -> bool`.

## Step 3. The window and the areas

Reads: the site metadata; the OSM payload for the window square
(`WINDOW_KM` by density class).

Decides: the activity areas inside the window, derived with the same rules
as initialization: settlements and road corridors, their grid ids on the
fixed 60 km frame. Nothing else is an area.

Writes: `state_00.json` and `geography.json` of the reference, as a harness
run writes them, so every reader works on them; `areas_grid_ids.json`.

Functions: `state0.build_state0` with the window square in place of the
density square (one parameter: the half width), `evidence_state.split_geography`;
OSM through `osm_landuse.query_osm_landuse` (tiled, as today).

## Step 4. The probe

Reads: the geometry.

Decides: nothing; it observes. The two probe rings at 500 m and 1 km, 24
point calls, enter the coverage table so that the sectors' bearings are on
record for the report's direction summary.

Writes: coverage entries with `observation: gt_probe`.

Functions: `point_coverage.probe_ring_ids`, `point_coverage.fetch_area_points`
with `grid_ids`, `point_coverage.apply_point_coverage`.

## Step 5. Sparse sampling of every area

Reads: every activity area in the window.

Decides: per area, the sample locations: its centroid cell, plus one cell
per `SAMPLE_SPACING_M` across it (for a corridor, one per kilometre along
it). Fetch all samples. An area is *hit* when any sample lists a confirmed
outage sector at or above `COVERAGE_RSRP_DBM`; *clear* otherwise.

Writes: `samples.json`: per area the sample grid ids, the listing found or
not, the strongest outage RSRP among its samples.

Functions: a new helper `sample_ids(area_grid_ids, geometry, spacing) -> list[str]`;
`fetch_area_points` with `grid_ids`; `apply_point_coverage`.

## Step 6. Fill and neighbours, until nothing new

Loop:

- Fill: every hit area not yet filled is fetched completely.
- Neighbours: every clear area that touches a filled area, or lies within
  `NEIGHBOUR_BAND_M` of one, has its locations within that band of the
  filled area fetched. A listing there makes it hit (filled next pass).
- Stop when a pass adds no listing.

Decides: the reference extent, every fetched location where a confirmed
outage sector is listed at or above the threshold, with every cell listed
in the same sample and its RSRP.

Writes: coverage entries as a harness run writes them; `fill_passes.json`:
per pass the areas filled, the neighbour bands fetched, the listings
found.

Functions: `fetch_area_points` (whole area, and with `grid_ids` for a
band); `apply_point_coverage`; `point_coverage.refresh_summaries`; a new
helper `band_ids(area, filled_area, geometry, band_m) -> list[str]`.

## Step 6b. Cells first seen in coverage

Reads: every cell listed in any sample fetched so far (steps 4 to 6),
against the candidate set of step 1 and the outage set of step 2.

Decides: the cells the heatmap did not show (it lists serving sectors
only; a cell that is never the strongest anywhere in the square is absent
from it) but the point API did. For each new cell: query its hourly KPI
over the derived outage interval widened as in step 2, and apply the down
rule. A new cell found down joins the outage set; the listings of steps 5
and 6 are then re-evaluated with the enlarged set (an area that was clear
may become hit), and the fill loop runs again. A new cell not down joins
the backup candidates and its outage-hour KPI is kept for step 8.

Repeat after every fill pass until no cell is new. This closes the
candidate list by observation instead of by the heatmap.

When a newly seen cell is found down, the re-evaluation and refill do not
overwrite the extent built so far: the script writes a new directory
`ground_truth/<site>_<window>/pass_<n>/` with its own `outage_set.json`,
`samples.json`, `fill_passes.json` and coverage entries, copies the
coverage fetched so far into it (no location is fetched twice), and
continues there. The previous directory stays as the record of what the
smaller outage set gave. `README.md` at the top level lists the passes
and names the final one.

Writes: `cells_seen.json`: every cell seen in coverage, where it was first
seen (probe, sample, fill, band), whether it was in the heatmap's list,
its KPI verdict (down, up, idle, no rows); `outage_set.json` updated with
any addition and the pass in which it was added.

Functions: the KPI tools as in step 2; `down_runs`; the fill loop of step 6.

## Step 7. The edge rule

Reads: the areas whose nearest location lies in the outer `EDGE_BAND_KM`
of the window.

Decides: if any of them is hit (from its samples or its fill), the window
is too small for this site: enlarge the window by one band (a new OSM
call for the added ground, new areas, steps 5 and 6 on them) and apply the
rule again. When every outer-band area is clear, the extent is bounded by
observed empty ground on every side.

Writes: `window.json`: the final window, the number of enlargements, the
outer-band areas and their verdicts.

Functions: the expansion machinery (`runner_point_nodes.execute_expand_study_area`
and `evidence_state.apply_expansion` cannot be used as they are, since
they expand one direction; a new helper `enlarge_window(state, run_dir, band_km)`
that reuses `state0.derive_geography` on the ring of new ground).

## Step 8. The quantified truth

Reads: the reference extent (step 6); `outage_set.json` (steps 2 and 6b);
for every backup cell seen in any sample of the extent, the hourly RRC and
PRB over the derived outage interval (fetched in steps 2 and 6b) and over
the previous month (same source).

Decides, in two layers that are recorded separately and never mixed.

**Per backup cell, per outage hour:**
- observed RRC and observed PRB;
- the RRC baseline: the previous month's mean RRC at the same day of week
  and hour of day (four samples), the harness's own baseline form;
- the RRC gain: observed minus baseline, as a number and as a ratio;
- `prb_issue`: observed PRB above `LOAD_LIMIT_PERCENT`;
- an hour with no row is `no_data` for that cell, not zero.

The RRC gain is what says where the outage traffic went; the PRB says
whether the cell could carry it.

**Per covered point, per outage hour:**
- the cells with coverage at the point: every eligible backup listed in a
  sample together with an outage sector at or above `COVERAGE_RSRP_DBM`,
  with its RSRP;
- `prb_issue_fraction`: the share of those cells with `prb_issue` in that
  hour (cells with `no_data` excluded from the denominator and counted);
- `rsrp_issue_fraction`: the share of those cells whose RSRP is weaker than
  the outage sector by more than `SIGNAL_MARGIN_DB` or below
  `SERVICE_RSRP_DBM`;
- `no_backup`: true when the set is empty.

Two fractions per point and hour, kept apart. No class is derived from
them in this version; the class rule can read them later.

**Per area and per site, per hour:** the mean of each fraction over the
covered points, the count of `no_backup` points, the count of points with
each fraction above one half.

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

## Step 9. The report and the record

Reads: `ground_truth.json`, `calls.json`.

Writes: `ground_truth_report.md` in the final report's layout: section 1
the per-area table for the worst hour (covered points, no-backup points,
mean PRB-issue fraction, mean RSRP-issue fraction), then the per-hour
lines;
section 2 per backup the hourly table (observed and baseline RRC and PRB,
the increases, prb_issue); section 1 per area and hour the two fractions
and the total-loss count in place of the class table; section 3 total-loss locations; section 2b per point fractions summarised per area; section 4 what is
not established: the two caveats, flagged cells, missing hours,
enlargements. For a `staggered` case, `kpi_month.png` (step 2) next to
the report. `calls.json` with every point, OSM and KPI call and its
latency.

Figures, all from `ground_truth.json` with matplotlib, same frame and
colours as the walkthrough page:
- `map_prb_issue.png` and `map_rsrp_issue.png`: the covered points on the
  grid for the worst hour, coloured by the fraction from 0 (green) to 1
  (red), `no_backup` points black, area outlines and the site; title with
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

## What the harness runs get from this

- The task: the confirmed outage set and the derived interval (from
  `outage_set.json`), so the harness investigates the outage that happened.
- The scorer: `reference_extent.json` and `ground_truth.json`.

## Settled on 2026-10-21

- Step 2 reads one month of KPI; regular zeros are excluded; a staggered
  case is flagged and drawn.
- Step 5: one sample per kilometre along a corridor.
- Step 7: one band and re-check.
- Step 8: per backup, observed RRC and PRB against the previous month's
  baseline, with the increases; per location, the PRB-issue fraction and the
  RSRP-issue fraction over the cells covering it, kept separate.
- Step 6b: re-evaluate and refill, in a new pass directory, never in place.
- The KPI calls with a window inside the outage: supplied by you.

## Settled on 2026-10-21, second round

- Figures draw the whole month of RRC and PRB per cell; the baseline is
  the same day of week and hour of day.
- `DOWN_MIN_HOURS` is 3; a ticket shorter than 3 hours is dropped.
- One instruction file for the whole process.
- Map colours: green to red over 0 to 1, no-backup points black.
