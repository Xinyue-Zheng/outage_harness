# Amendment 2: which stored state and which stored verdict a round uses

Amends `Copilot_Harness_Evolution_First_Trace_2026-11-08.md`, parts 3, 4
and 6, together with the gate amendment of the same date. Implement all
parts; the feasibility report is answered here, not a reason to stop.

## State alignment

The context of round r was rendered from the state as it stood at the
start of round r. Use that state file, whatever its name is. If the runner
writes the state after each round as `state_NN.json`, the state for the
context of round r is `state_{r-1}.json`, and `state_00.json` is the
initial state. Write the mapping you used into the gate record and the
packet (`state_for_round: {"28": "state_27.json"}`) so that nobody has to
guess it later. Do not re-render from the state after the round.

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

## Q2 for expansion

`legal_requests` produces coverage requests only. For a rejected
`expand_study_area`, Q2 calls the function the runner itself uses to
accept or reject an expansion direction, on the aligned state, with the
proposed direction, and compares with the recorded verdict. Name that
function in the report.

## Then run part 9 as written

With the two amendments, the step 28 trace has what the gate needs:
contexts 26 to 28, the aligned states, the three `rejections` entries, and
the expansion validator. Run it and paste the gate record.
