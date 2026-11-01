# Program performance and the decision policy for gpt-oss-safeguard-120b

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Builds on `Copilot_Resource_Caps_and_Decision_Accounting_2026-10-31.md`
(the `decisions` entries and `resources.seconds`),
`Copilot_Rejection_Handling_2026-10-31.md` and
`Copilot_Legal_Actions_Per_Bin_2026-10-31.md`.

Part 1 changes no completion rule, pattern, validation or rendered
output: every test that passes today must pass unchanged, and the
rendered context and `run.json` of a stored synthetic run must be byte
identical before and after part 1, except for timing fields. Part 2
applies to the model core only.

# Part 1. Program performance

## 1.1 Why

A rule run on a multi-site case spent 82 minutes in local processing.
One completion check took 51 seconds, 30 of them in corridor distance:
about 96 million location-to-cell comparisons, rebuilt once per site,
on every round, including rounds where the action was rejected and
nothing changed. All of that work is a property of the map or of the
stored point records, not of the round.

## 1.2 Static geometry, computed once

At initialization, and again only for the locations and areas an
expansion adds, compute and store per location:

- `bin` per site (v4 part 3) and `distance_m` per site;
- `nearest_corridor`: the corridor id and distance to its nearest cell
  within the corridor half-width, or null when none is within it.

Per area: `corridors_crossing`, the corridor ids that share a grid
cell with the area or have a cell within the half-width of any area
location (partial-query instruction part 3 check 7), derived from
`nearest_corridor` and the shared cells.

Corridor cells are indexed by grid id. For a location, the candidate
cells are those within the half-width neighbourhood of its grid id
(neighbourhood size from grid spacing and half-width, computed once);
the distance is the minimum over candidates, equal to the all-pairs
minimum whenever that is within the half-width.

The validator (check 7) and the area line ("crossed by R02") read these
fields. Delete the computations they replace.

## 1.3 Exact corridor distances for `roadside`, cached on demand

The `roadside` selector ranks every unqueried location of the area by
distance to the named corridor's centreline, with no half-width limit
(partial-query instruction part 4). That ordering is unchanged. Its
distances live in a cache keyed by (area, corridor): the exact distance
of every location of the area to the nearest cell of that corridor.

- The cache is empty at initialization. A block is computed only when
  a `roadside` request for that (area, corridor) is executed.
- The fill happens in the execute step, before selection, for the whole
  block in one pass. The selector is a pure read; a `roadside`
  selection whose block is absent raises a program error.
- After an expansion adds locations to an area, every cached block of
  that area is extended before its next read; a block is never
  partially valid.
- The step record of a round that filled or extended a block names the
  blocks and the seconds; `run.json` sums them under
  `resources.seconds.program_cache`, and `idle` in `resources.seconds`
  is computed with it. Blocks are never evicted.

A run that never issues `roadside` computes no exact distance.

## 1.4 The check runs only after a state change

State changes only when a request executes, an expansion executes, or a
KPI result is stored. On every other round (rejected action, parse
failure, finish refused) the completion check, the direction records
and the floor are not recomputed; the stored result is reused and the
step record says `check_reused: true`. The rendered context on such a
round differs from the previous one only in the budget block and the
`Last action rejected` block.

## 1.5 Incremental recompute after a query

After an executed action, recompute only: the (area, site, bin)
records of the areas named, for the sites and bins of the locations
touched; every (area, site, bin) record of a bin whose boundary F
moved, for that site; the direction records of those bins. One function
returns the keys to recompute from the touched locations and the
boundary changes; the check reads records and never rebuilds them.

# Part 2. Decision policy for gpt-oss-safeguard-120b

## 2.1 Why

The model is gpt-oss-120b fine-tuned to apply a written policy in the
system message to content in the user message. It reads a
reasoning-effort line from the system message and defaults to medium,
where hidden reasoning varies by thousands of tokens between rounds;
that is consistent with the 15 second to 3 minute spread between
adjacent decision calls. The endpoint returns no reasoning text in
either streaming or non-streaming mode (tested). The current skill is
prose; the model was trained on a policy template. Each round costs one
decision call, so the number of rounds is the model core's main cost;
the policy makes that cost visible and asks for fewer, fuller actions.

## 2.2 Reasoning effort as a run parameter

`RunLimits.reasoning_effort`, one of `low`, `medium`, `high`, set by a
required CLI flag `--reasoning-effort` with no default; a run without
it fails to start with a message naming the flag. Recorded in
`run.json` under `limits`. The author chooses the value per run and
reviews the result. The rule core ignores it.

## 2.3 System message

Fixed for the run, in this order: the line `Reasoning: <effort>`, then
the policy of 2.4. Nothing in it changes between rounds. The rendered
context is the whole user message. Tool declarations stay where the
client puts them today.

## 2.4 The policy

Replace the investigation skill prose with this text, edited only to
match the exact action names, enums and field names of the current
schema. Target under 600 tokens; report the count.

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

## 2.5 Hidden reasoning tokens

In each `decisions` entry of the accounting instruction add
`visible_tokens` (tokens of the returned text, counted with the model's
tokenizer) and `hidden_tokens` (`output_tokens` from the usage block
minus `visible_tokens`; null when the usage block is absent).
`resources.decision` reports p50 and p95 of `hidden_tokens`. Nothing is
estimated.

## 2.6 Decisions line in the budget block

After the seconds line, model core only:

```
  decisions     24 rounds, median 48 s each, 1 150 s of 7 200 s used; one round costs about as much as 40 locations
```

From the stored decision calls of this run and the measured coverage
seconds per location in `unit_costs.json`; the last clause is omitted
when that file is absent.

## 2.7 Latency probe beside a run

A script started with a run and stopped with it sends a fixed prompt
(`Reasoning: low`, a ten-line policy, a one-line user message, a
five-token answer) to the same endpoint once a minute and logs
timestamp and seconds to one CSV next to `run.json`. The report joins it
with `decisions` by timestamp: a call is endpoint-slow when the nearest
probe sample is above twice the probe median. The count goes to
`resources.decision.endpoint_slow_calls`.

# Part 3. Tests

Four tests, all on synthetic fixtures, none on real cases. Their purpose
is to show that part 1 changes nothing the decision cores see and that
the cache cannot be left in a bad state. No performance targets: the
author measures on the real cases.

- T1. Same behaviour: replay the actions of one stored synthetic run
  through the changed program. The rendered context of every round and
  the final `run.json` are identical to the stored ones, timing fields
  excluded. This covers 1.2, 1.4 and 1.5 together.
- T2. Same roadside order: on the largest fixture, for each
  (area, corridor) pair that crosses, the on-demand block gives the
  same ordered list as the current selector. Covers 1.3.
- T3. Cache cannot be inconsistent: a `roadside` selection with its
  block absent raises; after an expansion adds locations to an area
  with a cached block, the block has one entry per area location before
  the next selection; a run without `roadside` ends with an empty cache.
- T4. Model core wiring: a run without `--reasoning-effort` fails to
  start naming the flag; with it, the system message starts with the
  reasoning line, contains the policy, and is identical on every round
  of a synthetic run.

# Part 4. Report

State, as file and line: where each corridor distance was computed
before part 1 and the one place after; the field names of the usage
block the endpoint returns, or that it returns none; the policy token
count. No measurements and no runs on real cases: the author runs the
cases and reviews the results.
