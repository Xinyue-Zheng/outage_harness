# Results table against the reference (instruction for the Copilot)

Add one module, `table.py`, to the existing package
`outage_harness_impact`. For one case it writes one table: one row per
run, and every share measured against the full-read reference (the
ground truth) of that case. It reads stored files only and makes no
data call.

The package was built from `Copilot_Impact_Score_and_Curve_2026-11-15.md`.
If the package does not exist, stop and report. `table.py` is the new
file that this instruction creates.

Changed on 2026-11-16: part 0 allows you to write two loaders if the
package does not have them.

## Rules

- New code goes only into `outage_harness_impact/table.py` and
  `outage_harness_impact/tests/`. Edit no other package.
- Reuse what the package has: the loading of a harness-type run, the
  exposure, the class and the severity with its state. Find these
  functions in `impact.py` and `curve.py` and call them. If one is
  inline in `curve.py`, move it into a function there without changing
  what `curve.py` writes. Do not copy code and do not write a second
  classification.
- The loader of a Copilot baseline run and the loader of the reference
  may be missing. Part 0 says what to write then. Apart from moving a
  function, do not change `curve.py`; it may keep rejecting a Copilot
  run, because this table replaces the curve in the report.
- Read stored files only. Write only under `--out`. Write nothing into
  a run folder or the reference folder.
- Do not run `uv sync`. Add no dependency. Do not use git.
- `TABLE_VERSION` is a string at the top of `table.py`, bumped by hand
  at every change of a rule below, and written to both outputs.

Run as

```
python -m outage_harness_impact.table --out <output folder> --reference <reference folder> [--geometry-from <harness run folder>] <label>=<run folder> [<label>=<run folder> ...]
```

One invocation covers one case. The labels are the row names, in the
order given. The same-case check of `curve.py` applies to every run,
the reference and the `--geometry-from` run: the same down cell IDs and
the same outage interval, compared as parsed times, not as text. If one
differs, stop and print both. `--geometry-from` is required when a
Copilot baseline run is among the runs, as in `curve.py`.

## 0. Two loaders, if the package does not have them

**The reference.** Find the reader that the evaluation package already
uses for the stored reference, and call it. From it, `table.py` needs
for every reference location: the grid id, the class, the reachable
backups with their issue flags, and the KPI rows that give the load of
a backup. Compute the severity with `impact.py`, as for a run. Write a
reader in `table.py` only if no reader exists, and say so in the
report.

**A Copilot baseline run.** Such a run stores less than a harness run:
its case has no site metadata, and its reads are keyed by coordinates,
not by harness grid ids. Write the loader in `copilot_state.py`. It
builds the input of the evaluation function for the run, and only when
`--geometry-from` names a stored harness run on the same case:

1. Same case. The down cell IDs and the outage interval of the Copilot
   run's `case.json` must equal those of the harness run's task. If
   they differ, stop and print both.
2. Geometry. Take the site metadata and the static geometry (the grid
   definition and the areas) from the harness run. A run that expanded
   its study area holds several geography files. Use the one that the
   run's final State refers to. Do not look anything up and do not
   derive a geometry.
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
   scored. It counts as queried, and the line under the table gives the
   count.

Fill only the State fields that the evaluation function reads, and list
them in the report. If a stored record lacks a value that the function
needs, stop and name it. Do not put in a default.

## 1. The sets

- `R`: every location of the reference, with its class, its severity
  and its exposure. The severity of a reference location comes from the
  reference's own samples and KPI.
- `Q`: every location charged to the run, with the class and the
  severity state that the run's own samples and KPI give.
- `Q_in`: the locations of `Q` that are in `R`, matched by grid id.
  The locations of `Q` that are not in `R` are "outside the reference".
  They count as queried and enter no share.

A location is **covered** when its class is one of the two covered
classes. A location is **found** by the run when it is in `Q_in`, the
run's class is covered, and the reference's class is covered.

## 2. The columns

