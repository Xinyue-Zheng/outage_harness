# Program recovery at the rejection cap: an optional third condition, with resume from a stuck run

Apply to `outage_harness_langgraph` only; the rule core has no rejection
path that this concerns. Synthetic fixtures and tests; no real cases.
Report every change as file and line. Builds on
`Copilot_Rejection_Handling_2026-10-31.md` and
`Copilot_Legal_Actions_Per_Bin_2026-10-31.md`. No completion rule
changes.

## A run is in progress while you make this change

Do not touch any file the running process reads per round: skill text,
prompt templates, configuration files, `unit_costs.json`, anything under
a run directory. Add the new skill sentence only inside the branch that
the flag enables, and keep the current skill text byte-identical when
the flag is off. Point tests at a scratch output directory, not at the
live output directory. Do not run `uv sync` or rebuild the environment
while the run is in progress. Say in the report which files you
changed and confirm none of them is read per round by the runner.

## Why

A model run ended `rejection_cap` at a round where the context showed
one open item with one legal action, and the model proposed a different
direction three times. The pure model core must keep ending there, so
the failure stays visible. A separate condition continues such a run by
letting the program execute the one legal action, and records every
such intervention, so the result table can show how often the model
core needs rescue.

## 1. Flag

`RECOVERY`, values `none` (default) and `program`, read once at run
start, recorded in `run.json` under `limits` next to the caps. With
`none`, every code path is as today. The rule core ignores the flag and
records `none`.

## 2. Behaviour with `program`

In the place where the run would end `rejection_cap`, that is after the
third consecutive rejection:

1. Build the legal action set for the current state from
   `legal_requests` over every open item, plus `expand` for every bin
   that is `open_at_edge`, plus `query_kpi` for the pending cell set when
   a KPI item is open, plus `finish` when the completion check passes.
2. If the set has exactly one action, the program executes it: the same
   validate, execute, update, write-step path as a model action. The
   step record carries `decided_by: "program"` and `recovery_reason:
   "rejection_cap_single_legal_action"`, with the three rejected actions
   it replaced. The consecutive-rejection counter resets to zero. The
   run continues; the next round is a normal model round.
3. If the set has more than one action or is empty, the run ends
   `rejection_cap` as today, and `run.json` records
   `recovery_not_applicable` with the legal action count.

An identical rejection means the same action and parameters three times.
Three different rejected actions end the run as today under either flag
value; recovery applies to the repeated case only.

No model call is made for a program decision. The decision accounting
records no entry for that round; the step record's `decision` block is
absent and `decided_by` says why.

## 3. Rendering after an intervention

The next round's context opens with a fixed block in place of
`Last action rejected`:

```
Program action last round: expand bin WTL03023/3 (the only legal action after three rejected proposals: expand bin WTL03023/2).
```

The budget block is unchanged. The skill text, in the `program` branch
only, gains one sentence: "If you propose an illegal action three
times, the program executes the only legal action when there is exactly
one, and tells you so."

## 4. Accounting

`run.json` gets `interventions`: one entry per program action with the
round, the executed action, the three rejected actions and their
messages. `resources` gets `intervention_count`. The report tables show
`interventions` as a column next to rejections, for the model core
only. A run with `intervention_count > 0` is labelled condition
`model+program` in every table and figure; a run with 0 under
`RECOVERY=program` is labelled the same, because the condition is the
flag, not the outcome.

## 5. Tests

1. `RECOVERY=none`: the whole existing test suite passes unchanged, and
   a state with three identical rejected proposals ends `rejection_cap`.
2. `RECOVERY=program`, hand-built state with one open item whose only
   legal action is `expand` on one bin, three identical rejected
   proposals: the program executes the expand, the step record has
   `decided_by program` and the three rejected actions, the counter is
   zero, and the run continues to a model round whose context opens
   with the block of part 3.
3. Same with two legal actions: the run ends `rejection_cap` and
   `run.json` has `recovery_not_applicable` with count 2.
4. Three different rejected actions under `program`: the run ends
   `rejection_cap`.
5. A program round adds no entry to `decisions` and no decision seconds.
6. `run.json` `interventions` has one entry per program action and
   `intervention_count` matches; the condition label is `model+program`
   under the flag even with zero interventions.
7. With the flag off, the skill text sent to the model is byte-identical
   to the current text.
8. Resume: a synthetic run directory ended `rejection_cap` is resumed
   into a new directory; the source is byte-identical after the resume;
   the copy has `resumed_from`, `resumed_at_round`, carried-over
   counters, and its first step is a program action with
   `decided_by program` and `resumed true`.
9. Resume refuses an existing target directory and a source that ended
   with any reason other than `rejection_cap`.

## 6. Resume from a stuck run

A run that ended `rejection_cap` is resumed as a new run under
`RECOVERY=program`, from the state at the cap. The original run
directory is never modified.

`resume_run <source_run_dir> <new_run_dir> --recovery program`:

1. Copy the source run directory to `new_run_dir` in full (run.json,
   state, step records, point records, geometry, pictures). Refuse if
   `new_run_dir` exists. Refuse if the source did not end
   `rejection_cap`, with the end reason in the message.
2. In the copy, write `run.json` fields `resumed_from: <source path>`,
   `resumed_at_round: <last round>`, `limits.RECOVERY: "program"`, and
   reset `end_reason` to null. Every other counter (locations, KPI
   cell-queries, seconds elapsed, rounds, rejections) carries over, so
   the resumed run is charged for what the source spent. The time cap
   continues from the source's elapsed seconds.
3. Start the loop at the point of part 2: the consecutive-rejection
   counter is 3, so the first action of the resumed run is the program
   recovery step of part 2 (or the run ends `rejection_cap` again with
   `recovery_not_applicable` if the legal set is not a single action).
   Then normal model rounds.
4. Step records of the resumed run continue the source numbering. Each
   carries `resumed: true` until the run ends.
5. The condition label of the resumed run is `model+program (resumed)`
   in every table and figure, and the report shows both runs: the source
   as the pure model core ending `rejection_cap`, the copy as the
   continuation.

The source directory is the record of the failure; nothing in it
changes.

### Command to give the author

In the report, print the exact command line to run, with the real
source directory of the stuck run filled in and a new directory name
beside it, plus the one command that runs the resumed run to its end
with the same model, reasoning effort and caps as the source (read them
from the source `run.json`). The author will paste both without edits.

## Questions to answer with the report

1. Where `legal_requests` and the `expand`, `query_kpi` and `finish`
   legality are evaluated today, so step 1 of part 2 calls one place
   per kind and does not duplicate a rule.
2. Whether the runner spawns any subprocess or re-imports any module per
   round; if it does, name the modules, since a run is in progress.
