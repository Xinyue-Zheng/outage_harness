# Impact score and impact curve (instruction for the Copilot)

Apply this instruction first. A second instruction,
`Copilot_Impact_Facts_In_Context_2026-11-15.md`, builds on it later.
You do not need that file for this one.

Build one new package, `outage_harness_impact`, that gives every
location an impact score and draws, for any stored run, how much impact
the run had found after each location it spent. It reads stored data
only. It edits no other package and makes no data call.

Why. The runs are compared today by whether they complete and by how
many locations they spend. Neither shows whether a run found the
important places early. The impact curve does.

## Rules

- New code goes only into `outage_harness_impact/`: `impact.py`,
  `curve.py`, `copilot_state.py`, `tests/`. Import the harness and
  evaluation packages read-only. Do not copy code.
- The evaluation function that gives the per-point record
  (`ground_truth_outputs.py`) reads a harness State with the task, the
  site metadata, the geometry and the coverage. For a harness-type run,
  pass the run's own stored State.
- A Copilot baseline run stores less: its case has no site metadata,
  and its reads are keyed by coordinates, not by harness grid ids.
  `copilot_state.py` builds the State input for such a run from two
  sources, and only when `--geometry-from` names a stored harness run
  on the same case:
  1. Same case. The down cell IDs and the outage interval of the
     Copilot run's `case.json` must equal those of the harness run's
     task. If they differ, stop and print both.
  2. Geometry. Take the site metadata and the static geometry (the grid
     definition and the areas) from the harness run. A run that
     expanded its study area holds several geography files
     (`geography.json`, `geography_v2.json`, ...). Use the one that the
     run's final State refers to, which is the largest. Confirm that a
     grid id names the same cell in every version of that run, and say
     so in the report; if it does not, stop. Do not look anything up
     and do not derive a geometry.
  3. Grid ids. Map the coordinate of every Copilot read to a harness
     grid id with the harness grid function. Compute the distance
     between the read coordinate and the centre of that grid cell. If
     any distance is above `MAX_CENTRE_OFFSET_M = 1.0`, stop and report
     the count and the largest distance: the samples were then taken at
     another point than the harness reads, and the author decides.
  4. Coverage and KPI. Put the samples of `records/samples.jsonl` under
     the mapped grid ids, and the rows of `records/kpi.json`, in the
     form the harness State uses, with the harness's own constructors.
  5. A read whose grid cell is outside the harness geometry is not
     scored. Write the count of such reads into the summary, by name:
     "outside the harness geometry, not scored".

  Write the mapping to `<out>/<run name>/grid_mapping.csv`: the read
  order, the stored coordinate key, the grid id, the offset in metres.
  Fill only the State fields the evaluation function reads, and list
  them in the report. If a stored record lacks a value the function
  needs, stop and name it; do not put in a default. A Copilot run
  folder given without `--geometry-from` is an error that names the
  argument.
- Read stored files only: the map copy of the case, the samples and KPI
  rows of each run, the reference. Write only under `--out`. Write
  nothing into a run directory.
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
5. A synthetic Copilot run folder, with `--geometry-from` a synthetic
   harness run of the same case and the same samples and KPI rows,
   gives the same per-point records and the same curve as that harness
   run.
6. A Copilot run whose case differs from the harness run stops and
   prints both cases. A read 5 m from its cell centre stops with the
   count and the distance. A read outside the geometry is counted as
   not scored.

Gate on the new package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 5. Report back

The change list as file and line. Which evaluation function gave the
class and the issue flags, and which State fields it reads. Which map features the stored copy holds
(buildings, amenities, shops, leisure, tourism, roads) and which of the
exposure items could therefore not be counted. Then `impact_summary.md`
for the runs the author names.
