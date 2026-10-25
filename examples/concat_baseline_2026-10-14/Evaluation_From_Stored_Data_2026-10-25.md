# Evaluation from stored data: ground-truth statistics, matching, figures, analysis

This file replaces `Evaluation_Design_2026-10-25.md` and
`CHANGES_2026-10-25_query_radius_10m.md`. It is the full instruction: the
earlier design, the 10 m query radius, and one new rule that governs all
of it.

**The rule: no new point calls, no new KPI calls, no rerun.** All runs are
complete; the evaluation analyses them as they are. Every number in
this instruction is computed from files that already exist: the
ground-truth directories the scan script wrote, the run directories the
investigation code wrote, and the per-site caches. The evaluation scripts
never import the point API or the KPI tools. Where an input is absent
(a point never fetched, a cell without KPI rows, an hour without a row),
the script records it as absent and goes on; it never fills the gap by
querying. If a case lacks something this file needs, the case's report
says what is missing and the case stays in the tables with that mark.

**Why.** Point calls are what makes a run long and unstable, and the
cases at hand were already fetched. Scoring on what exists keeps the
evaluation reproducible: the same files give the same numbers every time,
and a reader can trace every number to a stored sample or KPI row.

---

## 0. Inputs, conventions, the query radius

**Ground-truth directory** (per case, as the scan script wrote it): the
scan and refinement points with their samples (`scan.json`,
`refinement.json`, `reference_extent.json`), the confirmed outage set with
verdicts (`outage_set.json`), the KPI rows per cell and month (the
`kpi_cache` files, or whatever your copy wrote), and
`kpi_availability.json`. If your copy used other names, map them once at
the top of the script, in one dictionary, and change nothing else.

**Run directory** (per case and condition, as the investigation code
wrote it): the last `state_NN.json` (the coverage table keyed by grid id
with the samples per location, the geography with each area's grid ids,
the KPI baselines), `redistribution.json` (the estimated load per backup
and hour), `final_report.json` or `.md` (the classes per location and the
per-area counts), `calls.json`, `steps.json`, `run.json`.

**Per-site caches**: `point_cache.jsonl` keyed `grid_id|radius_m|epoch`.
The scripts may read it to recover a point's samples when a run's table
does not hold them; they never append to it.

**Conventions.** A *point* is a cell of the 100 m frame grid. The ground
truth holds points on its scan lattice (1 km) and its refinement lattice
(500 m); a run holds every cell it fetched. The *outage sectors* are the
confirmed outage set; a *reachable backup* at a point is an eligible cell
listed in the same sample as an outage sector at or above -110 dBm.
Constants are imported from `completion_point`, one definition: the
10 dB margin, the -110 dBm threshold, the 80 % load limit.

**The query radius.** The point API serves a 10 m radius only. A point's
samples are the measurements within that radius of the centre of its
100 m cell, not the cell. Three consequences run through this file:

- many points return no sample. Such a point is *unknown*: not covered,
  not uncovered, not counted in any share. Every table and figure carries
  the no-sample count next to the point count;
- a point's verdict rests on few samples. The record keeps `n_samples`
  per point so a reader can weigh it; no minimum is imposed, because a
  threshold would hide data rather than report it;
- a run and the truth that fetched the same point with the same radius
  and epoch hold the same samples. The record keeps `radius_m` per point,
  read from the cache key or the call record, and the matching uses it
  (section 2.1).

---

## 1. The ground-truth record, per point

**Why.** The statistics made so far were computed without area
distinction and some are doubtful. The fix is not a new scan but a
recomputation: regenerate the per-point record from the stored samples
and the stored hourly KPI, then regenerate every aggregate from the
record. Nothing is read from an earlier aggregate.

For every fetched point of the ground truth (scan and refinement), and
for every outage hour `h`:

