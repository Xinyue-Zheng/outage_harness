# Remaining budget in the context

Apply to the internal copy of `outage_harness_langgraph` (the harness) and
to `outage_harness_rule_based` (the rules runner). Do not touch the two
concat packages. No runs against real services or real cases; use the
synthetic fixtures and tests. Report every change as file and line.

Today the model never sees how much of the run is left. The limits exist
(rounds, tool calls, locations, rejections, time) but only the location
budget appears, and only inside a rejection message. The model cannot
weigh a large query against a cheap one, or decide to finish before a cap.
This change renders the remaining budget every round. It changes the
context only; validation, caps and completion are unchanged.

## 1. Budget record in the state

In `update_state`, after every executed or rejected step, write one record:

```json
"budget": {
  "round": 3,
  "rounds_limit": 8,
  "tool_calls_used": 7,
  "tool_calls_limit": 50,
  "locations_used": 640,
  "locations_limit": 1500,
  "consecutive_rejections": 0,
  "rejections_limit": 3,
  "seconds_elapsed": 412,
  "seconds_limit": 12000
}
```

Values come from the same counters the caps read (`RunLimits` and the run
guard), so the rendered numbers and the cap decisions can never disagree.
`round` is the round about to be decided. `locations_used` counts
locations charged to the budget, the same count the oversized-query
rejection uses.

## 2. Rendered block

In `context_builder.py`, replace the current `_budget_lines` (locations
only) with a block in the variable part, directly after the progress
block and before the open items:

```
Budget:
  rounds        3 of 8 used, 5 left (program may stop from round 5 when checks pass)
  tool calls    7 of 50 used
  locations     640 of 1500 used, 860 left
  rejections    0 of 3 consecutive
  time          412 s of 12000 s
```

Rules for the block:

- Every line shows used, limit and left, computed by the program. The
  model never computes a remainder.
- The round line carries the program-stop note from round 1, so it is a
  fixed sentence, not a new object. Keep the existing round-5 notice in the
  cached prefix as it is.
- When a remainder is zero or when one more action of the smallest kind
  would exceed it, append `(cap reached)` or `(one more rejection ends the
  run)` on that line. No other wording changes between rounds.
- The block is in the variable part, not in the cached prefix.

## 3. Open items show their cost

Each open coverage item that names an area adds the location count of the
unqueried part of that area, for example
`query_area_coverage(area=S03, radius=10): 180 locations unqueried`. The
model can compare the cost against `locations left` on the line above.
Expansion items state `cost unknown until the wedge is built`. KPI items
state the number of cells.

## 4. Skill text

Add one sentence to the investigation skill: "The Budget block shows what
is left of the run; an action that costs more locations than are left is
rejected and counts as a rejection." Add nothing about strategy.

## 5. Run record

`run.json` gets `budget_at_end`: the same record as part 1, as it stood at
the last step.

## 6. Rules runner

The rules runner writes the same `budget` record to the state and to
`run.json`, so the two cores are compared on the same numbers. The rule
selector does not read it.

## Acceptance

- A rendered-context test with a fixture at round 3 asserts the block
  text above, character for character.
- A test at a state with 20 locations left and an open item of 180
  locations asserts the `180 locations unqueried` suffix and the budget
  line.
- A test that the budget record after a rejected step increments
  `consecutive_rejections` and `round`, and does not change
  `locations_used`.
- The rules-runner test asserts that `budget_at_end` is present in
  `run.json`.
