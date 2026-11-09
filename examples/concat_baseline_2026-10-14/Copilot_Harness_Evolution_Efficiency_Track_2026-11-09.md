# Harness evolution, efficiency track: waste profile, operator catalog, filter on stored rounds, one no-gate call

Apply to the repository that holds `outage_harness_langgraph`,
`outage_harness_rule_based` and `outage_harness_evolution`. Design
reference: `Harness_Evolution_2026-11-09.md`, sections 6, 8.1, 15.5 and
phases F1, F2 and E of section 13. This instruction adds the efficiency
track to the existing evolution package and runs it once on stored runs. No
held-out reruns, no acceptance, no automatic edit of a harness package.
Report every change as file and line.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory, any file in the two
  harness packages.
- Do not run `uv sync` and do not add dependencies. Use the model client
  the runner already uses.
- All new code goes into `outage_harness_evolution`. It imports the
  harness packages read-only. Candidates are written over a copy of a
  harness package under `evolution/`, never over the package itself.
- Tests write only under `tmp_path` or the scratch directory the existing
  evolution tests use.
- Outputs go to `evolution/<run_name>/` beside the run directories, and to
  `evolution/` for cross-run tables.

## 0. Facts the profile needs, and where they are

The profile reads facts, not files by assumed name. For each fact, use the
first place that holds it; write the place used into `profile.json` under
`sources`. If a fact is in none of the places, fail with the fact name and
the round; do not estimate it.

| fact | symbol | places to look, in order |
|---|---|---|
| location cap | L | `run.json.budget.max_query_locations` |
| locations spent in round r | c_r | the location counter in `steps/step_{r+1}/state_before.json` minus the one in `steps/step_r/state_before.json`; else the tool result of step r |
| floor after round r (minimum locations still needed to close every open item) | f_r | `run.json.floor_by_step` entry for step r; f_0 is the entry before any query, else the floor function of the completion check on `steps/step_01/state_before.json` |
| covered locations found in round r | n_r | the tool result of step r (locations with down-cell coverage); else the difference of the covered-location set between the two `state_before` files |
| the request of round r | (kind, area_id, bin_key, cost) | the decision JSON in `steps/step_r/` with `resolved_parameters.json` |
| legal requests on the same bin in round r, with costs | | `legal_requests(area_id, bin_key, state_before_r)` |
| open items at step 0 and at round r | | the completion record in the `state_before` files |
| seconds split | | `run.json.resources.seconds.program`, `.decision` |
| context size per round | | `run.json.decisions[].context_chars` |
| core of the run | | `run.json` (the field the runners write for the core); if absent, the command takes `--core model|rule` and records it |

Rounds that are expansions, KPI queries or finish attempts have c_r = 0
and n_r = 0 and do not enter the location shares. KPI budget is reported
as a count only (`kpi_cell_queries_used/limit`), no decomposition.

## 1. Waste profile per run

`evolution profile <run_dir> [--core model|rule]` writes
`evolution/<run_name>/profile.json`:

| field | definition |
|---|---|
| `end_reason` | from `run.json` |
| `spent` | sum of c_r |
| `infeasible_at_start` | f_0 > L |
| `post_infeasibility_share` | sum of c_r over rounds after the first round k with f_k > L minus spent-through-k, divided by `spent`; 0 if no such k; the round k as `first_infeasible_round` |
| `zero_yield_share` | sum of c_r over rounds with c_r > 0, f_r ≥ f_{r-1} and n_r = 0, divided by `spent`; the rounds as `zero_yield_rounds` |
| `excess_over_cheapest_share` | sum over coverage-request rounds of (cost of the chosen request minus the cheapest legal request on the same `(area_id, bin_key)` in that round), divided by `spent`; the rounds with positive excess as `excess_rounds`. This is an upper bound on waste: a cheaper pattern may not close the bin |
| `extension_share` | sum of c_r over rounds whose `(area_id, bin_key)` is not among the open items at step 0, divided by `spent` |
| `decision_time_share` | decision seconds over program plus decision seconds |
| `program_time_share` | program seconds over the same total |
| `context_chars` | median and maximum over rounds |
| `kpi` | `kpi_cell_queries_used`, `limit` |
| `sources` | the place used for every fact of part 0 |

A run with `infeasible_at_start: true` still gets a full profile; the pair
table marks it excluded from the trigger rule of part 3.

## 2. Pair table

