# Quick results table, without the reference (instruction for the Copilot)

This is a small task with a deadline. Write one new file,
`outage_harness_impact/quick_table.py`, run it for the cases of the
author's message, and print the tables. Do nothing else.

This task replaces `Copilot_Results_Table_2026-11-16.md` for now. Do not
continue that task.

## Rules

- Create only `outage_harness_impact/quick_table.py`. Do not edit,
  finish or repair any other file, including `table.py`,
  `copilot_state.py` and `curve.py`.
- Write no test. Do not refactor. Keep the file short.
- Read stored files only. Make no data call. Do not read a reference.
  Write only under `--out`.
- Do not run `uv sync`. Add no dependency. Do not use git.
- If an import of the package fails, or a stored file lacks a value
  named below, stop and report the error as it is. Do not repair it and
  do not put in a default.

Run as

```
python -m outage_harness_impact.quick_table --out <output folder> <label>=<run folder> [<label>=<run folder> ...]
```

One invocation covers one case. The labels are the row names, in the
order given.

## 1. A harness-type run

A harness-type run is a run of the harness, a rule package or a
transcript package. Call the functions that `curve.py` already uses for
such a run: the step list with the seconds elapsed, and the row of
every charged location with its class, its exposure, its severity and
its state. From them:

| column | value |
|---|---|
| `locations_queried` | the number of charged locations |
| `covered_found` | charged locations whose class is one of the two covered classes |
| `hit_rate` | `covered_found` / `locations_queried`, as percent with one decimal; `not available` when no location was charged |
| `no_backup_found` | charged locations whose class is covered with no backup |
| `located_impact` | sum of exposure times severity over the charged locations |
| `reportable_impact` | the same sum over the locations whose state is not `not_determined` |
| `seconds` | seconds elapsed at the end of the run; `not recorded` if the records hold no time |
| `end_reason` | the end reason in the run record, as written there |

## 2. A Copilot baseline run

A Copilot baseline run has `records/reads.jsonl`. Do not convert it to
a harness State and do not use `--geometry-from`. Read its records
directly, with the reader of `outage_harness_copilot` if that package
has one:

| column | value |
|---|---|
| `locations_queried` | the number of lines of `records/reads.jsonl` |
| `covered_found`, `no_backup_found` | counted from the class of each line, with the same class names |
| `hit_rate` | as in part 1 |
| `located_impact`, `reportable_impact` | `not available` |
| `seconds` | the total seconds that `summary.py` of that package reports |
| `end_reason` | `report submitted` if a report was accepted; else the limit that ended the run; else `no report` |

## 3. Output

Write `<out>/quick_table.md` and print it:

1. One line per run: the label, the down cell IDs and the outage
   interval of the run, as stored, so that the author can see that all
   runs are on the same case. Do not compare them.
2. The table, one row per run, with the eight columns above.
3. One line: "Impact uses the exposure weight. It is a sum, not a share
   of a reference."

## 4. Report back

Only this: the command of each case with the author's paths filled in,
and the printed table of each case. If you stopped, the error as it is.

## The author's message

```
Apply Copilot_Quick_Results_Table_2026-11-16.md. It is urgent: write the
one file, run it for the cases below, and print the tables.

Case 1
  output: <output folder for this case>
  runs:
    harness_llm   = <run folder>
    harness_rule  = <run folder>
    greedy_rule   = <run folder>
    codex_style   = <run folder>
    copilot_agent = <Copilot baseline run folder, the one that holds records/>

Case 2
  output: <output folder for this case>
  runs:
    harness_llm   = <run folder>
    harness_rule  = <run folder>
    greedy_rule   = <run folder>
    codex_style   = <run folder>
    copilot_agent = <Copilot baseline run folder, the one that holds records/>

Case 3
  output: <output folder for this case>
  runs:
    harness_llm   = <run folder>
    harness_rule  = <run folder>
    greedy_rule   = <run folder>
    codex_style   = <run folder>
```
