# Evaluation design: ground-truth statistics, matching, figures, analysis

Three things, as asked: the per-point statistics the ground truth must
hold and how they are shown on its two figures; how an investigation run
is matched to the ground truth at the point and at the area level, and
what is measured; and how the comparison is presented and analysed. The
decisions are stated as rules a script can apply; the figures are
specified to the line.

Conventions. A *point* is a cell of the 100 m frame grid. The ground truth
holds points on its scan lattice (1 km) and its refinement lattice
(500 m); a run holds every cell it fetched. The *outage sectors* are the
confirmed outage set; a *reachable backup* at a point is an eligible cell
listed in the same sample as an outage sector at or above -110 dBm.

---

## 1. The ground-truth record, per point

For every point in the reference extent, and for every outage hour `h`:

| field | definition |
|---|---|
| `outage_rsrp` | the best RSRP of any outage sector at the point |
| `backups[]` | the reachable backups, each with `rsrp`, `rsrp_drop = outage_rsrp - rsrp`, `rsrp_issue = rsrp_drop > 10 or rsrp < -110`, and per hour `prb_obs[h]`, `prb_issue[h] = prb_obs[h] > 80`, `rrc_gain[h]`, `data[h]` (true when the hour has a row) |
| `n_backups` | the number of reachable backups; `no_backup = (n_backups == 0)` |
| `f_rsrp` | the share of reachable backups with `rsrp_issue`; one number per point, independent of the hour |
| `f_prb[h]` | the share of reachable backups with `prb_issue[h]` among those with `data[h]`; `no_backup_data[h]` when none has data |
| `f_prb_worst` | the maximum of `f_prb[h]` over the hours, and `worst_hour` |

"1/3 of the backup cells experience a 10 dB RSRP degradation, 2/3 do not"
is `f_rsrp = 1/3`; "2/3 experience PRB congestion" is `f_prb[h] = 2/3`.
Both are counts over the same list `backups[]`, so a reader can verify
either from the record. The two are never combined into one number.

The script recomputes every field from the per-point samples and the
per-cell hourly KPI, never from an earlier aggregate, and stores
`backups[]` in full, so any statistic in any report can be reproduced
from `ground_truth.json`. This is the part to redo where the current
statistics are doubtful: regenerate the record from the samples, then
regenerate every aggregate from the record.

**Aggregates**, each per hour where the field has an hour:

- over all extent points: count, `no_backup` count and share, mean
  `f_rsrp`, mean `f_prb[h]`, share of points with `f_rsrp >= 0.5`, share
  with `f_prb[h] >= 0.5`, share with `f_rsrp == 1` (every backup degraded),
  share with `f_prb[h] == 1`;
- the same over the points inside each area, when the site has a
  geography file (section 2.2);
- per backup cell: the number of points where it is reachable, its
  `rrc_gain[h]`, `prb_obs[h]`, `prb_issue[h]`.

---

## 2. Matching a run to the ground truth

### 2.1 Point level

Both sides are on the same 100 m grid, so matching is by grid id. For
every ground-truth point `p`:

- **fetched**: the run's coverage table has `p` with samples. Then the
  run's reachable backups at `p` are computed by the same rule from its
  own samples, and compared with the truth's: `backup_jaccard(p)` is the
  Jaccard index of the two sets; `f_rsrp_run(p)` is the run's share, and
  `d_rsrp(p) = f_rsrp_run - f_rsrp`; `f_prb_run(p, h)` is the share of the
  run's reachable backups whose *estimated* PRB (from `redistribution.json`)
  exceeds 80 in hour `h`, and `d_prb(p, h) = f_prb_run - f_prb`.
- **fetched, no sample**: the run fetched `p` and got nothing; recorded as
  `missing_in_run`.
- **not fetched**: the run never fetched `p`; recorded as `not_fetched`.
  Among these, `not_fetched_in_area` when `p` lies inside an area of the
  run's geography (the run could have fetched it), and
  `not_fetched_outside_areas` when `p` lies in no area (the design never
  fetches there; this is a limit of the area-based investigation, reported
  separately and not counted as an error of the run).

