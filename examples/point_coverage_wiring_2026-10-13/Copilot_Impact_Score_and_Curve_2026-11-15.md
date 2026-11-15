# Impact score and impact curve (instruction for the Copilot)

Build one new package, `outage_harness_impact`, that gives every
location an impact score and shows, for any stored run, how much impact
the run had located and how much it could report after each step. It
reads stored data only. It edits no other package and makes no data
call.

If the package already exists from an earlier version of this
instruction, change it to match this version. Changed on 2026-11-15:
the located and the reportable curve (parts 2 to 4), the time axis
(part 4), and the commands in the report (part 6).

A second instruction, `Copilot_Impact_Facts_In_Context_2026-11-15.md`,
uses `impact.py` of this package. You do not need that file for this
one.

Why. The runs are compared today by whether they complete and by how
many locations they spend. Neither shows whether a run found the
important places early, or whether it can report what it found. A run
that never queries KPI can report a location with no backup, but it
cannot say whether a backup is overloaded. The two curves show both.

## Rules

- New code goes only into `outage_harness_impact/`: `impact.py`,
  `curve.py`, `copilot_state.py`, `tests/`. Import the harness and
  evaluation packages read-only. Do not copy code.
- Read stored files only: the map copy of the case, the step records,
  samples and KPI rows of each run, the reference. Write only under
  `--out`. Write nothing into a run directory.
- Do not run `uv sync`. Add no dependency. Do not use git.
- `IMPACT_VERSION` is a string at the top of `impact.py`, bumped by hand
  at every change of a constant or a rule below, and written to every
  output.

Run as

```
python -m outage_harness_impact.curve --out <output folder> [--reference <reference folder>] [--geometry-from <harness run folder>] <run folder> [<run folder> ...]
```

One invocation covers one case. All run folders given, the reference
and the `--geometry-from` run must be on the same case: the same down
cell IDs and the same outage interval. If one differs, stop and name
it. Run the command once per case, each with its own `--out` folder.

## 1. The score (`impact.py`)

```
impact(x) = weight(x) * severity(x)
```

Every function in `impact.py` is pure. All numbers below are constants
at the top of the file. They are draft values that the author will
revise; nothing else in the code may depend on their size.

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

## 2. Severity, and when it is determined

Take the class, the reachable backups and the `rsrp_issue` flag of each
backup from the function that the evaluation already uses for its
per-point record (`ground_truth_outputs.py`). Take the load problem of
a backup (`prb_issue` in the worst outage hour) as the evaluation
computes it for a run. Do not write a second classification.

For a covered location, call the reachable backups without
`rsrp_issue` its good-signal backups. The load of a backup is, from the
KPI the run holds at a given step:

| load state | meaning |
|---|---|
| `problem` | KPI rows held, `prb_issue` true |
| `no problem` | KPI rows held, `prb_issue` false |
| `not available` | the KPI query succeeded and returned no rows |
| `not asked` | no KPI query for this cell so far, or the query failed |

The severity of a read location, and the step at which the run can
state it:

| location | severity | determined |
|---|---|---|
| not covered, no sample, or error | 0 | when read |
| covered, no reachable backup | 1.0 | when read |
| covered, no good-signal backup | 0.5 | when read |
| covered, a good-signal backup with load `no problem` | 0.1 | at the later of the read and the step that brought that KPI |
| covered, every good-signal backup with load `problem` | 0.5 | at the later of the read and the step that brought the last of that KPI |
| covered, no good-signal backup is `no problem` or `not asked`, and at least one is `not available` | 0.1, flagged `load_not_available` | at the later of the read and the step that brought the last of that KPI |
| covered, otherwise | 0.1, flagged `not_determined` | never |

`severity_at(location, kpi_held)` returns the severity and its state as
a pure function. The states are a `Literal`: `at_read`, `after_kpi`,
`load_not_available`, `not_determined`.

## 3. Two curves for one run (`curve.py`)

1. Find the kind of run folder from the files in it: a harness-type run
   (the harness, the rule package, a transcript package) has step
   records and States; a Copilot baseline run has `records/reads.jsonl`.
   If it is neither, stop and name the folder.
2. List the steps of the run in order. For each step: its kind
   (coverage, KPI, other), the locations charged in it, the KPI cells
   it brought, the locations spent after it, and the seconds elapsed
   since the run's clock started. If the records hold no time, the
   seconds are `not recorded`.
3. For each charged location compute the exposure counts and, with the
   KPI the run holds at the end, the severity and its state.
4. **Located impact** of a location is its weight times its severity.
   It counts from the step that read the location.
5. **Reportable impact** of a location is the same value. It counts
   from the step at which the severity was determined. A location that
   is `not_determined` never counts.

Reportable impact is therefore never above located impact. The
difference is what the run found and cannot state.

Outputs per run, in `<out>/<run name>/`:

- `impact_locations.csv`, one row per charged location: read order,
  step read, grid id, class, severity, state, step determined, the four
  exposure counts, exposure, impact for both weights.
