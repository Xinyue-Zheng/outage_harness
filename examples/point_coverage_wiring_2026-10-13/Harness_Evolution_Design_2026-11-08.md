# Harness evolution: design proposal

Date: 2026-11-08. Status: proposal. Nothing in this document is implemented.
Where a record field is named, it is the field that the Copilot instructions
of 2026-10-28 to 2026-11-02 specify; confirm each one against the internal
code before you rely on it.

Related work is cited by arXiv id. The survey behind this document is in the
conversation of 2026-11-08; the table in section 12 says which parts of the
design are borrowed and from where.

## 1. What this adds and what it does not touch

The current system has one loop. A decision core (model or rule) proposes
one action per round, the program validates and executes it, the completion
check decides when the run is done. For four weeks the harness around that
loop has been edited by hand: you read a trace, diagnosed a defect, wrote an
instruction, Copilot changed the code, you reran.

This proposal adds an outer loop that does the same thing with a program and
a second model, offline, between runs:

```
                 ┌──────────────────────────────────────────────────────────┐
                 │  OUTER LOOP (offline, between runs)                      │
                 │                                                          │
   stored runs ──┼─► signal extraction ─► attribution gate ─► engineer ──┐  │
   (traces)      │   (program)            (program + model) (model)      │  │
                 │                                                        ▼  │
                 │      ledger ◄── acceptance ◄── validation ◄── candidate │
                 │      (program)   (program)     (program)      harness   │
                 └───────┬──────────────────────────────────────────────────┘
                         │ accepted harness version
                         ▼
                 ┌──────────────────────────────────────────────────────────┐
                 │  INNER LOOP (unchanged)                                  │
                 │  state → context builder → core → validator → data       │
                 │  completion check → open items → context builder         │
                 └──────────────────────────────────────────────────────────┘
```

The outer loop edits only the harness. It never edits:

- the decision cores (the model prompt is harness; the model is not; the rule
  policy is a baseline and is frozen);
- the caps and the unit costs (they are experiment parameters);
- the data sources and the synthetic cases;
- a run directory, and nothing while a run is in progress.

It runs offline because runtime editing (Living-Harness 2607.26598,
JIT-Agent 2608.25593) would change the harness between the rule run and the
model run of the same case, and the comparison depends on both cores seeing
the same harness.

## 2. Why the setting is different from the surveyed work

Every surveyed system (HarnessPro 2610.26770, AHE 2604.25850,
HarnessCompass 2608.01918, AutoSaddler 2608.23041, Harness-R1 2608.02276,
RRSI 2609.24972) scores a candidate harness by a task-level pass signal:
unit tests, game outcome, or tests that a model writes. This project has no
pass signal and no labels. It has something the surveyed systems do not have:

1. **Deterministic, typed failure records.** A run ends with an `end_reason`,
   a `rejections` list that names the validation check that fired, a
   `budget_at_end` record, `completion_checks`, and an optional `audit.json`.
   These say how a run went wrong, not only that it did.
2. **Replayable traces.** The tools run on stored data. Every past round has
   its state file, its rendered context and its decision. A changed renderer
   or validator can be run over every past round without a single model call.
3. **Two cores on one harness.** A harness edit must serve both. This is a
   constraint none of the surveyed systems has, and it is the reason for the
   attribution gate in section 5.

The evaluation critique 2607.12227 found that harness evolution often does
not beat spending the same budget on more attempts of the unedited harness,
and that it generalizes poorly across tasks, except on long-horizon tasks.
This task is long-horizon. The protocol in section 10 follows that critique.

## 3. Inputs: what a stored run already provides

Per the instructions implemented so far, one run directory holds:

| file | content | used for |
|---|---|---|
| `run.json` | `end_reason`, `budget`, `budget_at_end`, `resources` (seconds split, kpi, decision p50/p95), `rejections[]` (round, check, next action identical/changed/accepted, message), `decisions[]` (tokens, total_s, retries, finish_reason, context_chars), `interventions[]`, `floor_by_step`, `completion_checks`, `resumed_from` | signal extraction |
| `state_NN.json` | structured state after round NN | replay |
| `context_NN.txt` | rendered context sent in round NN | replay, engineer packet |
| `steps/step_NN/` | `resolved_parameters.json`, `tool_result.json`, the decision JSON (purpose, gap, action) | replay, engineer packet |
| `final_report.json`, `final_report.md` | report at end | metrics |
| `audit.json`, audit map | outside-only closure audit when run | signal `closure_leak` |