The truth's lattice is coarser than the run's grid, so the run's points
that lie between truth points are not scored; the comparison is at the
truth's points only, and the paper says so.

### 2.2 Area level

The run's areas are sets of grid ids (`geography.json`). A truth point
belongs to an area when its grid id is in the area's set; a point in two
areas (a corridor crossing a settlement) counts in both, as the run's own
counts do. For each area of the run:

- the truth's aggregates over the truth points inside the area (section
  1), and the counts of `fetched`, `missing_in_run`, `not_fetched_in_area`;
- the run's own report numbers for the area (covered points, total loss,
  degrade by signal, by capacity, served, unknown cause);
- the comparison: the run's `no_backup` count against the truth's over the
  matched points; the run's mean `f_rsrp` against the truth's; the run's
  mean `f_prb` (estimated) against the truth's `f_prb_worst` and per hour.

Areas the run never queried get a row with the truth's aggregates and
`fetched = 0`: the cost of leaving them.

### 2.3 Class level

The run reports a class per point (total loss, degrade by signal, degrade
by capacity, both, served, unknown cause). The truth gets the same class
by the same rule, `completion_point.classify_locations`, with the
strongest reachable backup's *observed* PRB in the worst hour in place of
the estimate. A confusion matrix over the fetched points, run class
against truth class, is the class-level comparison; it says which
mistakes the run makes, not only how many.

### 2.4 Numbers per run

| number | definition |
|---|---|
| extent recall | fetched truth points / truth points in areas (points outside areas excluded) |
| extent recall, all | fetched truth points / all truth points (the design limit shows as the gap between the two) |
| backup agreement | mean `backup_jaccard` over fetched points |
| RSRP-fraction error | mean absolute `d_rsrp` over fetched points |
| PRB-fraction error | mean absolute `d_prb` over fetched points, worst hour and per hour |
| PRB per-backup error | mean absolute (estimated minus observed PRB) over backups and hours; and the share of backups where estimated and observed fall on different sides of 80 |
| class agreement | diagonal share of the confusion matrix; plus the two rates that matter to an operator: truth total loss reported as served (missed loss), and truth served reported as loss or degrade (false alarm) |
| cost | point calls, rounds, wall time, each also as a fraction of the ground truth's point calls |

---

## 3. The ground-truth figures

Two maps, as now, with the same frame, limits and colours as the
walkthrough page, plus a text panel on each.

**Map A, RSRP**: every extent point coloured by `f_rsrp`, green at 0 to red
at 1; `no_backup` points black; the site as a cross; area outlines when a
geography file exists. Title: `<site>, outage <start> to <end>: share of
reachable backups with RSRP degradation (> 10 dB or below -110 dBm)`.

**Map B, PRB**: the same points coloured by `f_prb_worst`; `no_backup`
black; `no_backup_data` hatched grey. Title: `... share of reachable
backups congested (PRB > 80 %) in the worst hour, <worst_hour>`.

**The text panel**, a box on the right of each map, eight lines, numbers
from the aggregates of section 1 and nothing else:

```
extent          1,284 points, 500 m inside the footprint, 1 km outside
outage set      ARL02850_aa_1, _ab_1, _ac_1 (3 of 6 sectors; 3 stayed up)
interval        2026-03-24 11:00 to 2026-03-25 02:00 UTC (15 h)
no backup       212 points (16.5 %)
degraded        mean share 0.31; 388 points (30 %) with share >= 0.5; 97 (7.6 %) with every backup degraded
congested       worst hour 18:00: mean share 0.42; 505 points (39 %) >= 0.5; 160 (12.5 %) every backup   [map B only]
backups         CCL06090_aa_1 reachable at 611 points, +212 RRC, PRB 86 % (congested 6 of 15 h); CCL06090_ab_1 ...  (top 3 by points)
KPI             3 backups with no data (listed in the report); 2 hours with no data for CCL06112_ab_1
```

