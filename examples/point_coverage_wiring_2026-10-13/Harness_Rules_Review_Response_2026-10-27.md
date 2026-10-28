# Response to the filled rules checklist

Copilot filled `Harness_Rules_Checklist_2026-10-27.md` from the internal
source on 2026-10-27 (static review, no runs). This file is the response.
It has four parts: the rule table as it actually is, the changes that
must land before the rules-vs-model experiment, the specification
decisions, and the questions that remain. The rule-based baseline is
double checked in part 5, after the changes.

Scope: the harness is `outage_harness_langgraph` (rendered context) and
the rule policy runs inside it with the model replaced by the rule
selector. Only these two are compared for fairness. The two concat
packages are external baselines: they do not use the harness, and their
differences in validation, limits and stopping are part of what they are.
The checklist's "concat same?" column is recorded but drives no change.

Row ids (A1, E7, I11, ...) refer to the checklist.

## 1. The rule table as implemented

These rows are accepted as they are. Where the expected value was wrong,
the actual value replaces it. This table is the reference for the design
document and for the conditions table.

| area | rule (as implemented) | rows |
|---|---|---|
| initialization | settlement radii city 3 000 / town 2 000 / village 1 000 / hamlet 500 m, applied to merged activity groups, not filled discs; corridor half-width motorway 200, trunk 150, primary 150, secondary 100 m; a new corridor needs at least 50 locations; index frame 60 km, active square rural 30 km, urban 4 km, suburban 10 km; ring probe at 500 and 1 000 m, 12 bins, 10 m radius | A1-A5 |
| coverage facts | covered: any sample at or above -110 dBm, serving or not; backup: co-observed with an outage sector at threshold, not in the outage set, backup at threshold; eligibility excludes exact ids, a bare site id excludes its prefix; no sample = `missing`, counted apart from unqueried and valid; technology regexes end in `(?!\d)`, NR tested first | B1-B5 |
| validation | unknown function, area id or radius rejected with a reason, round counted; fully queried area rejected; expansion only for edge-open bins; KPI call with empty cell list rejected before dispatch; identical-query cap off; rejection cap 3, end reason `rejection_cap`; step cap 8 decision rounds | C1-C6, C10 |
| direction state | 30 degree bins, 1 margin bin, 300 m edge strip, observed radius 2 000 m, activity kinds settlement and road corridor; a bin is `open_at_edge` (blocking), `closed`, `closed_at_cap` (frame), or `legacy_edge_accepted`; there is no `ACCEPT_EDGE_OPEN` switch | D1-D7 |
| backup load | required checks `boundary` and `backup_load`; cells: observed outage sectors plus every co-observed eligible backup; hours: every weekday/hour overlapping the outage; baselines from `comparable_kpi_windows(weeks=8)`, the outage interval shifted back 1 to 8 weeks, one batch per technology; baseline key `kpi_baselines`; metrics `MEAN_PRB_USED`, `AVG_RRC_USERS` | E1-E6 |
| completion | finish accepted only when every required check passes; program stop from round 5; end order completion, redistribution once, report; report written at every handled cap; end reasons `complete`, `complete_program_stop`, `time_cap`, `tool_call_cap`, `rejection_cap`, `step_cap`, `query_budget` | F1, F2, F4-F6 |
| expansion | 30 degree bin padded 15 degrees each side (60 degree wedge); 500 to 5 000 m beyond the current bin edge, clipped by the frame, must add new cells; new cells are unioned and the edge recomputed; gap target: direction label or an observed outage sector id; OSM fetched per wedge bounding box, no cache, payload copied into the run | G1-G6 |
| end of run | redistribution once in `end_run`; signal margin 10 dB; service threshold -110 dBm; load limit 80 %; six classes; `run_log.md` one row per step directory | H1-H6 |
| rule policy | order KPI, check-named open area, edge-open, unobserved, verify then finish; rule 2 takes only areas the open record names, nearest grid location to the site, then area id; expand step 2 000 m, not adapted to the frame; strongest edge RSRP, legacy edges excluded; verify depth 1; no farther area = terminal; KPI retry two per unchanged fingerprint; reads state, checks, the geometry file and its own history; fired rule written to `decision.json` | I1-I6, I8-I10, I13 |

Two values the checklist expected and the code does not have: `kpi_window_for`
(E6) and `edge_distance_m` (G3). Both are replaced by the mechanisms above;
no change.

## 2. Changes before the rules-vs-model experiment

The comparison is valid only if the model and the rule selector run inside
the same harness: the same completion function, the same validator, the
same limits and the same stop rule. The review found six places where
that is not true today, or where a harness defect would hit the two cores
differently. Ordered by effect on the comparison.

### 2.1 One limits set for the harness and the rules runner (C7-C9)

The harness CLI uses 50 tool calls, 12 000 s and 1 500 locations, while the
class defaults are 20, 300 s and 5 000. The rules runner has its own CLI
(I11), and the review does not say which values it passes.

Change: one module holds the limits; the harness `run_case` and the rules
runner both import it, and the class defaults equal it, so no path can
differ. Values (the harness CLI values, which the stored rendered runs
used):

| limit | value |
|---|---|
| max_steps | 8 decision rounds |
| max_tool_calls | 50 |
| max_time_seconds | 12 000 |
| max_query_locations | 1 500 |
| max_consecutive_rejections | 3 |
| max_identical_queries | None |

### 2.2 Schema offers only radius 10 (B6)

The active client declaration advertises 4, 10 or 100 without an enum; the
validator accepts 10 only. A model that follows the schema is rejected and
loses a round. The rule policy never proposes another radius, so this
penalises the model only.

Change: the live declaration gets `enum: [10]` and the description says 10 m
only. Remove the commented-out replacement in the graph.