If a run does not record the harness version it ran under, add one field
now, before any evolution work: `harness_commit` in `run.json`, the git
commit of the harness package at run start. Without it the replay study in
section 9 cannot check out the harness that produced a trace.

## 4. Failure signals

A signal is a fact the program extracts from a run directory. The engineer
never reads a raw trace to find out what went wrong; it receives signals and
the rounds the signal points at.

| signal | source | what it says | component usually involved |
|---|---|---|---|
| `rejection_cap` | `end_reason` | the core repeated a rejected action three times | validator, legal action list, renderer, skill text, or the core |
| `rule_rejected` | `end_reason` | the rule proposed an action the validator refused | legal action list vs rule setting |
| `repeated_rejection` | `rejections[]` with the same check twice in one run | an interface rule the core does not understand | renderer wording, skill text |
| `invariant_failed` | `end_reason = completion_invariant_failed` | completion check accepted a state its own invariant rejects | completion check |
| `closure_leak` | `audit.json` with `found_rate > 0` or `farthest_covered_past_edge_m > BEYOND_REACH_M` | coverage outside the final active area | completion-check constants (specification, see 5.2) |
| `budget_before_complete` | `end_reason ∈ {query_budget, kpi_budget}` with open items | resources ran out | efficiency, no defect by itself |
| `time_cap_program` | `end_reason = time_cap` and `resources.seconds.program` > `resources.seconds.decision` | program time dominates | program performance |
| `time_cap_decision` | `end_reason = time_cap` and decision p95 high | model latency dominates | not a harness defect |
| `gap_mismatch` | decision `gap.targets` names an item the context lists as closed, while an open item exists | the core ignored the context | the core, unless the rendering was wrong |
| `cost_per_finding_high` | locations per covered unit above the rule's on the same case | the core spends more for the same finding | skill text (strategy), or nothing |

The last three rows are included so that the taxonomy says explicitly which
signals are not harness defects. The gate in section 5 turns a signal into
a decision about whether to edit at all.

### Example: the four historical rejection cases as signals

| date | signal | rounds | what the records show |
|---|---|---|---|
| 2026-10-31 case 1 | `rejection_cap` | model, check `kpi_cell_set` three times | validator refused KPI on configured down cells that the skill told the core to query |
| 2026-10-31 case 2 | `rule_rejected` | rule, check `budget` repeated | rule proposed a 53-location batch with 11 locations left, every round |
| 2026-10-31 case 3 | `rejection_cap` | model, bin without boundary, near_edge forbidden, `all` 50 978 | renderer offered an action the validator could not accept; no affordable legal action existed |
| 2026-11-02 step 28 | `rejection_cap` | model, direction 2 proposed while only direction 3 open | context listed the open direction, the rejection reason and the legal action correctly |

## 5. Attribution gate

The gate decides whether a signal is allowed to produce a harness edit. It is
the part of this design that does not exist in the surveyed work, and it
exists because of the two-core comparison: if every model failure becomes a
harness fix, the harness converges to the rule policy and the comparison
measures nothing.

### 5.1 The test

For a signal that points at rounds r1..rn, the program answers three
questions from the stored context and the stored decision of each round.
These are mechanical checks, not judgments:

```
Q1  Did the rendered context of round r list at least one legal action
    with cost within the remaining budget?               (parse context_r)
Q2  Did the validator's decision on the proposed action agree with the
    legality the renderer printed for that action?       (replay legal_requests)
Q3  Did the context state the condition the validator rejected on
    (open direction, budget left, KPI cell set) correctly against state_r?
```

| Q1 | Q2 | Q3 | class | allowed outcome |
|---|---|---|---|---|
| no | – | – | **interface defect** (no legal action offered) | harness edit |
| yes | no | – | **interface defect** (renderer and validator disagree) | harness edit |
| yes | yes | no | **interface defect** (context wrong about state) | harness edit |
| yes | yes | yes | **core failure** | no harness edit; record; a condition change (program recovery) is a separate experiment |

