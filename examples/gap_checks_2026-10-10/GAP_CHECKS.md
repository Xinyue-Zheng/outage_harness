# Program checks on the information gap

Every decision the model returns has three parts: an action, its parameters, and
a gap. The gap is the question the action is meant to answer. It has two
fields:

- `targets`: the area ids or cell ids the question is about. A finish uses the
  field for the key areas it leaves unqueried.
- `question`: one sentence of free text.

The program reads only `targets`. The question sentence goes to the verifier
model and into the trace; no program rule reads it. This keeps the checks
deterministic and keeps them independent of wording.

The checks run after check 1 (the action exists) and check 2 (the parameters
are valid). They return the first rejection found. A rejection names the wrong
thing and the right things, and it comes back to the model as a Feedback line
in the next context.

## Check 3: the gap targets agree with State

Three rules.

**3a. Every target is an id the State knows.** A target must be a known area
id (from the geography section) or a cell id seen in a valid coverage record of
the study area. The down cell counts as seen. The rejection lists both id sets.

**3b. Every action except finish names at least one target.** A query without
a target has no question the State can later confirm or contradict. A finish
with no targets means "no key area is left unqueried".

**3c. No target is already answered for the kind of result the action
returns.** What "already answered" means depends on the action:

| Action result | A target is already answered when |
|---|---|
| coverage rows | the area has no unqueried location and no missing record |
| KPI rows | the cell already has both pre-outage indicators in State |
| finish | the area is not a key area with unqueried locations |
| impact, observation rows | never; nothing in State pre-empts these |

Everything check 3 needs is already in State: the area list, the per-area
counts (`unqueried`, `missing`), the per-cell summary of the study area, and
the KPI table.

## Check 4: the action can answer the gap

Two rules.

**4a. The result kind matches the target kind.**

| Action result | Targets it can answer | Rejected when |
|---|---|---|
| coverage rows, observation rows | areas | a target is a cell |
| KPI rows | cells | a target is an area |
| impact | the one scope area, or none | more than one target, a cell, or an area other than the scope |
| finish | key areas | covered by 3c |

The rejection message names the action that can answer the target kind, for
example "use kpi.query for cell KPI".

**4b. The targets are among the ids the action is asked to query.** For a
coverage query, every area target is one of the `areas` parameter. For a KPI
query, every cell target is one of the `cells` parameter. Without this rule a
decision could query F5 while asking about S3; the result would never answer
the question, and the gap would stay open without the model noticing.

Rule 4b is new. The harness in `src/outage_poc/decision.py` implements 3a to
4a; 4b is in the sample code here and should be added when the checks move to
the real deployment.

## Order and effect

```
decision
  |- check 1  action exists            -> unknown_action
  |- check 2  parameters valid         -> bad_parameter
  |- check 3  targets agree with State -> bad_parameter | gap_contradicted
  |- check 4  action can answer gap    -> action_cannot_answer_gap
  '- verifier model (advisory, agree or concern)
```

A rejection is written to State as a Note and counts toward the rejection cap.
The action does not run. The model sees the message in the next context and
may change the action, the parameters, or the targets.

## What the real deployment needs

The checks need only these State facts, all computed by the program at parse
time:

- the set of area ids defined at initialization;
- the set of cell ids seen in valid coverage rows;
- per area: the number of unqueried locations and missing records;
- per cell: which KPI indicators are held;
- the list of key areas.

The real coverage query returns rows of latitude, longitude, serving cell and
RSRP inside a rectangle. As long as initialization fixes area ids and the
parser turns rows into the coverage table, the checks apply unchanged.

## Files

- `gap_checks.py`: the two checks as sample code against the proposed State
  layout, plus a demo of nine decisions.
- `state_model.py`: a copy of the State model and loader of the proposed
  layout, so the sample runs on its own.
- `demo_output.txt`: the demo's output on the round-1 State.
