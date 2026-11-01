# Program performance and the decision policy for gpt-oss-safeguard-120b

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Part A replaces `Copilot_Program_Performance_2026-11-01.md`,
which is withdrawn; part B applies to the model core only. Builds on
`Copilot_Resource_Caps_and_Decision_Accounting_2026-10-31.md`.

No completion rule, pattern, validation or rendering change in part A:
every test that passes today must pass unchanged, and the rendered
context and `run.json` of a stored synthetic run must be byte identical
before and after part A, except for timing fields.

# Part A. Program performance

## Why

A rule run on a multi-site case spent 82 minutes in local processing.
The profile shows one completion check at 51 seconds, 30 of them in
corridor-crossing distance: about 96 million location-to-cell
comparisons per check, rebuilt once per site, on every round, including
rounds where the action was rejected and nothing changed. Everything in
that work is a property of the map or of the stored point records, not
of the round.

## A1. Static geometry, computed once

At initialization, and again only for the locations and areas that an
expansion adds, compute and store in state per location:

- `bin` per site (v4 part 3) and `distance_m` per site;
- `nearest_corridor`: the corridor id and distance to its nearest cell
  within the corridor half-width, or null when no corridor cell is
  within it. Computed by the grid lookup of A2.

Per area: `corridors_crossing`, the list of corridor ids that share a
grid cell with the area or have a cell within the half-width of any
area location, with the half-width definition of the partial-query
instruction part 3 check 7. Derived from `nearest_corridor` and the
shared grid cells; no other distance is computed for it.

The validator (check 7) and the area line ("crossed by R02") read these
fields. The `roadside` selector reads the cache of A2.1. No distance to
a corridor is computed anywhere else. Delete the computations they
replace.

## A2. Corridor distance by grid lookup, not all pairs

Index corridor cells by grid id. For a location, the candidate corridor
cells are those whose grid id lies within the half-width neighbourhood
of the location's grid id (the neighbourhood size derived from the grid
spacing and the half-width, computed once). Distance is taken over the
candidates only. The result must equal the all-pairs minimum whenever
that minimum is within the half-width; test A2 checks this.

## A2.1 Exact corridor distances for `roadside`, cached on demand

The `roadside` selector ranks every unqueried location of the area by
its distance to the named corridor's centreline, with no half-width
limit (partial-query instruction part 4). That ordering is unchanged.
The distances it needs are kept in a cache keyed by (area, corridor),
holding the exact distance of every location of the area to the
nearest cell of that corridor.

- The cache is empty at initialization. Nothing is computed for it
  until a `roadside` request for that (area, corridor) is executed.
- The fill happens in the execute step, before selection, for the whole
  (area, corridor) block in one pass. The selector is a pure read of
  the block; it never writes state. A `roadside` request whose block
  is absent at selection time is a program error, raised, not filled
  lazily.
- After an expansion adds locations to an area, every cached block of
  that area is extended with the new locations in the next execute
  step that reads it; a block is never partially valid.
- The step record of a round that filled or extended a block names
  the blocks and the seconds spent; `run.json` sums them under
  `resources.seconds.program_cache`.
- Memory: a block is one float per location of the area; blocks are
  never evicted during a run.

The cost of exact distances therefore lands on the round that chose
`roadside`, and a run that never issues `roadside` computes none.

## A3. The check runs only after a state change

A round changes state only when a request executes, an expansion
executes, or a KPI result is stored. On every other round (rejected
action, parse failure, finish refused), the completion check, the
direction records and the floor are not recomputed; the stored result of
the last computation is reused, and the step record says
`check_reused: true`. The rendered context on such a round differs from
the previous one only in the budget block and the `Last action rejected`
block.

## A4. Incremental recompute after a query

After an executed action, recompute only:

- the (area, site, bin) records of the areas named in the action, for
  the sites and bins of the locations touched;
- every (area, site, bin) record of a bin whose boundary F moved, for
  that site;
- the direction records of those bins.

Every other record is left as stored. One function returns the set of
(area, site, bin) keys to recompute from the touched locations and the
boundary changes; the check reads the records and never rebuilds them.
Test A1 compares the incremental result with a full rebuild.

## A5. Tests

- A1. Equivalence: on every synthetic fixture, after each action of a
  stored run, the incremental state equals a full rebuild from the
  point records, field by field.
- A2. Corridor distance: for every location of the largest fixture, the
  grid-lookup result equals the all-pairs result when either is within
  the half-width, and both are null otherwise.
- A2.1 Cache: on a synthetic run with two `roadside` requests on the
  same (area, corridor) and one on another corridor, the cache holds
  exactly two blocks after the run; the second request on the first
  block fills nothing (step record names no block, zero cache seconds);
  the selected locations equal those of the current selector on the
  same state, in the same order.
- A2.2 Purity: the selector called twice on the same state returns the
  same list and the state hash is unchanged; a `roadside` selection
  with its block absent raises.
- A2.3 Expansion: after an expansion adds locations to an area with a
  cached block, the next `roadside` on that area ranks the new
  locations too, and the block has one entry per area location.
- A2.4 No `roadside` in the run: the cache is empty at the end and
  `program_cache` seconds is zero.