Applied to the four cases: case 1 fails Q3 (the skill and the validator
contradicted each other on the KPI cell set), case 2 fails Q1 (no affordable
legal action was offered to the rule), case 3 fails Q2 (renderer offered
what the validator refused), step 28 passes all three and is a core failure.
That is the same outcome you reached by hand, which is the first thing the
replay study in section 9 checks.

### 5.2 Specification changes are a third class

Some signals do not come from a harness defect but from the definition of
done. `closure_leak` is the example: the check accepted a bin as resolved on a
sample of 10 locations within 5 km, and coverage existed past that. Changing
`BEYOND_REACH_M` or the sample size changes what "done" means, for both
cores, and therefore changes the task.

The engineer may propose a specification change, but the pipeline marks it
`specification` and it is never auto-accepted. A human accepts it, and the
ledger records it as a task change, not a harness fix. Without this rule the
outer loop would quietly make the task easier until every run completes.

### 5.3 Where the model is in the gate

Q1 to Q3 are computed by the program. The engineer model receives the
result and may dispute it with a cited reason (round, field, text). The
dispute is recorded; the class does not change unless a human changes it.
The model is in the loop as a second reader, not as the judge, because the
step-28 episode showed that a model reading the trace blamed a verifier
output from round 11 that could not have reached round 28.

## 6. Edit surface

An edit is a patch to one component. The surface is closed; a patch that
touches anything else is rejected before validation.

| component | file (current names) | allowed edits | forbidden |
|---|---|---|---|
| legal action list | `legal_requests(area_id, bin_key, state)` | legality rules, cost text, combined requests | removing an action kind |
| validator | checks numbered in the partial-area-query instruction, `kpi_cell_set`, `budget`, overlap check | precondition logic, message text that names one legal action | any check that reads the case id or geography by name |
| renderer | `context_builder_point.py` sections and templates | section order, wording, which state fields are shown, how rejections are shown | adding computed recommendations that choose the action |
| skill text | `investigation_skill.txt` | rules of the interface (what a rejection means, how to read legal actions, format) | strategy that names areas, bins or directions of a case |
| completion-check constants | `BEYOND_REACH_M`, sample sizes, `AUDIT_*` | value changes, marked `specification` (5.2) | semantics of resolutions |
| program performance | geometry, corridor cache, check scheduling | anything that leaves outputs identical | behaviour changes |

Not on the surface: the rule policy and its settings A to C, program
recovery, caps, unit costs, the model, the synthetic cases, the completion
check resolutions and the end-run invariant.

Two properties are checked mechanically on every patch:

- **core-agnostic**: the patch does not read which core is running, and the
  test suite runs it under both cores;
- **case-agnostic**: the patch contains no area id, bin key, direction
  number, cell id or coordinate from any case (a string check against the
  case files, plus a reviewer line in the ledger).

These are the counterparts of the "task-agnostic" constraint of
HarnessCompass 2608.01918 and the critic of RRSI 2609.24972, applied to the
two things that would break this experiment.

## 7. The engineer

Should a model be inside the update? Yes, in two roles and no others. Every
surveyed system uses a model to diagnose and to write the patch, and no
program can write a renderer wording fix. The model is not used to decide
what counts as a failure (section 4), to classify it (section 5), to
validate (section 8) or to accept (section 8.4).

Use a stronger model than the in-loop core. The outer loop runs a few times
per week, so its cost is irrelevant next to a 2-hour run, and the step-28
episode shows that the in-loop model class cannot read its own trace
reliably.

### 7.1 Input packet

The engineer gets a packet the program assembles, never a run directory:

```
packet/
  signal.json          the signal record and the gate result (class, Q1..Q3)
  rounds/              for each round the signal points at, plus one before:
    context_NN.txt       as rendered
    decision_NN.json     as proposed
    validation_NN.json   accepted or rejected, check, message
    state_NN.summary     the state fields the check read (not the full state)
  component/           source of the component the gate names, current commit
  ledger_tail.md       last 10 ledger entries (section 8.5)
  constraints.md       edit surface, core- and case-agnostic rules,
                       output schema, "do not edit if class is core failure"
```

