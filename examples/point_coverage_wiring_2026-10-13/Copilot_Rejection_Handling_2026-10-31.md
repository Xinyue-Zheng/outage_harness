# Rejection handling: KPI cell set, affordability guard, rule next-item

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Builds on `Copilot_Completion_Check_v3_Bin_Local_2026-10-30.md`
and on the floor record of
`Copilot_Objective_and_Floor_In_Context_2026-10-30.md`.

## Why

Two runs of one case ended `rejection_cap`. Neither cause was a decision
error, and in both the end reason hides the cause.

- Model run: the completion check requires KPI baselines for the
  configured down cells, but the KPI validator accepts only cells that a
  coverage result has shown. The model asked for the required baselines,
  was rejected three times, and the run ended. The rule run never meets
  this only because R3 runs after R1 and coverage results have shown the
  down cells by then. Order hides the contradiction; it does not remove
  it.
- Rule run: 989 of 1000 locations were used, the rule asked for a
  53-location batch, and a deterministic selector that is rejected once
  is rejected on every retry. The true cause is that the budget is gone.

No corrector is added. The program does not repair a rejected action and
no second model call is made: both would move the decision out of the
decision core and out of the measurement.

## 1. KPI validator: the set of cells a query may name

The cells a `query_kpi` request may name are the configured down cells
plus every cell that appears in a stored coverage result. A configured
down cell is known by definition and is legal at round 1, before any
coverage query.

A request that names any other cell is rejected with one message that
lists the legal cells:

```
Rejected: cell X is not a configured down cell and no coverage result shows it. Legal cells: WTL03023-1, WTL03023-2, WTL03023-3, B1, B2.
```

The investigation skill is not changed by this part. When to fetch the
baselines stays a recommendation (rule R3 fetches them after every
boundary passes; the model reads the load item), not a validation rule.

## 2. Affordability guard before the decision call

`state["floor"]` already computes, per open item, the smallest legal
action and its location count (floor part 1). Add to that record:

```json
"min_action_locations": 10
```

the smallest location count among the open coverage items (inside items
count their `inside_unqueried`; beyond and unqueried-area items count
`N_MIN_SAMPLED`, or fewer when fewer locations remain). It is 0 when no
coverage item is open.

In `loop_guards`, before the context is rendered and the decision core is
called: if the remaining location budget
(`max_query_locations - locations used`) is below `min_action_locations`,
the run ends with `end_reason = "query_budget"`. `run.json` records the
remaining budget, `min_action_locations`, and the open items at that
round. The decision core is never asked a question that no legal
coverage action can answer.

The guard does not consider KPI items: a KPI call costs no locations, so
with coverage items unaffordable but a KPI item open, the run continues
and the only affordable coverage action is none. The model sees this in
the budget block; the rule reaches its R3 item through part 3.

## 3. Rule policy: next item on rejection, end when none is left

The rule reads the open items and the validator message. On a rejection
it does not repeat the action: it marks that open item as rejected for
the current round and takes the next item in its existing order
(nearest first within the rule's current step R1 to R4). A 53-location
inside item that is rejected for budget is skipped; a 10-location beyond
item that follows it is proposed.

Rules the rule must keep:

- it never changes `n`, pattern, or radius of an item to fit a budget; it
  does not read the budget;
- a rejected item is tried again in the next round only if the state
  record of that item changed;
- when every open item of the round has been rejected and no R3 or R4
  action is legal, the run ends with `end_reason = "rule_rejected"`, and
  `run.json` stores every rejected action with its validator message.

`max_consecutive_rejections` stays at 3 for both cores and keeps its
meaning. With part 3 the rule core reaches it only through a program
defect, which is then visible as three different rejected items in
`run.json`.

## 4. Rejection message names one legal action

Every validator rejection message ends with one legal action for the
same intent, taken from the open items list, when one exists:

```
Rejected: R08 is resolved_boundary in bin 0; beyond on bin 0 is not legal. Legal: query_coverage R08 beyond bin=5 n>=10, or all.
```

The last rejected action and its message are rendered verbatim at the top
of the next round's context, under a fixed heading `Last action rejected`,
in addition to the step record. The block is absent when the last action
was accepted.

## 5. Rejection accounting in run.json

`run.json` gets `rejections`: one entry per rejected action with round,
the validation check that rejected it (the check number from the
partial-area-query instruction, or `kpi_cell_set`, or `budget`), whether
the following action was identical, changed and rejected, or accepted,
and the message. The report tables show the rejection count per run next
to locations and time, for both cores.

## 6. Tests

1. Round 1, no coverage query yet: `query_kpi` on a configured down cell
   is accepted and executed.
2. `query_kpi` on a cell that is neither configured nor observed is
   rejected with the message of part 1, listing the legal cells.
3. State with 9 locations left and one beyond item (`min_action_locations`
   10): the run ends `query_budget` before the decision call; `run.json`
   holds the remaining budget and the open items.
4. State with 9 locations left, no coverage item, one KPI item: the run
   continues, and a `query_kpi` is accepted.
5. Rule core, state with an inside item of 53 locations and a beyond item
   of 10, 11 locations left: the inside request is rejected, the next
   action in the same run is the beyond request, and it is accepted.
6. Rule core, every open item rejected and no R3 or R4 action legal: the
   run ends `rule_rejected` after one pass over the items, with every
   rejected action and message in `run.json`.
7. A rejected `beyond` on a resolved bin produces the message of part 4
   ending with the legal action, and the next rendered context opens
   with the `Last action rejected` block.
8. `run.json` `rejections` has one entry per rejected action with the
   check name and the outcome of the following action.

## Questions to answer with the report

1. File and line of the KPI cell check today, and whether the configured
   down cells are available to the validator at round 1 without a lookup
   that itself calls a service.
2. The order in which the rule iterates open items today (file and
   line), so part 3 states which item is "next".
3. Whether the area id mismatch fixed before these runs has a test; if
   not, add one that queries by the id the open item rendered.
