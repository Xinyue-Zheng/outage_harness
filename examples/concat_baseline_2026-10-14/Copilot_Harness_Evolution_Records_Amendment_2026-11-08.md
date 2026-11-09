# Amendment 2: which stored state and which stored verdict a round uses

Amends `Copilot_Harness_Evolution_First_Trace_2026-11-08.md`, parts 3, 4
and 6, together with the gate amendment of the same date. Implement all
parts; the feasibility report is answered here, not a reason to stop.

## State alignment

The context of round r was rendered from the state as it stood at the
start of round r. The runs store that state as
`steps/step_NN/state_before.json`. Use it for Q2, Q3 and the replay.
`state_NN.json` is the state after the round and is not used for
re-rendering. Write the file used into the gate record and the packet
(`state_for_round: {"28": "steps/step_28/state_before.json"}`).

## Fields that older runs lack

| missing in the trace | use instead |
|---|---|
| `harness_version` | the runs named with `--replay-runs`; the field is written from the next run on (part 1) |
| `max_consecutive_rejections` | `budget_at_end.rejections_limit` |

Read the replacement field; do not hard-code 3. A trace with neither
field fails with both names.

## Per-round records are assembled, not expected

No run directory has a `validation_NN.json`. Build each round's record
from where the runner stores the facts:

| fact | where it is now |
|---|---|
| the decision (purpose, gap, action) | the step directory of that round, or the runner's per-round record |
| the verdict and the check that rejected | `run.json` `rejections[]` for rejected rounds; a round with no entry was accepted |
| the rendered context | `context_NN.txt` |
| the state the context came from | per the mapping above |

The packet builder writes the assembled record as `validation_NN.json`
inside the packet. That file is an output of the outer loop, never a file
in the run directory. If a fact is in none of these places, fail with the
fact name and the round.

## Q2 for expansion, and no cost for expansion in Q1

`legal_requests` produces coverage requests only. For a rejected
`expand_study_area`, Q2 calls the function the runner itself uses to
accept or reject an expansion direction, on `state_before.json`, with the
proposed direction, and compares with the recorded verdict. Name that
function in the report.

Q1 for expansion has no cost. The context line "expand_study_area may name
one of: <keys>; cost unknown until the wedge is built" is the legality
sentence; Q1 is true when it lists at least one key. Do not define an
expansion-cost procedure. Affordability applies to coverage requests and
KPI queries only, as the gate amendment's table says.

## Then run part 9 as written

With the two amendments, the step 28 trace has what the gate needs:
contexts 26 to 28, the `state_before.json` files, the three `rejections`
entries, `budget_at_end.rejections_limit`, and the expansion validator.
This is the implementation, not a legacy adapter: these are the records as
they are. Run part 9 and paste the gate record and the engineer response.
