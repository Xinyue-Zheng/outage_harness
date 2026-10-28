# Harness changes before the rules-vs-harness experiment

Apply these changes to the internal copy of `outage_harness_langgraph`
(the harness) and to `outage_harness_rule_based` (the rules runner). Do not
touch the two concat packages; they are separate baselines and are changed
later. Do not run anything against the real services or real cases; use
the packages' own synthetic fixtures and tests only. When you finish,
report every change as file and line, and answer the questions at the end.

Background: `Harness_Rules_Review_Response_2026-10-27.md`. The harness is
the program: state facts, validation, caps, completion checks, end-of-run
computation. The decision core is either the model or the rule selector.
After these changes both cores run inside the same harness and differ only
in how they choose the next action.

## 1. Same caps in both packages

The packages stay separate, so each keeps its own limits definition, but
the values must be identical and the class defaults must equal the CLI
defaults, so that no launch path can differ.

| limit | value |
|---|---|
| max_steps | 8 decision rounds |
| max_tool_calls | 50 |
| max_time_seconds | 12 000 |
| max_query_locations | 1 500 |
| max_consecutive_rejections | 3 |
| max_identical_queries | None |

Report the values the rules runner CLI passes today, before you change
them.

Acceptance: in each package, a test asserts that the class defaults equal
the CLI defaults and equal this table.

## 2. Query radius 4 or 10, chosen by the model

- `AREA_RESOLUTIONS = (4, 10)`. The live client declaration gets
  `enum: [4, 10]` for `resolution` and a description that names only these
  two values. Remove the commented-out replacement declaration in the graph
  and the `[10]` helper enum, so that one declaration exists.
- The validator accepts 4 or 10 and rejects everything else with a message
  that names both values.
- The probe stays at 10 m (`PROBE_RESOLUTION_M = 10`).
- A location is queried once. A second query of the same location at the
  other radius is rejected as fully queried, the same as today for the same
  radius (C2). The rejection message says the location was queried at
  radius N.
- Every stored point record carries `radius_m` and `n_samples`; confirm both
  are in the point record that the evaluation reads.
- The rendered area summary line shows the radius used for that area, for
  example `queried 120/120 at 10 m`. If one area was queried at both radii
  across calls, show both counts.
- The skill text gets one sentence that states the choice: the 4 m disc
  returns fewer samples than the 10 m disc at the same cell centre, and a
  location with no sample counts as missing, not as uncovered. Add nothing
  about when to use which.
- The rule selector always proposes radius 10 (`RULE_RADIUS_M = 10.0`).
- `run.json` reports the number of locations queried at each radius.

Acceptance: validator tests for 4, 10, 100 and a repeat at the other
radius; a rendered-context test that shows the radius in the area line.

## 3. Same completion function and stop rule for both cores

In the rules runner:

- Remove the rule-verification completion gate. The shared completion
  function in `completion_point.py` is the only definition of done.
- Remove the deferred program stop. Program stop from round 5 applies to
  the rules runner exactly as to the harness.
- Remove the closure verification step: `VERIFY_DEPTH`, the farther-area
  candidate search, and the verified/unverified direction history. Finish
  is proposed as soon as every required check passes (rule R4 below).
- Add a test for the state where every direction is closed and
  the checks pass, and assert that the selector proposes finish. A rules
  run must never reach a cap because no rule fires.

Before changing, report what the removed gate required and at which round
the removed deferred stop fired, so the change log states what changed.

## 4. Budget exhaustion: same behaviour in both packages

Keep the harness behaviour as it is today. Report, from the code, what the
harness does in each of these two states, then make the rules runner do the
same:

- the remaining location budget is zero;
- a single request is larger than the remaining budget while the budget is
  not zero.

Acceptance: one test per state, in each package, asserting the same end
reason or the same rejection.

## 5. Condition label (optional)

The harness CLI defaults `--condition` to `concat`; a harness run launched
without the flag is stored with that label. If the launch script always
passes `--condition rendered`, leave the code and report the script line.
Otherwise make the argument required.

## 6. Direction status without samples

Add the direction status `closed_without_sample`: a bin that closes while
the nearest activity area beyond its edge returned no sample at every
location. It does not block completion. It is written to the completion
record, the report and `run.json`, with the count of such bins. Both cores
see the same status.

## 7. The rule policy

Replace the current five rules with these four. Each round, evaluate from
the top and take the first rule that fires. Record the fired rule id in
`decision.json` as before.

| rule | fires when | proposes |
|---|---|---|
| R1 | the boundary check names an area to fetch in an open direction | query the area nearest to the site (nearest grid location, then area id), radius 10 |
| R2 | no area is left to fetch and a direction is edge-open | expand that direction by 2 000 m, clipped to the frame; strongest edge RSRP first; legacy-accepted edges excluded |
| R3 | the boundary check passes and a required cell (outage sectors plus every co-observed backup) has no baseline | one KPI call per technology for all required cells, for the outage interval shifted back 1 to 8 weeks; at most two proposals for the same batch while the missing set is unchanged |
| R4 | every required check passes | finish |

Removed from the current policy: KPI first (moved after the boundary as
R3; its retry limit of two per unchanged batch is kept), the unobserved-direction rule (the
completion check does not require it), and the verification step (part 3).

Constants: `RULE_RADIUS_M = 10.0`, `EXPAND_STEP_M = 2000.0`. Remove
`VERIFY_DEPTH`.

Inputs the selector reads: the state, the completion check records, the
geometry file, and its own proposal history. It never reads rendered text.

KPI handling itself is unchanged: a cell whose call fails stays
`not_queried`. If it stays unresolved after two proposals, `backup_load`
does not pass, R4 never fires, and the run ends at a cap, as the harness
run would.

Acceptance: one synthetic fixture per rule where exactly that rule fires,
and one where R2 has no edge-open direction and R1 nothing to fetch, so
that R3 or R4 fires.

## Questions to answer with the report

1. The rules runner CLI limit values before the change (part 1).
2. What the removed gate required and at which round the deferred stop
   fired (part 3).
3. The harness behaviour in the two budget states (part 4).
4. The six rows whose file references were cut off in the exported review:
   C1 (second validator path), C7 (start of the actual column), G3
   (continuation after "maximum radial"), G4 (client reference), H6
   (middle reference), and the remaining-budget note in the additional
   clarifications. Give them as text.