- A3. Rendered context and `run.json` of a stored synthetic run are
  identical before and after part A, timing fields excluded.
- A4. Performance, on the largest synthetic fixture with four sites:
  initialization under 10 seconds; one full check under 2 seconds; one
  rejected round under 0.1 seconds of program time; one executed
  50-location action, including the incremental recompute, under 2
  seconds; the first `roadside` fill on the largest area, reported as a
  number with no target. Record the five numbers in the report and in
  the test output.
- A5. `check_reused` is true on a rejected round and false on an
  executed one.

# Part B. Decision policy for gpt-oss-safeguard-120b

## Why

The model is gpt-oss-safeguard-120b: gpt-oss-120b fine-tuned to apply a
written policy in the system message to content in the user message. It
reads a reasoning-effort line from the system message and defaults to
medium, where the hidden reasoning varies by thousands of tokens between
rounds; that is consistent with the 15 second to 3 minute spread between
adjacent decision calls. The reasoning text is not returned by the
endpoint in either streaming or non-streaming mode (tested). The current
skill is prose; the model was trained on a policy template.

## B1. System message

The system message is fixed for the run and holds, in this order:

1. `Reasoning: <effort>` as the first line. `<effort>` is the run
   setting `reasoning_effort`, one of `low`, `medium`, `high`, set the
   same way as the caps: a `RunLimits` field and a CLI flag
   `--reasoning-effort`, required with no default, recorded in
   `run.json` under `limits`. The rule core ignores it.
2. The policy of B3.

Nothing in the system message changes between rounds. The rendered
context is the whole user message. The tool declarations stay where the
client puts them today.

## B2. Hidden reasoning tokens

Per decision call, in the `decisions` entry of the accounting
instruction, add:

- `visible_tokens`: tokens of the returned text, counted with the
  model's tokenizer;
- `hidden_tokens`: `output_tokens` from the usage block minus
  `visible_tokens`, or null when the usage block is absent.

`resources.decision` reports p50 and p95 of `hidden_tokens`. No
estimate when usage is absent.

## B3. The policy

Replace the investigation skill prose with this text, edited only to
match the exact action names, enums and field names of the current
schema. Target length under 600 tokens; report the count.

```
# Outage investigation action policy

INSTRUCTIONS
You receive the rendered state of one outage investigation. Choose
exactly one action from the legal actions printed in the state. Output
one JSON object in the OUTPUT format and nothing else.

DEFINITIONS
Open item: an area and bin the completion check still needs evidence
for, printed under "Open". Legal action: a request form printed after
"Legal:" for that item. Budget: the block printed under "Budget";
"left" is what remains. Baseline: a KPI record for a cell; the backup
list marks cells that have one. Decision time: the time this call
takes, charged to the time budget on every round.

RULES
1. An action that is not printed as legal for its item is not allowed.
2. One action holds up to four requests. Put every open item you act on
   this round into one action; each round spends decision time whatever
   the action does.
3. When "all" for an area is affordable and its cost is close to the
   cost of the partial requests listed, choose "all". A partial request
   on a covered area creates a second item for the same area next round.
4. Do not request a baseline for a cell that already has one.
5. Propose "finish" only when the state prints no open item.

OUTPUT
{"action": "<name>", "requests": [...], "gap": "<one sentence: the
information the state still lacks>"}
```

No rule about which item first, which bin, or when to fetch baselines.

## B4. Decisions line in the budget block

After the seconds line of the budget block:

```
  decisions     24 rounds, median 48 s each, 1 150 s of 7 200 s used; one round costs about as much as 40 locations
```

Computed from the stored decision calls of this run and the measured
coverage seconds per location (`unit_costs.json` when present; the
clause is omitted when it is absent). The rule core's budget block has
no decisions line.

## B5. Latency probe beside a run

A script, started with a run and stopped with it, that sends a fixed
prompt (`Reasoning: low`, a policy of ten lines, a user message of one
line, a five-token answer) to the same endpoint once a minute and logs
timestamp and seconds. It writes one CSV next to `run.json`. The report
joins it with the `decisions` entries by timestamp: a call is
"endpoint-slow" when the nearest probe sample is above twice the probe
median. `resources.decision` reports the count of endpoint-slow calls.

## B6. Tests

- B1. The system message starts with the reasoning line carrying the
  configured effort, contains the policy, and is identical on every
  round of a synthetic run; a run without `--reasoning-effort` fails to
  start with a message naming the flag.
- B2. `hidden_tokens` equals usage output tokens minus visible tokens on
  a fake response with a usage block, and is null without one.
- B3. The policy token count is under 600 and reported.
- B4. The budget block of the model core renders the decisions line
  from three stored decision calls; the rule core's block has none.
- B5. The probe CSV joins with the decisions entries and marks the
  endpoint-slow calls on a synthetic pair of files.

## Report

State, as file and line, where each corridor distance was computed
before part A and the one place it is computed after. State the field
names of the usage block the endpoint returns, or that it returns none.
No measurements on real cases: the author runs the cases at each
reasoning effort and reviews the decision-time distribution and the
pictures.
