# Impact of a Copilot baseline run, from its stored records (instruction for the Copilot)

This is a small task with a deadline. Write one script,
`copilot_impact.py`, run it for the cases of the author's message, and
print the result. Do nothing else.

The script computes the located impact and the reportable impact of a
Copilot baseline run from the records that the run already stored. It
starts no run and calls no model.

## Rules

- Create only `copilot_impact.py`, in the script folder that the
  author's message names. It is a script, not a package module. Do not
  edit, finish or repair any other file, including `quick_table.py`,
  `table.py`, `copilot_state.py`, `curve.py` and `impact.py`.
- Write no test. Do not refactor. Keep the file short.
- Read stored files only. Make no point call, no KPI call and no map
  call. Write only under `--out`. Write nothing into a run folder.
- Do not import `outage_harness_copilot`: its modules import `fastmcp`.
  Read the record files of the Copilot run directly with `json`.
- Do not build a harness State. Do not write a second exposure rule or
  a second classification: call the functions that
  `outage_harness_impact` already has.
- Do not run `uv sync`. Add no dependency. Do not use git.
- If an import fails, or a stored file lacks a value named below, stop
  and report the error as it is. Do not repair it and do not put in a
  default.

Run as

```
python <script folder>/copilot_impact.py --out <output folder> --harness-run <harness run folder> <label>=<Copilot run folder> [<label>=<Copilot run folder> ...]
```

Use the Python of the project environment, with the repository root on
`PYTHONPATH`. One invocation covers one case.

**Order of work.** Write parts 1 to 3 and part 5, run the command for
every case, and print the output. Only then do part 4, and run again.

## 1. The case

Print, for the harness run and for every Copilot run, the down cell IDs
and the outage interval as stored. If the set of down cell IDs of a
Copilot run differs from that of the harness run, stop and print both.
Do not compare the intervals as text.

## 2. The exposure of each location read

`--harness-run` names a stored harness run of the same case. Load it
and compute the exposure table of the case with the same calls that
`curve.py` makes for a harness run (`exposure_table`). The table gives
the exposure of a location by grid id.

For every line of `records/reads.jsonl` of the Copilot run, take the
grid id. If the line holds no harness grid id, map its centre to a grid
id with the grid function that `exposure_table` uses.

- If no covered read of a run has its grid id in the table, stop and
  print three grid ids of the reads and three grid ids of the table.
- A covered read whose grid id is not in the table has no exposure. It
  enters the equal-weight sums and not the exposure-weight sums. Print
  the count.

A location is covered when its class in `reads.jsonl` is
`covered_backup` or `covered_no_backup`.

## 3. Severity from the class alone

| class in `reads.jsonl` | severity | state |
|---|---|---|
| `covered_no_backup` | 1.0 | `at_read` |
| `covered_backup` | between 0.1 and 0.5, until part 4 | `not_determined`, until part 4 |
| any other class | 0 | not counted |

With this part alone, the output of part 5 gives a range:

- located impact, low: every `covered_backup` location at 0.1; high:
  every `covered_backup` location at 0.5;
- reportable impact: the `covered_no_backup` locations only, marked
  "at least".

## 4. Exact severity of the locations with a backup

Do this part only if the two functions below accept the stored rows
directly, or through their own constructors in a few lines. If one of
them needs a harness State, do not do this part: keep the range of
part 3, and name in the report the function and the input that it
needs.

1. For every `covered_backup` location, get its reachable backups and
   the `rsrp_issue` flag of each from the function that `curve.py` uses
   for a harness-type run. Pass it the samples of that grid id from
   `records/samples.jsonl`.
2. The load state of a backup cell comes from `records/kpi.json`:
   status `rows` gives `problem` or `no problem` with the `prb_issue`
   that the evaluation computes for a run; status `no_rows` gives
   `not available`; status `failed`, or a cell in no KPI call, gives
   `not asked`.
3. Call `severity_at` of `impact.py` with the KPI that the run holds at
   its end. It returns the severity and the state.

Then the located impact is exact, and the reportable impact is the sum
over the locations whose state is not `not_determined`.

## 5. Output

Write `<out>/copilot_impact.md` and print it:

1. The case lines of part 1.
2. One table, one row per Copilot run:

   | column | value |
   |---|---|
   | `locations_queried` | the number of lines of `records/reads.jsonl` |
   | `covered_found` | reads with a covered class |
   | `no_backup_found` | reads with the class `covered_no_backup` |
   | `located_impact_exposure` | sum of exposure times severity over the covered reads that have an exposure |
   | `reportable_impact_exposure` | the same sum over the locations whose state is not `not_determined` |
   | `located_impact_equal` | sum of severity over all covered reads |
   | `reportable_impact_equal` | the same sum over the locations whose state is not `not_determined` |

   With part 3 alone, a located cell is `<low> to <high>` and a
   reportable cell is `at least <value>`.
3. Per run, one line each: the covered reads with no exposure; the
   count of locations per state; and "severity: exact" or "severity:
   range, part 4 not done".
4. One line: "The exposure of a Copilot baseline run comes from the
   exposure table of the harness run on the same case. Impact is a sum,
   not a share of a reference."

## 6. Report back

Only this: the command of each case with the author's paths filled in,
and the printed output of each case. Say whether part 4 was done. If
you stopped, the error as it is.

## The author's message

```
Apply Copilot_Agent_Impact_Quick_2026-11-16.md. It is urgent: write the
one script, run it for the cases below, and print the output.

repository root: <repository root>
script folder:   <the Copilot baseline folder>

Case 1
  output:      <output folder for this case>
  harness run: <one harness run folder of this case>
  runs:
    copilot_agent   = <Copilot baseline run folder, the one that holds records/>
    copilot_agent_2 = <second Copilot baseline run folder, if there is one>

Case 2
  output:      <output folder for this case>
  harness run: <one harness run folder of this case>
  runs:
    copilot_agent = <Copilot baseline run folder, the one that holds records/>
```