`evolution profile-table <model_run_dir> <rule_run_dir> [<model_run_dir> <rule_run_dir> ...]`
takes run directories in pairs, runs part 1 on each if `profile.json` is
absent, and writes `evolution/profiles_<YYYY-MM-DD>.md`: one row per run,
pairs adjacent, columns `case` (from `run.json` if recorded, else the run
name), `core`, `end_reason`, `spent`, `infeasible_at_start`,
`post_infeasibility_share`, `zero_yield_share`,
`excess_over_cheapest_share`, `extension_share`, `decision_time_share`,
`program_time_share`, `context_chars_median`. Shares as two-decimal
fractions. A final block lists, per pair, the model-minus-rule difference
of the three waste shares.

## 3. Trigger rule for an efficiency packet

A pair produces an efficiency target when all of these hold on the model
run: `infeasible_at_start` is false; `end_reason` is `query_budget` or
`time_cap`; and `zero_yield_share` or `excess_over_cheapest_share` exceeds
the rule run's by at least `EFFICIENCY_DELTA` (constant in the evolution
package, initial value 0.10). The target names the share that fired and
the flagged rounds (`zero_yield_rounds` or `excess_rounds`). A pair that
does not fire writes one ledger line with `track: efficiency`,
`decision: no_target` and the four shares, and stops.

`time_cap` with `decision_time_share` above 0.5 produces a target of kind
`context_length` instead, with the five rounds of largest `context_chars`
as flagged rounds. `time_cap` with `program_time_share` above 0.5 produces
a target of kind `performance` with no flagged rounds; it is recorded in
the ledger and no packet is built (performance is out of scope here).

## 4. Operator catalog

Add `outage_harness_evolution/operators.json`, a list of operators derived
from the manual changes of 2026-10-28 to 2026-11-02. Each operator has
`name`, `component`, `file`, `allowed_functions` (Python function names,
or section headings for the skill text), `description`, `source`
(instruction file date), `track` (`defect`, `efficiency`, `both`,
`specification`).

| name | component | allowed scope | description | source |
|---|---|---|---|---|
| `show_state_field` | renderer | the section-rendering functions of the context builder | add or change a state fact shown in one context section | 10-28 budget in context |
| `rejection_feedback_wording` | renderer | the rejection-rendering function | change how a rejection and its reason are shown | 10-31 rejection handling |
| `context_length` | renderer | the section-rendering functions | shorten a section; the legal action list is unchanged | new, efficiency |
| `unify_legality` | legal action list | `legal_requests` and its callers in renderer and validator | one legality function for both sides | 10-31 |
| `affordability_guard` | legal action list | `legal_requests` | exclude or price requests the remaining budget cannot pay | 10-31 |
| `kpi_cell_set_alignment` | validator | the KPI cell-set check | the cell set equals the configured cells | 10-31 |
| `overlap_rule` | validator | the overlap check | which requests count as duplicates | 11-02 |
| `skill_interface_rule` | skill text | one named section of the skill | a rule about reading the interface | 10-31 policy-form skill |
| `skill_strategy_rule` | skill text | the strategy section of the skill | a case-agnostic rule on choosing among legal requests | new, efficiency |
| `completion_constant` | completion constants | the constant definitions | a value change; `specification` | 10-29 to 11-02 |
| `performance_cache` | program performance | cache and geometry modules | outputs identical | 11-01 |

Fill `file` and `allowed_functions` from the current code and report the
list. If a component has no single function that matches a row, list the
functions you chose and why.

## 5. Efficiency packet

`evolution packet <run_dir> --efficiency <pair_rule_run_dir>` builds
`evolution/<run_name>/packet_efficiency/` with the same wrappers and order
as the defect packet (amendment 4), with these differences:

1. `target.json` replaces `signal.json`: the trigger of part 3, both
   profiles, and the model-minus-rule differences.
2. `rounds/`: the flagged rounds, at most 12, the ones with the largest
   c_r; for each, `context_NN.txt`, the decision, the legal requests on the
   round's bin with costs (`legal_NN.json`, program output), and the state
   summary.
3. `component/`: the renderer and the skill text (both are candidates for
   an efficiency edit); each wrapped as a recorded file.
4. `operators.md`: the operators with `track` `efficiency` or `both`,
   rendered as a table.
5. `constraints.md` last, with the efficiency-track sentences added: the
   engineer picks exactly one operator by name; `patched_file.path` must be
   that operator's file; the patch may change only that operator's allowed
   scope; no line in the context may pick the action for the core; no case
   entity may appear.

The output schema gains one field, `operator`, which must be a name from
`operators.json`. A reply whose `patched_file.path` differs from the
operator's `file` fails validation before S0, with both paths.

## 6. Locality check in S0

