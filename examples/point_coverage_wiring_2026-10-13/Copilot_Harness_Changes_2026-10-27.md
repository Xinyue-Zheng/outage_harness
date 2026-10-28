# Harness changes before the rules-vs-harness experiment

Apply these changes to the internal copy of `outage_harness_langgraph` and
to the rules runner in `outage_harness_rule_based`. Do not touch the two
concat packages. Do not run anything against the real services or real
cases; use the package's own synthetic fixtures and tests only. When you
finish, report every change as file and line, and answer the three
questions at the end.

Background: `Harness_Rules_Review_Response_2026-10-27.md` (part 2 and
part 3). The harness is the program: state facts, validation, caps,
completion checks, end-of-run computation. The decision core is either the
model or the rule selector. After these changes both cores run inside the
same harness and differ only in how they choose the next action.

## 1. One limits module

Create one module that holds the run limits. The harness `run_case`, the
`RunLimits` class defaults and the rules runner CLI all take their values
from it, so no path can differ.

| limit | value |
|---|---|
| max_steps | 8 decision rounds |
| max_tool_calls | 50 |
| max_time_seconds | 12 000 |
| max_query_locations | 1 500 |
| max_consecutive_rejections | 3 |
| max_identical_queries | None |

Acceptance: a test that constructs the harness limits and the rules-runner
limits and asserts they are equal.

## 2. Query radius 4 or 10, chosen by the model

- `AREA_RESOLUTIONS = (4, 10)`. The live client declaration gets
  `enum: [4, 10]` for `resolution` and a description that names only these
  two values. Remove the commented-out replacement declaration in the graph
  and the `[10]` helper enum so that one declaration exists.
- The validator accepts 4 or 10 and rejects everything else with a message
  that names both values.
- The probe stays at 10 m (`PROBE_RESOLUTION_M = 10`).
- A location is queried once. A second query of the same location at the
  other radius is rejected as fully queried, the same as today for the same
  radius (C2). The rejection message says the location was queried at
  radius N.
- Every stored point record carries `radius_m` and `n_samples` (already
  present for the cache key `grid_id|radius_m|epoch`); confirm both are in
  the point record that the evaluation reads.
- The rendered area summary line shows the radius used for that area, for
  example `queried 120/120 at 10 m`. If one area was queried at both
  radii across calls, show both counts.
- The skill text gets one sentence that states the choice: the 4 m disc
  returns fewer samples than the 10 m disc at the same cell centre, and a
  location with no sample counts as missing, not as uncovered. Add nothing
  else about when to use which.
- The rule selector always proposes radius 10 (`RULE_RADIUS_M = 10.0`).
- `run.json` reports the number of locations queried at each radius.

Acceptance: validator tests for 4, 10, 100 and a repeat at the other
radius; a rendered-context test that shows the radius in the area line.

## 3. Zero-row KPI result is a success with an empty baseline

The client must not turn a zero-row CSV into `ToolFailure("EmptyResult")`.
A successful call with zero rows for a cell returns an empty baseline for
that cell; the checker already treats such a cell as `missing` and
non-blocking. Keep the failure path for transport and parsing errors only.
`run.json` reports the missing cells and hours (the existing KPI-missing
counts).

Acceptance: a fixture with one cell that has baselines and one with zero
rows; after one KPI call `backup_load` passes and the empty cell is listed
as missing.

## 4. Same completion function and stop rule for both cores

In the rules runner:

- Remove the rule-verification completion gate. The shared completion
  function in `completion_point.py` is the only definition of done.
- Remove the deferred program stop. Program stop from round 5 applies to
  the rules runner exactly as to the harness.
- Rule 5 keeps its verification step as policy: when the checks pass and
  the round is below 5, it proposes one verification query (depth 1) and
  then finish. When verification exhausts the candidates without usable
  evidence, or no farther area exists, the direction is terminal and rule 5
  proposes finish. A rules run must never reach a cap because no rule
  fires: add a test for the state where every direction is closed or
  terminal and the checks pass.

## 5. Same oversized-query behaviour in the rules runner

An oversized query is a rejection that counts toward the rejection cap and
the run continues. The run ends with `query_budget` only when the
remaining location budget is zero. The rejection message states the
remaining budget. This is the harness behaviour today; make the rules
runner match it.

## 6. Condition label

The harness CLI has no default for `--condition`; the argument is required
and `run.json` records it.

## 7. Direction status without samples (specification decision S1)

Add the direction status `closed_without_sample`: a bin that closes while
the nearest activity area beyond its edge returned no sample at every
location. It does not block completion. It is written to the completion
record, the report and `run.json`, with the count of such bins. Both cores
see the same status.

## Questions to answer with the report

1. Which `--condition` label the launch script passed for the stored
   harness runs, from the launch script.
2. What the removed rule-verification gate required, and at which round the
   removed deferred stop fired, so the change log states what changed.
3. The six rows whose file references were cut off in the exported review:
   C1 (second validator path), C7 (start of the actual column), G3
   (continuation after "maximum radial"), G4 (client reference), H6 (middle
   reference), and the remaining-budget note in the additional
   clarifications. Give them as text.