| field | definition |
|---|---|
| `radius_m` | the radius the point was fetched with |
| `n_samples` | the number of samples returned; `no_sample = (n_samples == 0)`, and then no other field is set |
| `outage_rsrp` | the best RSRP of any outage sector at the point; absent when no outage sector is listed at or above -110 dBm (the point is sampled but not covered) |
| `backups[]` | the reachable backups, each with `rsrp`, `rsrp_drop = outage_rsrp - rsrp`, `rsrp_issue = rsrp_drop > 10 or rsrp < -110`, and per hour `prb_obs[h]`, `prb_issue[h] = prb_obs[h] > 80`, `rrc_gain[h]`, `data[h]` (true when the hour has a row) |
| `n_backups` | the number of reachable backups; `no_backup = (n_backups == 0)` |
| `f_rsrp` | the share of reachable backups with `rsrp_issue`; one number per point, independent of the hour |
| `f_prb[h]` | the share of reachable backups with `prb_issue[h]` among those with `data[h]`; `no_backup_data[h]` when none has data |
| `f_prb_worst` | the maximum of `f_prb[h]` over the hours, and `worst_hour` |

"1/3 of the backup cells experience a 10 dB RSRP degradation, 2/3 do not"
is `f_rsrp = 1/3`; "2/3 experience PRB congestion" is `f_prb[h] = 2/3`.
Both are counts over the same list `backups[]`, so a reader can verify
either from the record. The two are never combined into one number.

**KPI from stored rows only.** `prb_obs[h]` and `rrc_gain[h]` come from
the rows already on disk. `prb_obs[h]` is the load observed on the backup
during the actual outage hour `h`: it is what happened, including every
cause of load in that hour. The run's PRB for the same backup and hour is
an estimate made from the pre-outage baseline and the redistribution
model. The comparison in section 2 is therefore estimate against
observation, and section 4.3 reads it that way. A backup with no rows is `no_data` in every
hour and listed as such; a backup with rows but none for `h` is `no_data`
for `h`. A cell seen in a sample that was never queried for KPI (a cell
first seen in refinement after the KPI step, for example) is a reachable
backup with `no_data` throughout and is listed in the report under
"backups without KPI"; it is not fetched. The baseline for `rrc_gain` is
the one the scan script computed; when none exists for a cell and hour,
`rrc_gain[h]` is `no_data`.

The script stores `backups[]` in full, so any statistic in any report can
be reproduced from `ground_truth.json`.

**Aggregates**, each per hour where the field has an hour:

- over all extent points: count, `no_sample` count and share, and then
  over the sampled points only: covered count, `no_backup` count and
  share, mean `f_rsrp`, mean `f_prb[h]`, share of points with
  `f_rsrp >= 0.5`, share with `f_prb[h] >= 0.5`, share with `f_rsrp == 1`
  (every backup degraded), share with `f_prb[h] == 1`;
- the same over the points inside each area, when the case has a run
  with a geography file (section 2.2); the truth itself has no areas;
- per backup cell: the number of points where it is reachable, its
  `rrc_gain[h]`, `prb_obs[h]`, `prb_issue[h]`, and `no_data` hours.

---

## 2. Matching a run to the ground truth

**Why area level first.** The run's conclusions are area statements:
which settlements and corridors lose service, and how much of each is
degraded by signal or by capacity. The truth is a set of points. The
comparison that answers "did the agent get the impact right" is
therefore made per area, from both sides' point statistics aggregated
over the same area. The two sides fetched different points, so a
point-by-point comparison is possible only where they overlap; it is
kept as a secondary analysis, and the points the run fetched that the
truth does not hold are reported on their own.

Both sides are on the same 100 m grid. The run's samples per location
are read from its last `state_NN.json`; when the table holds only the
derived cells and not the samples, read the samples from the per-site
`point_cache.jsonl` by the location's cache key.

### 2.1 Area level (primary)

The run's areas are sets of grid ids (`geography.json` in the run
directory, or the geography inside the last state file). A point belongs
to an area when its grid id is in the area's set; a point in two areas (a
corridor crossing a settlement) counts in both, as the run's own counts
do. The truth has no areas of its own; it is read through the run's.