- `impact_series.csv`, one row per step: step, kind, locations spent,
  seconds elapsed, cumulative located impact and cumulative reportable
  impact, for both weights.

With `--reference`, also compute the total impact over all locations of
the reference, for both weights, with the reference's own samples and
KPI, and add each cumulative value as a share of that total. Without
it, the shares are `not available`, and the summary says so.

**A Copilot baseline run** stores less than a harness run: its case has
no site metadata, and its reads are keyed by coordinates, not by
harness grid ids. `copilot_state.py` builds the input of the evaluation
function for such a run, and only when `--geometry-from` names a stored
harness run on the same case:

1. Same case. The down cell IDs and the outage interval of the Copilot
   run's `case.json` must equal those of the harness run's task. If
   they differ, stop and print both.
2. Geometry. Take the site metadata and the static geometry (the grid
   definition and the areas) from the harness run. A run that expanded
   its study area holds several geography files (`geography.json`,
   `geography_v2.json`, ...). Use the one that the run's final State
   refers to, which is the largest. Confirm that a grid id names the
   same cell in every version of that run, and say so in the report; if
   it does not, stop. Do not look anything up and do not derive a
   geometry.
3. Grid ids. Map the coordinate of every Copilot read to a harness grid
   id with the harness grid function. If the distance between a read
   coordinate and the centre of its grid cell is above
   `MAX_CENTRE_OFFSET_M = 1.0`, stop and report the count and the
   largest distance.
4. Coverage and KPI. Put the samples of `records/samples.jsonl` under
   the mapped grid ids, and the rows of `records/kpi.json`, in the form
   the harness State uses, with the harness's own constructors. The
   steps of a Copilot run are its tool calls in `records/calls.jsonl`.
5. A read whose grid cell is outside the harness geometry is not
   scored. Write the count into the summary, by name: "outside the
   harness geometry, not scored".

Write the mapping to `<out>/<run name>/grid_mapping.csv`. Fill only the
State fields the evaluation function reads, and list them in the
report. If a stored record lacks a value the function needs, stop and
name it; do not put in a default. A Copilot run folder given without
`--geometry-from` is an error that names the argument.

## 4. The summary and the charts

`<out>/impact_summary.md`, one column per run, for each weight:

- locations spent, and the run's location limit;
- located impact and reportable impact at 25, 50 and 100 percent of the
  limit;
- the area under each curve: the mean of the cumulative value over the
  locations 1 to the limit, with the last value held after the run
  ended;
- the reportable share at the end: reportable impact divided by located
  impact;
- the count of locations per state: `at_read`, `after_kpi`,
  `load_not_available`, `not_determined`;
- whether the run made a KPI query, and the step of the first one;
- with a reference: the values above as shares of the total, and the
  share never located;
- for the exposure weight: the located impact split by item (building,
  critical place, other place, major road);
- seconds elapsed at the end, and the seconds at which the run reached
  half of its final reportable impact.

Two charts, plain SVG written by the script, no plotting library. Each
has two panels, `equal` and `exposure`, and for every run two lines in
the run's colour: located impact as a solid line, reportable impact as
a dashed line.

- `<out>/impact_curves.svg`: x is the locations spent.
- `<out>/impact_curves_time.svg`: x is the seconds elapsed. A run
  without recorded time is left out and named under the chart.

## 5. Tests, synthetic

1. Exposure of a cell with 4 buildings, 1 school, 2 shops, in a primary
   road corridor: 4 + 10 + 6 + 3 = 23. A cell in a motorway corridor
   and a secondary corridor gets 5 once.
2. Severity and state, the seven rows of the table of part 2, each on a
   hand-built location.
3. A run of six locations whose KPI step comes last: the located curve
   rises at each read; the reportable curve rises at the reads only for
   the locations determined when read, and steps up at the KPI step.
4. The same run without its KPI step: the locations that needed KPI are
   `not_determined`, the reportable share is the hand-computed value
   below 1, and the located curve is unchanged except for the severity
   of those locations.
5. With a synthetic reference, the shares end at the hand-computed
   value, and the area under the curve holds the last value up to the
   limit.
6. A synthetic Copilot run folder, with `--geometry-from` a synthetic
   harness run of the same case and the same samples and KPI rows,
   gives the same two curves as that harness run. A Copilot run of
   another case stops and prints both cases. A read 5 m from its cell
   centre stops with the count and the distance.

Gate on the new package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 6. Report back

First, ready to copy: the exact command for every case the author
named, one per case, with the author's paths filled in. Then the
command pattern for a further run or case. Run the commands unless the
author's message says to print them only.

Then: the change list as file and line; which evaluation function gave
the class and the issue flags, and which State fields it reads; which
map features the stored copy holds (buildings, amenities, shops,
leisure, tourism, roads) and which exposure item could therefore not be
counted; where the step time comes from; and `impact_summary.md` of
each case that was run.
