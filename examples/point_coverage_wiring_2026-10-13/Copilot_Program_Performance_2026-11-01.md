# Program performance: static geometry once, check only on state change

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. No completion rule, pattern, validation or rendering output
changes: every test that passes today must pass unchanged, and the
rendered context and `run.json` of a stored synthetic run must be byte
identical before and after, except for timing fields.

## Why

A rule run on a multi-site case spent 82 minutes in local processing.
The profile shows one completion check at 51 seconds, 30 of them in
corridor-crossing distance: about 96 million location-to-cell
comparisons per check, rebuilt once per site, on every round, including
rounds where the action was rejected and nothing changed. Everything in
that work is a property of the map or of the stored point records, not
of the round.

## 1. Static geometry, computed once

At initialization, and again only for the locations and areas that an
expansion adds, compute and store in state per location:

- `bin` per site (v4 part 3) and `distance_m` per site;
- `nearest_corridor`: the corridor id and distance to its nearest cell,
  or null when no corridor is within the corridor half-width.

Per area: `corridors_crossing`, the list of corridor ids that share a
grid cell with the area or have a cell within the half-width of any
area location, with the half-width definition of the partial-query
instruction part 3 check 7.

The validator (check 7), the `roadside` selector (part 4), and the area
line ("crossed by R02") read these fields. No distance to a corridor is
computed anywhere else. Delete the computations they replace.

## 2. Corridor distance by grid lookup, not all pairs

Index corridor cells by grid id. For a location, the candidate corridor
cells are those whose grid id lies within the half-width neighbourhood
of the location's grid id (the neighbourhood size derived from the grid
spacing and the half-width, computed once). Distance is taken over the
candidates only. The result must equal the all-pairs minimum whenever
that minimum is within the half-width; the test in part 5 checks this.

## 3. The check runs only after a state change

A round changes state only when a request executes, an expansion
executes, or a KPI result is stored. On every other round (rejected
action, parse failure, finish refused), the completion check, the
direction records and the floor are not recomputed; the stored result of
the last computation is reused, and the step record says
`check_reused: true`. The rendered context on such a round differs from
the previous one only in the budget block and the `Last action rejected`
block.

## 4. Incremental recompute after a query

After an executed action, recompute only:

- the (area, site, bin) records of the areas named in the action, for
  the sites and bins of the locations touched;
- every (area, site, bin) record of a bin whose boundary F moved, for
  that site;
- the direction records of those bins.

Every other record is left as stored. One function returns the set of
(area, site, bin) keys to recompute from the touched locations and the
boundary changes; the check reads the records and never rebuilds them.
The equivalence test in part 5 compares the incremental result with a
full rebuild.

## 5. Tests

1. Equivalence: on every synthetic fixture, after each action of a
   stored run, the incremental state (parts 3 and 4) equals a full
   rebuild from the point records, field by field.
2. Corridor distance: for every location of the largest fixture, the
   grid-lookup result equals the all-pairs result when either is within
   the half-width, and both are null otherwise.
3. Rendered context and `run.json` of a stored synthetic run are
   identical before and after this change, timing fields excluded.
4. Performance, on the largest synthetic fixture with four sites: one
   full check under 2 seconds; one rejected round under 0.1 seconds of
   program time; one executed 50-location action, including the
   incremental recompute, under 2 seconds. Record the three numbers in
   the report and in the test output.
5. `check_reused` is true on a rejected round and false on an executed
   one.

## Questions to answer with the report

1. File and line of every place that computes a corridor distance today,
   and confirmation that after the change there is one.
2. Program seconds per round, from the step records of the slow
   multi-site rule run, before and after, as two numbers: median and
   total.
3. Whether the ring probe and the expansion share the location geometry
   function of part 1, or keep their own.
