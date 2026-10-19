# A third package: transcript input with program completion (`outage_harness_concat_checked`)

Why a third package. The two packages that run today differ in two things at
once: what the model reads (rendered State versus transcript) and who ends
the run (program checks versus the model's finish). A difference between
their results cannot be attributed to the State organisation alone. The
third package keeps the concat input exactly and takes the rendered
package's ending: a finish is refused until the checks pass, the refusal
comes back to the model, the program stops the run from round 5 when the
checks pass, and every end writes the report. The only remaining difference
between this package and the rendered one is then what the model reads.

This is the `concat+checks` condition of the test plan, as its own package
instead of the `COMPLETION_MODE` switch, so it can run next to the other two.

Every step is find-and-replace or add-after; package name placeholders are
written out. Start from the concat package after the expansion change.

---

## 1. Copy the package

Why: the package must be identical to the concat one in everything except
the ending, so it is a copy, not a fresh build.

From the directory that contains the packages:

```
cp -r outage_harness_codex_state outage_harness_concat_checked
cd outage_harness_concat_checked
grep -rl "outage_harness_codex_state" . | xargs sed -i 's/outage_harness_codex_state/outage_harness_concat_checked/g'
rm -rf __pycache__ */__pycache__ results runs
```

Check: `grep -rn "outage_harness_codex_state" .` prints nothing.

---

## 2. `langgraph_runner.py`: the condition label and the completion mode

Why: the package must declare what it is in every `task.json` and
`run.json`, and the ending must be the checked one with no switch left to
set at run time.

### 2a. The label

Find:

```python
CONDITION = "concat"
```

Replace with:

```python
CONDITION = "concat_checked"   # transcript input (as concat), program completion (as rendered)
```

### 2b. The completion mode

Find:

```python
COMPLETION_MODE = rc.COMPLETION_MODE_MODEL
```

Replace with:

```python
COMPLETION_MODE = rc.COMPLETION_MODE_CHECKS   # fixed: this package has no model-decided finish
```

Then search the file for every other read of `COMPLETION_MODE`
(`finish_check_node`, `update_state_node`, `write_cap_node`). Each has a
branch for `COMPLETION_MODE_CHECKS` and a branch for the model mode. Keep
the file as it is: with the constant fixed, the checks branch is always
taken. Do not delete the model branches; the package stays a copy that
differs in one constant, which is what makes the comparison clean.

### 2c. The condition value the nodes test

Find the line in `build_investigation_graph` that sets the transcript mode:

```python
    concat_mode = condition == "concat"
```

Replace with:

```python
    concat_mode = condition in ("concat", "concat_checked")
```

and the guard above it:

```python
    if condition not in ("rendered", "concat"):
        raise ValueError(f"condition must be rendered or concat, got {condition!r}")
```

with:

```python
    if condition not in ("rendered", "concat", "concat_checked"):
        raise ValueError(f"condition must be rendered, concat or concat_checked, got {condition!r}")
```

If the Copilot's version keys the transcript mode on a different expression
(for example a module-level `CONDITION != "rendered"`), apply the same
rule: `concat_checked` takes every branch that `concat` takes.

In `run_case_langgraph`, find:

```python
        verifier=None if condition == "concat" else verifier,
```

Replace with:

```python
        verifier=None if condition in ("concat", "concat_checked") else verifier,
```

### 2d. What this gives, with no further edit

- `validate_node`: schema-only validation, as concat. A finish is routed to
  `finish_check_node`.
- `finish_check_node`: the checks branch, `finish_check`: refused until the
  required checks pass; on refusal the reason ("Completion refused: ...",
  with the open directions and the backup cells not yet queried) is the
  node's error, and `record_error_node` appends it to the transcript as a
  tool error, so the model reads why its finish was refused.
- `update_state_node`: the checks are computed every round and, from
  `AUTO_STOP_FROM_ROUND`, a passing check ends the run as
  `complete_program_stop`.
- `write_cap_node`: the report on a cap end.
- No verifier, no rendered context, no progress block. The model learns what
  is open only from a refused finish. That is the designed difference: the
  progress block is part of the State organisation, not of the ending.

---

## 3. `run_case.py`

Why: the script refuses to run a package under a condition the package does
not declare, and the choices list must know the new label.

Find:

```python
    parser.add_argument("--condition", choices=("rendered", "concat"), default="concat",
```

Replace with:

```python
    parser.add_argument("--condition", choices=("rendered", "concat", "concat_checked"), default="concat_checked",
```

Find:

```python
PACKAGE = "outage_harness_concat_checked"
```

(the `sed` in step 1 has already set it; confirm). Find:

```python
    if condition == "rendered" and not arguments.no_verifier:
```

No change: the verifier is built only for `rendered`.

---

## 4. `investigation_skill.txt`

Why: the concat skill tells the model to finish when the evidence answers
the task. In this package a finish is accepted only by the program, and the
model should know that a refusal will tell it what is open.

Find the sentence:

```
Choose finish when the evidence answers the task.
```

Replace with:

```
finish is a proposal. The program accepts it only when its completion checks pass: every observed outage sector closed in every checked direction, and every backup candidate's KPI baseline queried. A refused finish returns the open items as a tool error; read them and resolve them before proposing finish again.
```

No other sentence changes. The skill must not describe a progress block,
because this package renders none.

---

## 5. Check

From the directory that contains the packages:

```
python -c "from outage_harness_concat_checked.langgraph_runner import CONDITION, COMPLETION_MODE; print(CONDITION, COMPLETION_MODE)"
```

must print `concat_checked checks` (or the constant's value for the checks
mode). Then one run:

```
python -m outage_harness_concat_checked.run_case --condition concat_checked \
    --down-cell <ID> --start-time <start> --end-time <end> \
    --output runs/case1_concat_checked --max-steps 15 --query-budget <same as the other two> \
    --ca-bundle <certificate>
```

Expect: `task.json` and `run.json` carry `"condition": "concat_checked"`;
if the model proposes finish before the checks pass, that step's
`validation.json` or `error.json` says "Completion refused" and the next
`LLM_input.txt` shows the refusal as a tool error in the transcript; the run
ends as `complete`, `complete_program_stop`, or a cap, never
`model_finish`; `final_report.md` exists.

---

## 6. The three packages side by side

| | rendered | concat | concat_checked |
|---|---|---|---|
| model input | context rendered from State, progress block every round | transcript of replies and raw tool output | transcript, as concat |
| validation | full (references, preconditions, budget with cost, gap checks) | schema only | schema only |
| finish | refused until the checks pass | accepted as proposed | refused until the checks pass |
| program stop from round 5 | yes | no | yes |
| verifier | yes | no | no |
| report | every end | every end | every end |
| what differs from rendered | nothing | input, validation, ending, verifier | input, validation, verifier |

rendered versus concat_checked isolates the input format and the
validation. If you also want validation held equal, that is a fourth
package with the rendered package's `validate_node` copied into this one;
say so and I will write that step.