For every area, the same statistics are computed twice by the same code,
once over the truth's sampled points inside the area and once over the
run's sampled points inside the area, each side from its own samples:

| statistic | truth side | run side |
|---|---|---|
| `n_points`, `n_sampled`, `n_covered` | truth points in the area | run points in the area |
| `no_backup_share` | covered points with no reachable backup | same |
| `f_rsrp_mean`, `f_rsrp_ge_half`, `f_rsrp_all` | mean of `f_rsrp`, share of points at or above 0.5, share at 1 | same |
| `f_prb_mean[h]`, `f_prb_ge_half[h]`, `f_prb_all[h]`, and the worst hour | from observed PRB during the outage | from the estimated PRB of `redistribution.json` |
| `class_share[c]` | class per point by `completion_point.classify_locations` with the strongest reachable backup's observed PRB in the worst hour; backups all without data give `unknown cause` | the run's reported class per point (its own report) |

The per-area comparison is the difference run minus truth of every
statistic: `d_no_backup`, `d_f_rsrp_mean`, `d_f_prb_mean[h]` and for the
worst hour, and for the classes the per-class difference and the total
variation distance `tv = sum(|class_share_run[c] - class_share_truth[c]|) / 2`
(0 when the two class distributions agree, 1 when they share nothing).
Each area row also carries `extent_recall`: the share of the truth's
sampled points in the area that the run fetched.

Three kinds of area row:

- **compared**: both sides have sampled points in the area;
- **truth only**: the run never queried the area (`n_sampled_run = 0`);
  the row carries the truth's statistics and marks the cost of leaving
  the area;
- **run only**: the run has sampled points there but the truth has none
  (an area outside the truth's lattice or extent); the row carries the
  run's statistics and is not compared. Section 2.3 reports these points.

The truth's lattice is coarse (500 m inside the footprint, 1 km
outside), so a small area rests on few truth points. Every row carries
`n_sampled` for both sides and the tables are sorted by it; the summary
numbers weight areas by the truth's `n_sampled`, and an area with fewer
than five truth points is shown but excluded from the weighted means,
with that exclusion counted in the row `areas_excluded_few_points`.

### 2.2 Matched points (secondary)

For every truth point `p` that the run also fetched, the run's reachable
backups at `p` are computed by the same rule from its own samples and
compared with the truth's. `backup_jaccard(p)` is the Jaccard index of
the two sets. With the same `radius_m` and epoch on both sides it must be
1; a value below 1 then marks a rule mismatch between the two
computations and the script reports it as a check failure, not as a run
error. With different radii (a run fetched before the API change) it is a
measurement difference and is reported as such, per point and as a mean.
`d_rsrp(p) = f_rsrp_run - f_rsrp` and `d_prb(p, h) = f_prb_run - f_prb`
are the per-point differences; a confusion matrix of run class against
truth class over the matched points is the class-level comparison. A
truth point the run fetched that returned no sample is `missing_in_run`;
with the same radius this coincides with the truth's `no_sample` and the
point is unknown on both sides.

Truth points the run never fetched are `not_fetched_in_area` when they lie
in an area of the run's geography, and `not_fetched_outside_areas` when
they lie in no area (the design never fetches there; this is a limit of
the area-based investigation, reported separately and not counted as an
error of the run).

### 2.3 Points the run fetched that the truth does not hold