This is the evidence-corpus idea of AHE 2604.25850 in a smaller form: the
program decides what the engineer sees, so the engineer cannot wander into
unrelated rounds.

### 7.2 Output schema

One JSON object per episode:

```json
{
  "episode": "run_2026-11-02_case4_model/rejection_cap",
  "diagnosis": "one paragraph, cites round and field for every claim",
  "class_agreement": "agree | dispute",
  "dispute_reason": "null or cited reason",
  "component": "validator",
  "patch": "unified diff against the named commit",
  "tests": ["unit tests added or changed, as code"],
  "predicted_effect": {
    "signal": "rejection_cap",
    "direction": "absent",
    "on_runs": ["the run ids of this episode"],
    "unchanged": ["signals that must not move"]
  },
  "scope": "harness | specification"
}
```

A patch without a predicted effect is rejected. The predicted effect is the
"falsifiable contract" of AHE 2604.25850; it is what the validation stages
check, and the ledger keeps both the prediction and the observation.

## 8. Validation and acceptance

```
candidate patch
   │
   ▼
S0 static ──fail──► reject (ledger: static)
   │ pass
   ▼
S1 replay on stored rounds (no model calls) ──fail──► reject (ledger: replay)
   │ pass
   ▼
S2 reruns on held-out cases, both cores, matched caps ──fail──► reject
   │ pass
   ▼
S3 human review if scope = specification, else auto-accept
   │
   ▼
ledger entry, new harness commit, used by the next runs
```

### 8.1 S0: static

The full gate of the repository (`ruff format`, `ruff check`, `ty check`,
tests) passes. The patch touches only files on the edit surface. The
core-agnostic and case-agnostic checks pass. The patch is under a size
budget (lines changed, one component), the regularizer of RRSI 2609.24972
that stops a candidate from bundling many edits whose effects cannot be
attributed.

### 8.2 S1: replay on stored rounds

This stage is new and specific to this project. For every stored run under
the same harness commit, and for every round of it:

1. re-render the context from `state_NN.json` with the patched renderer and
   diff it against `context_NN.txt`;
2. re-validate the stored decision with the patched validator and compare
   the verdict with `validation_NN.json`;
3. re-compute the legal action list and compare.

The report lists every changed context, every changed verdict and every
changed legal list, by run and round. Acceptance at S1:

- the predicted effect appears: for the episode's rounds, the change the
  patch promised is visible (the rejected action is now accepted, or the
  context now lists a legal affordable action);
- no unpredicted verdict flips: an action that was accepted in a stored
  round must still be accepted unless `predicted_effect.unchanged` says
  otherwise;
- renderer diffs are confined to the sections the diagnosis names.

S1 costs no model calls and takes minutes. It catches the class of defect
that produced case 3 (renderer and validator disagree) directly, because it
runs both over the same states.

### 8.3 S2: reruns on held-out cases

Replay cannot show what a core does with a changed context. S2 reruns the
patched harness on cases that produced none of the signals in the episode,
with both cores, at the same three caps as the stored runs. Acceptance:

- the episode's signal is absent on the episode's case when rerun;
- on held-out cases, `rejections` count, `end_reason` distribution and the
  area-level findings-versus-cost metrics do not get worse by more than a
  fixed tolerance, for both cores;
- the matched-budget baseline (8.6) does not explain the gain.

The held-out set must be real. Three real cases are not enough; use the
synthetic case generator to produce held-out cases with different site
counts and geometries, and keep a fixed split that the engineer never sees.

### 8.4 Acceptance and rollback

A patch that passes S0 to S2 and has `scope = harness` is accepted and
becomes a new harness commit. A patch with `scope = specification` waits
for a human. Every accepted patch has a revert path: if the next real runs
show the predicted-absent signal again, or a new signal on the same
component, the ledger entry is marked `reverted` and the commit is reverted.
Nothing is edited in place in a running experiment; the new commit is used
from the next run pair on.

### 8.5 Ledger

One record per episode, kept in the repository as a file, not in a run
directory:

| field | content |
|---|---|
| `episode` | run id and signal |
| `harness_commit` | commit the trace ran under |
| `gate` | Q1, Q2, Q3, class |
| `engineer` | diagnosis, dispute, component, patch id |
| `predicted_effect` | as in 7.2 |
| `S0`, `S1`, `S2` | pass or fail, with the report path |
| `observed_effect` | after the next runs: signal present or absent, metrics delta |
| `decision` | accepted, rejected at which stage, human-accepted specification, reverted |

