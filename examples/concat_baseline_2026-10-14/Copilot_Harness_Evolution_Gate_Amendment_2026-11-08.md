# Amendment: the gate reads legality per action kind

Amends `Copilot_Harness_Evolution_First_Trace_2026-11-08.md`, part 3.
Everything else in that instruction stands. The report that the gate
cannot run on the step 28 trace is correct: part 3 assumed that every
rejected action is a priced coverage request. `expand_study_area` is not.

## Q1, Q2, Q3 by the kind of the rejected action

Take the action kind from the rejected round's decision. Apply the row
for that kind. A kind not in the table fails with the kind name.

| kind | Q1 reads in `context_NN.txt` | Q1 true when | Q2 re-computes | Q3 compares |
|---|---|---|---|---|
| coverage request (`inside`, `beyond`, `near_edge`, `far_edge`, `sparse`, `roadside`, `all`) | the priced request lines of the named bin, and the locations budget line | at least one listed request costs no more than the remaining locations | `legal_requests(area_id, bin_key, state_NN)` for the proposed request, against the recorded verdict | the open items and the budget line in the context against the state's completion record and budget |
| `expand_study_area` | the sentence that lists the directions (or site/bin keys) that may be named | at least one direction is listed | the expansion validator on `state_NN` for the proposed direction, against the recorded verdict | the listed directions against the open directions in the state's completion record |
| `query_kpi` | the cell set the context says may be queried, and the KPI budget line | at least one cell is listed and cell-queries remain | the KPI validator (`kpi_cell_set`, `budget`) on `state_NN` for the proposed cells, against the recorded verdict | the listed cell set and KPI budget line against the state's configured cells and `kpi_cell_queries_used/limit` |
| `finish` | nothing | true by definition | the completion check on `state_NN`, against the recorded refusal | the open items in the context against the state's completion record |

For every row, quote the context line(s) that Q1 and Q3 read, and name
the state fields they were compared with, in the gate record as before.
If the sentence or section the row names is absent from the context, fail
with the round number and the row; do not fall back to another row.

## Expected result on the step 28 trace

Rounds 26 to 28, kind `expand_study_area`. Q1 true (direction 3 listed).
Q2 true (the expansion validator rejects direction 2 on the stored state,
as recorded). Q3 true (the listed direction set equals the open set in the
state). Class `core_failure`. If any question comes out otherwise, paste
the quoted evidence; that is a finding, not something to adjust.

## Tests added

10. `gate` on a fixture round of kind `expand_study_area` whose context
    lists direction 3 and whose decision names direction 2, with a recorded
    rejection, gives `core_failure`.
11. `gate` on a fixture round of kind `expand_study_area` whose context
    lists no direction gives `interface_defect_q1`.
12. `gate` on a fixture round of a kind not in the table fails with the
    kind name.

## Note for the design

Design section 13 lists "the gate as a rule table" as a risk. This is the
first instance: the gate must have one row per action kind that can be
rejected, and a new action kind is not covered until its row exists.