| column | value |
|---|---|
| `locations_queried` | the size of `Q` |
| `covered_found` | locations of `Q` whose class in the run is covered |
| `hit_rate` | `covered_found` / `locations_queried` |
| `coverage_recall` | found locations / covered locations of `R` |
| `no_backup_recall` | found locations whose class is covered with no backup in the run and in the reference / locations of `R` with that class |
| `located_impact` | sum over the found locations of exposure times reference severity / the same sum over all of `R` |
| `reportable_impact` | the same sum over the found locations whose severity the run can state / the same sum over all of `R` |
| `seconds` | seconds elapsed at the end of the run, from the step list of `curve.py`; `not recorded` if the records hold no time |
| `end_reason` | the end reason in the run record, as written there. For a Copilot baseline run: `report submitted` if a report was accepted, else the limit that ended it, else `no report` |

The run can state the severity of a location when its state is not
`not_determined` and its own severity equals the reference severity.

A share whose denominator is 0 is `not available`. Do not write 0 or
100 for it.

Above the table, one line gives the reference: locations, locations
with a sample, covered locations, covered locations with no backup, and
the total impact with the exposure weight and with the equal weight.

## 3. Outputs, in `<out>/`

- `results_table.md`: the reference line, then the table with the nine
  columns above, shares as percent with one decimal. Under the table,
  one line per run: locations outside the reference, locations of
  `Q_in` whose class differs between the run and the reference, and
  locations in the state `not_determined`. The file states that the
  impact columns use the exposure weight and the reference severity.
- `results_table.csv`: one row per run with the same columns, every
  numerator and denominator, the two impact shares with the equal
  weight, and `TABLE_VERSION`.

## 4. Tests, synthetic, under `tmp_path`

1. A reference of ten hand-built locations and a run that read five of
   them: every column equals the value computed by hand.
2. A run with one location outside the reference and one location
   whose class differs from the reference: both appear in the line
   under the table, neither enters a share, and no share is above 1.
3. The same run without its KPI step and with it: `located_impact` is
   equal in both, `reportable_impact` is lower without the KPI step.
4. A reference with no location of the class covered with no backup:
   `no_backup_recall` is `not available`.
5. A synthetic Copilot baseline run with `--geometry-from` gives the
   same row as the harness run with the same samples and KPI rows. A
   Copilot run of another case stops and prints both cases. A read 5 m
   from its cell centre stops with the count and the distance.

Gate on the changed package: `uv run ruff format`,
`uv run ruff check --fix`, `uv run ty check`.

## 5. Report back

First, ready to copy: the exact command for every case of the author's
message, one per case, with the author's paths filled in. Run them, and
print `results_table.md` of each case.

Then: the change list as file and line; which existing functions
`table.py` calls; where the end reason of each run type comes from;
anything that could not be done as written. State it, and do not work
around it.

## The author's message

The author sends this with the instruction, with the folders filled in.
A case with no Copilot baseline run has no `copilot_agent` line and no
geometry line.

```
Apply Copilot_Results_Table_2026-11-16.md. Then run it for the cases
below and show me results_table.md of each.

Case 1
  reference: <reference folder of this case>
  output:    <output folder for this case>
  runs:
    harness_llm   = <run folder>
    harness_rule  = <run folder>
    greedy_rule   = <run folder>
    codex_style   = <run folder>
    copilot_agent = <Copilot baseline run folder, the one that holds records/>
  geometry for the Copilot run: <one harness run folder of this case>

Case 2
  reference: <reference folder of this case>
  output:    <output folder for this case>
  runs:
    harness_llm   = <run folder>
    harness_rule  = <run folder>
    greedy_rule   = <run folder>
    codex_style   = <run folder>
    copilot_agent = <Copilot baseline run folder, the one that holds records/>
  geometry for the Copilot run: <one harness run folder of this case>

Case 3
  reference: <reference folder of this case>
  output:    <output folder for this case>
  runs:
    harness_llm   = <run folder>
    harness_rule  = <run folder>
    greedy_rule   = <run folder>
    codex_style   = <run folder>
```