The run's sampled points that are not on the truth's lattice (or lie
outside the truth's extent) are not compared. They are reported on their
own, because they are evidence the truth does not have:

- count per area, and the count outside the truth's final square;
- the run's statistics over them (the row-side columns of 2.1), as a
  separate table and as a layer on the run map (section 4.1);
- the subset that is *covered* (an outage sector at or above -110 dBm)
  and lies beyond the truth's extent: these are places the run found
  outage coverage where the truth's edge rule had closed, and the report
  lists them with their distance from the nearest truth hit. They are a
  finding about the truth's lattice as much as about the run.

### 2.4 Numbers per run

Primary, area level, weighted by the truth's `n_sampled` over compared
areas:

| number | definition |
|---|---|
| areas | compared / truth only / run only, with the truth points in each group |
| area extent recall | truth sampled points in compared areas / truth sampled points in all areas with truth points (truth-only areas count as unfetched) |
| no-backup share error | weighted mean of `|d_no_backup|` |
| RSRP share error | weighted mean of `|d_f_rsrp_mean|`, and the signed mean (bias) |
| PRB share error | weighted mean of `|d_f_prb_mean|` for the worst hour and per hour, and the signed mean |
| class distance | weighted mean of `tv`; plus the two rates that matter to an operator, over the compared areas' points: truth total loss reported as served (missed loss), truth served reported as loss or degrade (false alarm) |
| area ranking | the areas ordered by truth total-loss share against the run's order: how many of the truth's top three are in the run's top three |

Secondary, point level, over matched points: backup agreement (mean
`backup_jaccard`, with the share of points where the radii differ), mean
absolute `d_rsrp`, mean absolute `d_prb` for the worst hour and per hour,
the confusion matrix's diagonal share, and the per-backup PRB error: mean
absolute (estimated minus observed PRB) over backups and hours with data,
and the share of backups where estimated and observed fall on different
sides of 80.

Run-only points: their count, the count beyond the truth's extent, and
the covered count among those.

Cost and data: point calls, cache hits, rounds, wall time from
`calls.json` and `run.json`, each also as a fraction of the ground
truth's point calls; the no-sample share of the truth, the share of
backups without KPI, the share of outage hours without KPI rows.

---

## 3. The ground-truth figures and report

Two maps, with the same frame, limits and colours as the walkthrough
page, plus a text panel on each.

**Map A, RSRP**: every extent point coloured by `f_rsrp`, green at 0 to red
at 1; `no_backup` points black; `no_sample` points a small hollow grey
circle, so the reader sees where the truth is unknown; sampled points
without outage coverage a small grey dot; the site as a cross; area
outlines when a run's geography file exists. Title: `<site>, outage
<start> to <end>: share of reachable backups with RSRP degradation
(> 10 dB or below -110 dBm)`.

**Map B, PRB**: the same points coloured by `f_prb_worst`; `no_backup`
black; `no_backup_data` hatched grey; `no_sample` as on map A. Title:
`... share of reachable backups congested (PRB > 80 %) in the worst
hour, <worst_hour>`.

**The text panel**, a box on the right of each map, eight lines, numbers
from the aggregates of section 1 and nothing else:

```
extent          1,284 points (10 m radius at each), 500 m inside the footprint, 1 km outside; 341 (26.6 %) with no sample
outage set      ARL02850_aa_1, _ab_1, _ac_1 (3 of 6 sectors; 3 stayed up)
interval        2026-03-24 11:00 to 2026-03-25 02:00 UTC (15 h)
no backup       212 of 943 sampled points (22.5 %)
degraded        mean share 0.31; 388 points (41 %) with share >= 0.5; 97 (10 %) with every backup degraded
congested       worst hour 18:00: mean share 0.42; 505 points (54 %) >= 0.5; 160 (17 %) every backup   [map B only]
backups         CCL06090_aa_1 reachable at 611 points, +212 RRC, PRB 86 % (congested 6 of 15 h); CCL06090_ab_1 ...  (top 3 by points)
KPI             3 backups with no data (listed in the report); 2 hours with no data for CCL06112_ab_1
```

Map A's panel carries the `degraded` line and not the `congested` one;
map B the reverse. Shares on the `degraded` and `congested` lines are
over sampled points. Below each map, one line: `every statistic is in
ground_truth.json; the report lists them per area and per hour`.

**Map C, hours**: the PRB map for every outage hour as a strip, one small
map per hour with its mean share in the corner, so the reader sees when
the congestion peaks.

**The report** (`ground_truth_report.md`) carries the same numbers in
tables: section 1 the site aggregates per hour; section 2 per area when a
run's areas exist; section 3 per backup the hourly table (observed RRC,
gain, PRB, congested, `no_data`); section 4 the data availability: the
no-sample share, the closing band's sampled and no-sample counts (a band
closed on few sampled points is a weak edge, and the report says so),
the backups without KPI, the hours without rows, and the caveats.

---

## 4. Presenting and analysing the comparison

### 4.1 Figures per run

- **Area maps**, the primary figure: one row for RSRP and one for PRB,
  three panels each: truth, run, difference. Each area is filled by its
  area statistic (`f_rsrp_mean`, `f_prb_mean` in the worst hour), green
  at 0 to red at 1; truth-only areas hatched on the run panel, run-only
  areas hatched on the truth panel; the difference panel on a diverging
  scale, blue when the run underestimates, red when it overestimates,
  white at zero, with `tv` printed in each area. The text panel on the
  difference map: the area counts, area extent recall, the three share
  errors with their bias, the class distance, the two operator rates.
- **Per-area bars**: for each compared area, truth and run side by side
  for `no_backup_share`, `f_rsrp_mean`, `f_prb_mean` (worst hour), and the
  class shares as stacked bars; `n_sampled` of both sides under the area
  name; truth-only areas shaded.
- **Point maps**, secondary: the same three panels at point level, the
  run panel marking `not_fetched_in_area` with a hollow circle,
  `not_fetched_outside_areas` with a dot, run-only points as small
  triangles, no-sample points as on the truth maps; the difference panel
  over matched points only.
- **The confusion matrix** of classes over matched points, counts and row
  shares.
- **Per-backup scatter**: estimated PRB against observed PRB, one point per
  backup and hour with data, the 80 % lines drawn; the four quadrants are
  the four outcomes (both congested, both clear, missed congestion, false
  alarm).

### 4.2 Tables across runs and conditions

One table per condition (rendered, concat, concat_checked, rules), one row
per case, the primary numbers of section 2.4 first, then the secondary
and the run-only counts, then cost and data; a last row with mean and
range. One summary table across conditions with the means of the primary
numbers. Cases where the confirmed outage set differed from the ticket
are listed with a flag, since every condition was given the confirmed
set. Cases with a high no-sample share, many backups without KPI, or many
areas excluded for few points carry those numbers in their row, so a
case with little data is read as such and not as a bad run.

### 4.3 Reading the differences

An area-level difference has one of three sources, and the per-area row
says which:

1. **Extent**: the run did not fetch the area (truth only), or fetched a
   small part of it (`extent_recall` low). The cause is the
   investigation's choice of areas or its stop; the completion check and
   the open items of the run's last round say why the area was left. The
   run's statistics over a partly fetched area rest on the part it chose,
   which may be the roadside strip or the settlement centre; the point
   maps show which.
2. **Sampling**: the two sides fetched different points of the area, and
   the area statistic moves with the points. The matched-point analysis
   bounds this: where `backup_jaccard = 1` at every matched point, the
   difference in `f_rsrp_mean` between the sides comes only from the
   unmatched points, and the run-only table says what the run saw there.
3. **Load model**: `d_f_prb_mean` with `d_f_rsrp_mean` near zero is the
   redistribution estimate against the load observed during the outage.
   The per-backup scatter says whether the estimate is biased (points off
   the diagonal on one side) or noisy, and which backups it misjudges.
   The observed load includes everything that happened in the hour, so a
   part of this difference is not the model's to remove; the scatter's
   spread across cases shows how large that part is.

At the point level, the same three apply, with the rule-mismatch check
(`backup_jaccard < 1` at equal radius) fixed before any table is read.

The analysis for the paper follows those lines: how much of each
condition's area error is extent (1), how much sampling (2), how much
load model (3); then, across conditions, which of the three the input
format and the completion machinery change. That is where the agent
performs well or badly stated in terms the design can act on: an extent
miss is a strategy problem, a sampling difference is a choice of where
to look inside an area, and a load error is a model problem. The
measurement limit that remains is the no-sample share: it is the same
for every condition and for the truth, and the tables report it per
case.

---

## 5. The investigation packages: offer 10 m only

**Why.** The tool still offers the model `[4, 10, 100]` and the skill text
tells it to choose the radius by the question. A future run can spend
rounds on calls the API rejects. The rule policy and the ring probe
already use 10, and the point cache key includes the radius, so results
fetched at another radius are never reused by mistake. No run is
repeated for this; it applies to runs made from now on.

1. `runner_point_nodes.py`, in all three packages: `AREA_RESOLUTIONS = (10,)`
   and, in `QUERY_AREA_COVERAGE`, `"resolution": {"type": "number", "enum": [10]}`.
   The check in `validate_action` stays. In the concat package, the
   `allowed_resolutions` passed to the parser becomes `(10,)`.
2. `synthetic_case.py`: the same enum `[10]` in the tool list.
3. `investigation_skill.txt` and `investigation_skill_rendered.txt`:
   delete the sentence that starts "The resolution values the coverage
   tool accepts" and the sentence "Choose the radius by the question ...
   the locations of an area." Replace them with one sentence: "Each
   location call returns the samples within 10 m of the grid cell centre;
   a location with no sample is unknown, not uncovered." The rest of the
   paragraph stays.
4. Nothing changes in `point_coverage.py`: `valid`, `missing` and `error`
   per location already separate a point with samples from one without,
   and `locations_missing` is in the summary. Check that the rendered
   context prints the missing count for every area next to the covered
   count, and that an unobserved direction (the ring probe change) is
   decided by the absence of sampled points, not by the absence of
   covered points: a direction whose probe points all returned no sample
   is unobserved.

---

## 6. What to build

Three scripts, none of which imports the point API or the KPI tools:

- `regenerate_ground_truth.py <ground truth dir>`: section 1 from the
  stored samples and KPI rows, writing `ground_truth.json` (the record
  with `backups[]` in full, the aggregates); then section 3, the three
  figures with their text panels and the report. It overwrites earlier
  statistics files and figures and says so in the README.
- `score_run.py <run dir> <ground truth dir>`: section 2, writing
  `score.json` (the numbers of 2.4; the per-area table with both sides'
  statistics, the differences and the source from 4.3; the matched-point
  records; the run-only points; the confusion matrix) and the figures of
  4.1 into the run directory.
- `summarize_scores.py <score.json ...>`: the tables of 4.2, as one
  Markdown file.

Section 5 is an edit of the packages, done once.

---

## 7. Check

1. Running `regenerate_ground_truth.py` twice on the same directory gives
   byte-identical `ground_truth.json`; no network call is made (run it
   with the API modules absent from the path and it still completes).
2. Every number on a text panel is found in `ground_truth.json` or its
   aggregates by name.
3. For a case where the run and the truth used the same radius and
   epoch, `score.json` has `backup_jaccard = 1` at every matched point
   and `d_rsrp = 0` wherever both sides have the same backups; a
   deviation is a bug to fix before any table is read. Scoring a run
   against a truth built from the run's own points (the same samples on
   both sides) gives every area difference 0 and `tv = 0`.
3b. Every run point is in exactly one of: matched, run only inside the
   truth's square, run only beyond it; every truth point in exactly one
   of: matched, `missing_in_run`, `not_fetched_in_area`,
   `not_fetched_outside_areas`, `no_sample`. The counts add up to the
   totals in `calls.json` and `ground_truth.json`.
4. `summarize_scores.py` over all cases of one condition gives one row
   per case with the data columns filled, including the cases with
   missing KPI.
5. After section 5, a run offers only `resolution: 10` in the action
   list and a decision with 100 is rejected with a message naming `[10]`.