The ledger is the artifact the paper reports: how many episodes, how many
were core failures that the gate kept out, how many predictions held.

### 8.6 Matched-budget baseline

Following 2607.12227: for every accepted patch, run the unedited harness on
the same held-out cases with the engineer's model budget added to the in-loop
budget (more rounds of the same core). If the unedited harness with extra
budget reaches the same findings-versus-cost, the patch did not help; it was
test-time scaling.

## 9. First study: replay on the traces you already have

You asked whether the existing traces can test this before anything runs.
They can test everything except S2, and they also give the engineer's own
evaluation.

### 9.1 What exists

Several dozen run directories from 2026-10-13 to 2026-11-02, under harness
versions that changed roughly every two days, and the instruction files that
record the manual fix made after each failure. The instruction files are the
ground truth for the engineer: for each episode, a human read the same trace
and chose a component and a change.

### 9.2 Retroactive ledger

Build the ledger backwards from the instruction files. From the repository
history, the episodes are at least these:

| date | trigger seen in traces | manual change | class under the gate (expected) |
|---|---|---|---|
| 10-28 | whole-area queries unaffordable | partial area query, validation checks numbered | interface defect (Q1) |
| 10-28 | budget invisible to the core | budget in context | interface defect (Q3) |
| 10-29 to 10-31 | runs complete with open directions; per-site bins | completion check v2, v3, v4 | specification |
| 10-31 | KPI rejected on configured down cells | KPI cell set includes configured cells | interface defect (Q3) |
| 10-31 | rule repeats unaffordable batch | affordability guard, rule takes next item | interface defect (Q1) |
| 10-31 | bin without boundary, near_edge forbidden, `all` too large | one `legal_requests` function for renderer and validator | interface defect (Q2) |
| 11-01 | time cap from program time | geometry cache, corridor cache | performance |
| 11-02 | inside and beyond on one bin rejected as duplicates | overlap check by selection pool | interface defect (Q2) |
| 11-02 | step 28, direction 2 while direction 3 open | no harness edit; program recovery as a condition | core failure |
| 11-02 | completion passes with coverage outside | closure audit probe | specification detection |

Fill the table from the actual run directories: which run, which rounds,
which `rejections` entries. Where a run predates a record field, say so.

### 9.3 The study

For each episode in the ledger:

1. Check out the harness at the run's commit (or the nearest commit if
   `harness_commit` was not recorded; note it).
2. Run signal extraction and the gate on the run directory. Record the
   class. Compare with the expected class in 9.2.
3. Build the packet (7.1) and run the engineer once. Record component,
   patch, predicted effect, dispute.
4. Run S0 and S1 on the engineer's patch.
5. Score against the manual fix:
   - gate agreement: class matches the human judgment;
   - component agreement: the engineer names the component the instruction
     changed;
   - replay pass: S1 passes on the engineer's patch;
   - effect agreement: the engineer's predicted effect matches what the
     manual fix achieved in the next stored run.

Report the four rates over the episodes, and list every disagreement with
the reason. The most important single number is the gate's result on the
step-28 episode and any other episode you judged a core failure: if the
gate lets those through, the design fails its purpose.

This study needs no new in-loop runs, no live data, and about one engineer
call per episode. It is also the right first result for a meeting: it shows
whether an automated loop would have made the same decisions you made.

## 10. Evaluation protocol for the paper

| question | measurement |
|---|---|
| Does the gate protect the comparison? | ablation: evolution with and without the gate on the same episodes; the model-versus-rule gap in area-level findings under each |
| Do accepted edits hold? | predicted-effect hit rate from the ledger; signal recurrence on later runs |
| Is it better than more budget? | matched-budget baseline (8.6) on held-out cases |
| Does it generalize? | held-out synthetic cases never seen by the engineer; both cores |
| What does it cost? | engineer tokens and wall time per accepted edit, against the human time recorded in the instruction history |
| Does it match the human engineer? | the replay study (9.3) rates |