Map A's panel carries the `degraded` line and not the `congested` one;
map B the reverse. Below each map, one line: `every statistic is in
ground_truth.json; the report lists them per area and per hour`.

**Map C, hours**: the PRB map for every outage hour as a strip, one small
map per hour with its mean share in the corner, so the reader sees when
the congestion peaks.

**The report** (`ground_truth_report.md`) carries the same numbers in
tables: section 1 the site aggregates per hour; section 2 per area when
areas exist; section 3 per backup the hourly table (observed RRC, gain,
PRB, congested); section 4 the KPI availability and the caveats.

---

## 4. Presenting and analysing the comparison

### 4.1 Figures per run

- **Three-panel maps**, one row for RSRP and one for PRB: truth, run,
  difference. The run panel colours fetched truth points by the run's
  fraction and marks `not_fetched_in_area` with a hollow circle and
  `not_fetched_outside_areas` with a dot; the difference panel colours
  `d_rsrp` or `d_prb` on a diverging scale, blue when the run
  underestimates, red when it overestimates, white at zero. The text panel
  on the difference map: extent recall (both), backup agreement, the two
  fraction errors, the two operator rates.
- **Per-area bars**: for each area, truth and run side by side for
  `no_backup` share, mean `f_rsrp`, mean `f_prb`; areas the run never
  queried shaded.
- **The confusion matrix** of classes, counts and row shares.
- **Per-backup scatter**: estimated PRB against observed PRB, one point per
  backup and hour, the 80 % lines drawn; the four quadrants are the four
  outcomes (both congested, both clear, missed congestion, false alarm).

### 4.2 Tables across runs and conditions

One table per condition (rendered, concat, concat_checked, rules), one row
per case, the numbers of section 2.4; a last row with mean and range. One
summary table across conditions with the means. Cases where the confirmed
outage set differed from the ticket are listed with a flag, since every
condition was given the confirmed set.

### 4.3 Reading the differences

Each disagreement at a point has one of four causes, and the matching
record says which:

1. **Not fetched** (`not_fetched_in_area`): an extent miss. The cause is
   the investigation's choice of areas or its stop; the completion check
   and the open items of the run's last round say why the area was left.
2. **Fetched, different backups** (`backup_jaccard < 1`): the same point
   sampled at a different time or radius returned different cells. Not
   the investigation's doing; it bounds how far point-level agreement can
   go, and the rules run shows the same effect.
3. **Same backups, different RSRP fraction**: should not occur, since the
   rule is the same on the same cells; a non-zero `d_rsrp` with
   `backup_jaccard = 1` is a bug in one side's computation.
4. **Same backups, different PRB fraction**: the redistribution estimate
   against the observed load. The per-backup scatter says whether the
   estimate is biased (points off the diagonal on one side) or noisy, and
   which backups it misjudges.

The analysis for the paper follows those four lines: how much of the
run's error is extent (1), how much is sampling that no strategy can
remove (2), and how much is the load model (4); then, across conditions,
which of the three the input format and the completion machinery change.
That is where the agent performs well or badly stated in terms the
design can act on: an extent miss is a strategy problem, a load error is a
model problem, and a sampling difference is a measurement limit.

---

## 5. What the Copilot builds

- `ground_truth.json` regenerated from samples and hourly KPI with the
  record of section 1; the aggregates; the three figures of section 3
  with their text panels; the report.
- `score_run.py <run dir> <ground truth dir>`: the matching of section 2,
  writing `score.json` (the numbers of 2.4, the per-point records, the
  per-area table, the confusion matrix) and the figures of 4.1.
- `summarize_scores.py <scores...>`: the tables of 4.2.

Constants shared with the investigation code: the 10 dB margin, the
-110 dBm threshold, the 80 % limit; one definition, imported from
`completion_point`.