### 2.3 Empty KPI result takes the missing path (E7, E8)

The real client turns a zero-row CSV into `ToolFailure("EmptyResult")`. A
failed call never enters the queried set, so the cell stays `not_queried`,
`backup_load` never passes, and the run goes to a cap. The rule policy stops
retrying after two proposals and then can never finish; the model keeps
retrying or hits a cap. Both lose for a data reason.

Change: a successful call with zero rows is a success with an empty baseline.
The checker already treats that as `missing` and non-blocking. `run.json`
records the missing cells and hours (the `KPI-missing Backups / Hours`
metric already exists). No dedicated KPI stop reason is needed.

### 2.4 Same stop rule for rules and model (I11, I7)

The rules runner adds a rule-verification completion gate and defers the
program stop. The rule baseline therefore solves a stricter task and cannot
end by program stop at round 5 as the model can. Every rounds-to-finish
number would compare different tasks.

Change: remove the rules-only gate and the deferred program stop. The shared
completion function in `completion_point.py` is the only definition of
done, for both decision cores. Rule 5 (verify depth 1, then finish) stays as
policy behaviour: it spends a step on verification when the checks already
pass and the round is below 5. If verification exhausts the candidates
without usable evidence (I7), rule 5 treats the direction as terminal, the
same as when no farther area exists (I8), and proposes finish. A rules run
must never reach a cap for lack of a terminal rule.

See decision S2 if you want verification inside the specification instead.

### 2.5 Same oversized-query behaviour for both cores (F6)

The harness reports an oversized query as a rejection and continues. The
rules runner must do the same: reject, count the rejection, continue, and
end with `query_budget` only when the remaining location budget is zero.
The rejection message states the remaining budget; the budget part (later)
renders the same number in the context every round.

### 2.6 Condition label (additional clarification 4)

The harness CLI defaults its condition label to `concat`. A harness run
launched without `--condition rendered` is stored with the wrong label.

Change: no default; the label is required, and `run.json` records it.
Copilot confirms from the launch scripts which label the stored harness
runs carry.

## 3. Specification decisions

These change what "done" means. They are design points, so they are yours.
Each has a recommendation; the change list in part 2 assumes it.

**S1. A direction whose activity locations all returned no sample (D7, D8).**
Today the nearest all-missing area is skipped and the direction can close
without any sample. Blocking on it would make sparse rural cases never
complete at a 10 m radius. Recommendation: keep it non-blocking, but add
the direction status `closed_without_sample`, report it in `run.json` and
in the report, and count it as a separate column in the evaluation. The
same rule holds for the unobserved-direction list, which is reported but
does not block. Same for both decision cores.

**S2. Verification depth in the specification or in the policy (I6, I11).**
Part 2.4 keeps verification as a policy step. If you believe closure with
one area beyond is not enough for "done", move verification into the
shared completion function so the model must satisfy it too. Then the
rendered open items must name the verification query, and the rule policy
reads it like any other open item. Recommendation: policy, not
specification, until a ground-truth case shows a false closure that
verification would have caught.

**S3. Mixed LTE and NR outage sets (B2, B3).** Eligibility filters by the
union of technologies in the task, not per outage sector. If a case mixes
technologies in the outage set, fix this before running it: the backup must
share the technology of the outage sector it is co-observed with. If no case
mixes technologies, record it as a known limitation and do not change code.

**S4. Model-only actions (I12).** The model can choose inspection and
metadata/OSM actions; the rules never do. Keep them. They count toward the
tool-call cap, so the evaluation reports their number per run as its own
column. This is one of the places where the agent differs from the rules.

## 4. Questions for Copilot

Answer from the code, with file and line; no runs, no run outputs.

1. Which `--condition` label the launch script passes for the harness
   (2.6).
2. The exact requirement of the rules-only completion gate and the exact
   round at which the deferred program stop fires (2.4).
3. Rows whose file reference was cut off in the exported review: C1 (the
   second validator path), C7 (start of the actual column), G3
   (continuation after "maximum radial"), G4 (client reference), H6
   (middle reference), and the remaining-budget note in the additional
   clarifications. Re-export those six as text.

## 5. Rule-based baseline: double check after the changes

Check each line against the code; one sentence per line, file and line.

1. The rules runner imports the limits module of 2.1 and the shared
   completion function; it has no gate, no deferred stop, no own limits.
2. The rules runner calls the same validator as the harness. Rule
   decisions that fail validation are recorded as rejections and count
   toward the rejection cap, exactly as model decisions.
3. The verifier is off for rules and `run.json` says so.
4. Rule 1: one batch per technology; retry limit two per unchanged
   fingerprint; after exhaustion the rule yields to rule 2.
5. Rule 2: only areas named by an open record (`areas_to_fetch`, else
   `closing_area`); nearest grid location, then area id; radius 10.
6. Rule 3: strongest `edge_rsrp_max_dbm`, legacy edges excluded, step
   2 000 m clipped to the frame; if the clipped step is below 500 m the
   rule yields (state what happens then).
7. Rule 4: an unobserved direction with an activity area in reach queries
   the nearest one; with none in reach the direction is terminal.
8. Rule 5: verify depth 1; unusable or exhausted candidates are terminal;
   finish is a proposal that the completion function accepts or refuses.
9. Every rules step writes the fired rule to `decision.json` (I13).
10. Replay: for a stored state, geometry and policy history, the selector
    returns the same action (I14). State which inputs the selector reads
    beyond the state snapshot.
11. A rules run ends with `complete` or `complete_program_stop` whenever the
    checks pass; it ends at a cap only for the same reasons a model run can.

When these eleven lines pass, the rule baseline and the harness share the
specification, the validator, the limits and the stop rule, and differ only
in the decision core. Then the budget part.