Baselines: the manual history (you), no-edit with matched budget, and
unconstrained evolution (no gate, no edit surface) as the ablation that is
expected to erode the comparison.

## 11. What not to build

- No runtime editing during a run. It breaks the fairness of the pair and
  the rule that nothing read per round is changed while a run is open.
- No edits to the rule policy. It is a baseline, and editing it is the
  mechanism by which the harness would absorb the model's job.
- No automatic acceptance of specification changes.
- No LLM-generated tests as the success signal (HarnessPro). The program
  signals, replay and held-out reruns are the signal here.
- No evolution of the completion-check semantics. Constants are
  specification changes; resolutions and the invariant are frozen.
- No second in-loop model that rewrites rejected actions. That is a
  decision-core change and belongs to the recovery experiment, not here.

## 12. Borrowed and new

| element | source | changed how |
|---|---|---|
| offline propose, validate, accept loop | AHE 2604.25850, HarnessPro 2610.26770, AutoSaddler 2608.23041 | signal is program records, not task pass |
| failure batch to patch | AutoSaddler, Harness-R1 2608.02276 | typed signals with pointed rounds |
| component-scoped edits, file-level surface | AHE, HarnessCompass 2608.01918 | closed surface with forbidden list |
| predicted effect per edit, checked later | AHE (falsifiable contract) | checked by replay first, then reruns |
| generalization constraint on edits | HarnessCompass (task-agnostic), RRSI critic | core-agnostic and case-agnostic, checked mechanically |
| edit size budget | RRSI 2609.24972 | one component per patch |
| cost-aware selection | HarnessPro | findings-versus-cost metrics already defined |
| matched-budget baseline, held-out tasks | 2607.12227 | adopted as is |
| the context builder as the optimized object | Meta-Harness 2603.28052 | renderer is one component of the surface |
| learned legality checker | AutoHarness 2603.03329 | not adopted: legality is written and replay-tested, not learned |
| **attribution gate** | none | new; protects the two-core comparison |
| **specification class with human acceptance** | none | new; stops the loop from redefining done |
| **replay validation on stored rounds** | none | new; possible because tools run on stored data |
| **development-history benchmark** | none | new; the manual fixes are the reference for the engineer |

## 13. Risks

- **Overfitting to few cases.** RRSI documents it. The defense is the
  held-out synthetic set and the case-agnostic check. Expect the first
  accepted edits to be exactly the ones you made by hand; the study in
  section 9 will say whether the loop finds anything you did not.
- **Signals that stop firing.** A harness that produces no rejections is not
  a harness with no defects. Keep the closure audit as the independent
  check that the completion check cannot see.
- **The gate as a rule table.** Q1 to Q3 are three checks. If a new kind of
  interface defect appears that passes all three, the gate will call it a
  core failure. Every core-failure episode must be read by a human until
  the gate has been wrong zero times over a meaningful count.
- **Harness commit not recorded.** If old runs have no commit, the replay
  study loses precision for them. Add the field before the next run pair.

## 14. Implementation phases

| phase | content | needs | status |
|---|---|---|---|
| A | `harness_commit` in `run.json`; signal extraction from a run directory; gate Q1 to Q3; retroactive ledger | stored runs, repository history | not started |
| B | packet builder; engineer call with the output schema; S0 and S1 | phase A, one strong model | not started |
| C | replay study on existing episodes; report rates | phases A and B | not started |
| D | S2 on held-out synthetic cases; acceptance; revert path; matched-budget baseline | synthetic case generator, both cores | not started |
| E | ablation without the gate; paper tables | phase D | not started |

Phase A is small and all program. Phase C is the first result and needs no
new in-loop runs. Do not start D while a run pair is in progress.

## 15. Open questions

1. Which model is the engineer, and does it see the in-loop model's
   reasoning tokens or only the decision JSON? Default: decision JSON only,
   so the engineer reads the interface the way the program does.
2. How many held-out synthetic cases make S2 meaningful? The synthetic
   generator decides; a first target is ten cases with one to four sites.
3. Should the engineer be allowed to propose a new signal type when it
   disputes the gate? Default: yes as a ledger note, never as code.
4. Is the rule policy's setting list (A, B, C) part of the frozen baseline or
   a thing the engineer may add to? Default: frozen.
