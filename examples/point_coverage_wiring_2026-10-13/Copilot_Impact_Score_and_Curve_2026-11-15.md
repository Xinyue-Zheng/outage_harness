# Impact score and impact curve (instruction for the Copilot)

Apply this instruction first. `Copilot_Impact_Facts_In_Context_2026-11-15.md`
builds on it.

Build one new package, `outage_harness_impact`, that gives every
location an impact score and draws, for any stored run, how much impact
the run had found after each location it spent. It reads stored data
only. It edits no other package and makes no data call.

Why. The runs are compared today by whether they complete and by how
many locations they spend. Neither shows whether a run found the
important places early. The impact curve does.

## Rules

- New code goes only into `outage_harness_impact/`: `impact.py`,
  `curve.py`, `tests/`. Import the harness and evaluation packages
  read-only. If a function cannot be called without a harness State,
  stop and report which one. Do not copy code.
- Read stored files only: the map copy of the case, the samples and KPI
  rows of each run, the reference. Write only under `--out`. Write
  nothing into a run directory.
- Do not run `uv sync`. Add no dependency. Do not use git.
- `IMPACT_VERSION` is a string at the top of `impact.py`, bumped by hand
  at every change of a constant or a rule below, and written to every
  output.

Run as

```
python -m outage_harness_impact.curve --out <output folder> [--reference <reference folder>] <run folder> [<run folder> ...]
```

## 1. The score (`impact.py`)

```
impact(x) = weight(x) * severity(x)
```

Every function in `impact.py` is pure. All numbers below are constants
at the top of the file. They are draft values that the author will
revise; nothing else in the code may depend on their size.

**Severity**, from the class of a read location:

| condition | severity |
|---|---|
| covered by an outage cell, no reachable backup | 1.0 |
| covered, and every reachable backup has a problem | 0.5 |
| covered, and at least one reachable backup has no problem | 0.1 |
| not covered by an outage cell | 0 |
| no sample, or error | 0 |

A backup has a problem when the evaluation record marks it with
`rsrp_issue`, or with `prb_issue` in the worst outage hour. A backup
without KPI data is judged by `rsrp_issue` alone, and the location is
flagged `load_unknown`. Take the class, the reachable backups and the
two issue flags from the function that the evaluation already uses for
its per-point record. Do not write a second classification.

**Weight**, two variants, both always computed:

| name | weight |
|---|---|
| `equal` | 1 for every location |
| `exposure` | the exposure of the location, below |

**Exposure** of a location is a sum over what the map shows inside its
100 m cell:

| item | counted from the stored map copy | points each |
|---|---|---|
| building | mapped buildings whose centre lies in the cell | 1 |
| critical place | `amenity` in hospital, clinic, fire_station, police, school, kindergarten, college, university, nursing_home | 10 |
| other place | any other `amenity`, and any `shop`, `leisure` or `tourism` feature | 3 |
| major road | the cell lies in a road corridor area: motorway or trunk 5, primary 3, secondary 2; the highest class once | 5, 3 or 2 |

Exposure describes what is at a place. It is not a measure of demand or
of users, and no output may call it that. The building count stands in
for population; `people_in_cell()` is the one function to replace when
a population dataset is available.

`exposure_table(case) -> dict[grid id, ExposureCounts]` computes the
four counts for every location of the case with the harness grid
function and the stored map copy, once per case, and `curve.py` writes
it to `<out>/exposure.json`.

## 2. The curve of one run (`curve.py`)

1. Find the kind of run folder from the files in it: a harness-type run
   (the harness, the rule package, a transcript package) has step
   records and States; a Copilot baseline run has `records/reads.jsonl`.
   If it is neither, stop and name the folder.
2. List the locations the run was charged for, in the order it was
   charged, each with the step that read it.
3. For each one compute the class, the severity, the exposure counts and
   the two impact values, from the run's own stored samples and KPI
   rows.
4. Write `<out>/<run name>/impact_curve.csv`, one row per charged
   location: order, step, grid id, class, severity, `load_unknown`, the
   four exposure counts, exposure, and the cumulative impact for both
   weights.

With `--reference`, also compute the total impact over all locations of
the reference, for both weights, and add the cumulative share of that
total to each row. Without it, the shares are `not available`, and the
summary says so.

## 3. The summary across runs

`<out>/impact_summary.md`, one column per run, for each weight:

- locations spent, and the run's location limit;
- impact found at 25, 50 and 100 percent of the limit;
- the area under the curve: the mean of the cumulative impact over the
  locations 1 to the limit, with the last value held after the run
  ended;
- with a reference: the same values as shares of the total, and the
  share never found;
- for the exposure weight: the impact found split by item (building,
  critical place, other place, major road);
- the count of `load_unknown` locations.

`<out>/impact_curves.svg`: two panels, `equal` and `exposure`; x is the
locations spent, y is the cumulative impact (the share when a reference
is given); one line per run with its name. Plain SVG written by the
script; no plotting library.

## 4. Tests, synthetic

1. Exposure of a cell with 4 buildings, 1 school, 2 shops, in a primary
   road corridor: 4 + 10 + 6 + 3 = 23. A cell in a motorway corridor
   and a secondary corridor gets 5 once.
2. Severity: the five rows of the table; a covered location whose only
   backup has no KPI data and no `rsrp_issue` gives 0.1 and
   `load_unknown`.
3. A synthetic run of six charged locations gives the cumulative values
   computed by hand for both weights, in charge order.
4. With a synthetic reference, the shares end at the hand-computed
   value, and the area under the curve holds the last value up to the
   limit.

Gate on the new package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 5. Report back

The change list as file and line. Which evaluation function gave the
class and the issue flags. Which map features the stored copy holds
(buildings, amenities, shops, leisure, tourism, roads) and which of the
exposure items could therefore not be counted. Then `impact_summary.md`
for the runs the author names.