Extend S0: when the operator has `allowed_functions`, parse the original
and the patched Python file with `ast`, compare every top-level function
and method by source segment, and fail if any function outside
`allowed_functions` differs, naming the function. For the skill text,
split by headings and fail if any section outside the allowed headings
differs, naming the heading. A patch that adds a new top-level function
passes only if the operator's `allowed_functions` contains `"+new"`.

## 7. Filter on stored rounds

`evolution filter <packet_dir>` runs after an engineer call whose reply
has a `patched_file`:

1. copy the harness package to `evolution/<run_name>/candidate_pkg/` and
   write the patched file over it (as the replay does);
2. for each flagged round in the packet, and for the flagged rounds of the
   up to four most recent other model runs under `evolution/` that fired
   the same share (the failure window), re-render the context from
   `state_before.json` with the candidate package; if the operator is a
   skill operator, the candidate skill text is the system prompt;
3. call the in-loop model once per round with the run's recorded reasoning
   effort (`run.json`; fail if absent), no execution, at most 20 calls per
   candidate; record every call's usage and `total_s`;
4. score the recorded decision and the new decision with the program on
   `state_before`: `legal` (the validator accepts), `affordable`,
   `targets_open_item`, `excess_over_cheapest` (locations), and
   `closes_if_no_coverage` (the completion check would close the item if
   the query finds nothing);
5. write `filter_report.md`: one row per round with both scores, the share
   of rounds where the new decision is good (legal, affordable, targets an
   open item, excess 0) against the recorded share, and the line
   `filter: pass` when the good share rises by at least `FILTER_DELTA`
   (constant, initial value 0.20), else `filter: fail`.

The filter is a filter: a pass does not accept the candidate. The ledger
line records `S0`, `locality`, `filter` and `decision: awaiting_S2`.
Nothing is copied into a harness package.

## 8. One no-gate call on the step-28 packet (ablation, phase E)

`evolution engineer <packet_dir> --no-gate` sends the existing step-28
defect packet with a `constraints.md` from which the gate class and the
sentence that a core failure gets no harness edit are removed; everything
else is unchanged. Save the reply as `engineer_response_nogate.json` with
the same call accounting. If it returns a `patched_file`, run S0, the
locality check (operator `+new` not allowed) and S1 replay on it and save
`replay_report_nogate.md`. Append one ledger line with `ablation: no_gate`
and `decision: not_eligible`. Do not run the filter and do not copy
anything into a harness package.

## 9. Tests

Add to the existing evolution test module, numbered on from 15:

16. `profile` on a fixture run (synthetic `run.json`, three
    `state_before` files, three tool results) gives the expected `spent`,
    `zero_yield_share`, `excess_over_cheapest_share` and
    `post_infeasibility_share`, and `sources` names every fact.
17. `profile` on a fixture with f_0 > L gives `infeasible_at_start: true`
    and the pair table marks the pair excluded.
18. `profile` fails with the fact name when the tool result and the state
    counters both lack the round cost.
19. `profile-table` on two fixture pairs writes one row per run and the
    difference block.
20. The trigger rule fires on a fixture pair whose model zero-yield share
    exceeds the rule's by 0.10, and writes `no_target` when it does not.
21. `operators.json` loads, every `file` exists, every `allowed_functions`
    entry is a function or heading in that file.
22. The locality check passes a fixture patch that changes only an allowed
    function and fails one that changes another function, naming it.
23. A reply whose `operator` and `patched_file.path` disagree fails before
    S0 with both paths.
24. `filter` scoring on a fixture round with an injected decision (no
    model call) gives the expected `legal`, `affordable`,
    `targets_open_item` and `excess_over_cheapest`.
25. The no-gate `constraints.md` contains neither the class nor the
    core-failure sentence, and the gated one contains both.

## 10. Run it once

1. Run `profile-table` on every stored run pair you have (model and rule
   of the same case, same caps). Paste the table.
2. For the pair with the largest model-minus-rule zero-yield or excess
   difference that fires the trigger, build the efficiency packet, call
   the engineer (in-loop model, same reasoning effort as the trace), run
   S0 with the locality check, then the filter. Paste the engineer reply,
   the locality result and `filter_report.md`. If no pair fires, say so
   and paste the differences block.
3. Run part 8 on the step-28 packet. Paste the reply and, if there was a
   patch, the S0, locality and replay results.

## 11. Report

File and line of every change; the fields used for every fact of part 0;
the operator table as filled; the pair table; the engineer replies; the
filter report; the no-gate result; the test list with results; anything
in part 0 that was in none of the named places.
