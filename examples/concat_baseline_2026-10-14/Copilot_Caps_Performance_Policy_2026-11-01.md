# Resource caps, program performance, decision policy

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line.

This file replaces `Copilot_Resource_Caps_and_Decision_Accounting_2026-10-31.md`
and `Copilot_Performance_and_Policy_Skill_2026-11-01.md`, both withdrawn.
It builds on `Copilot_Rejection_Handling_2026-10-31.md` and
`Copilot_Legal_Actions_Per_Bin_2026-10-31.md`, which stay in force.

No completion rule, pattern, validation or rendering output change in
parts 1 and 2 beyond what is written here. The rendered context and
`run.json` of a stored synthetic run must be byte identical before and
after part 2, except for timing fields.

# Part 1. Resource caps and accounting

## 1.1 Why

The rule core ends at the tool-call cap and the model core at the time
cap, so the two never stop at the same resource spend. A tool-call cap
is not a resource: a 10-location call and a 500-location call count the
same, and "attempted KPI calls" include rejected calls that cost
nothing. Decision calls vary from 15 seconds to 3 minutes between
adjacent rounds, and the records do not say why.

## 1.2 Three resource caps

| cap | counter | end reason |
|---|---|---|
| `max_query_locations` | locations charged by executed coverage requests | `query_budget` |
| `max_kpi_cell_queries` | cell-queries of executed KPI calls (1.3) | `kpi_budget` |
| `max_time_seconds` | wall-clock seconds since run start, decision time included | `time_cap` |

Delete `max_steps`, `max_tool_calls` and `max_identical_queries` from
`RunLimits`, the CLI, the budget record, the rendered budget block and
`run.json`, with the end reasons `step_cap` and `tool_call_cap`. There
is no round guard. `max_consecutive_rejections` stays at 3 with its
meaning and end reason `rejection_cap`: it is a defect detector, not a
resource cap. "Program may stop from round 5" is unchanged.

`RunLimits` gains `reasoning_effort` (3.1). Both packages read one
limits set; `run.json` records it under `limits`.

Budget record:

```json
"budget": {
  "round": 3,
  "locations_used": 640, "locations_limit": 1500,
  "kpi_cell_queries_used": 12, "kpi_cell_queries_limit": 200,
  "consecutive_rejections": 0, "rejections_limit": 3,
  "seconds_elapsed": 412, "seconds_limit": 12000
}
```

The rendered budget block lists locations, KPI cell-queries, rejections
and seconds, in that order, with `left` on the first, second and
fourth. Values come from the counters the caps read.

## 1.3 KPI accounting

A KPI call that reaches the client and returns, with rows or without,
is executed. A call rejected by the validator is not executed and costs
nothing here; it is counted under `rejections`.

Per executed call: cells named, rows returned, `query_id`, client wall
seconds. Cell-queries of a call is the number of cells it names; a cell
named in two calls counts twice.

```json
"kpi": {"calls": 3, "cell_queries": 42, "rows": 1830,
        "query_ids": ["..."], "seconds": 71.2}
```

The time window is fixed per run and recorded next to it.

## 1.4 Affordability guard, extended

The guard of the rejection-handling instruction part 2 ends the run
with `query_budget` when the remaining locations are below
`min_action_locations`. Add: when every open item is a KPI item and the
remaining cell-queries are below one, the run ends with `kpi_budget`
before the decision call. `run.json` records the remaining cell-queries
and the open items.

## 1.5 Decision-call accounting

For every call to the model, one entry under `decisions` in `run.json`
and the same fields in the step record:

| field | source |
|---|---|
| `round` | runner |
| `input_tokens` | usage block |
| `output_tokens` | usage block, all generated tokens |
| `visible_tokens` | tokens of the returned text, counted with the model's tokenizer |
| `hidden_tokens` | `output_tokens - visible_tokens`; null when the usage block is absent |
| `total_s` | seconds from request sent to response complete |
| `retries` | client retries before the recorded response |
| `http_status` | of the recorded response |
| `finish_reason` | API field |
| `context_chars` | length of the user message sent |

The endpoint returns no reasoning text in either mode (tested); the
hidden count is the only measure of it. Do not estimate a missing
field: record null and name the missing block in
`resources.decision.notes`.

`resources.decision`: number of calls; p50 and p95 of `total_s`,
`output_tokens` and `hidden_tokens`; `endpoint_slow_calls` from 3.5.
The rule core writes `decisions: []` and zero calls.

## 1.6 Time split

`resources.seconds` keeps `coverage`, `kpi`, `osm`, `decision`,
`program`, `total`, and adds `program_cache` (2.3) and `idle`.
`decision` is the sum of `total_s`; `total` is the wall-clock the time
cap reads; `idle` is `total` minus the others, recorded so a gap is
visible.

## 1.7 Pictures

The picture set is unchanged. Its margin line reads the three resource
counters and the decision seconds from `run.json`, in place of any
rounds or tool-call count.

# Part 2. Program performance

## 2.1 Why

A rule run on a multi-site case spent 82 minutes in local processing.
One completion check took 51 seconds, 30 of them in corridor distance:
about 96 million location-to-cell comparisons, rebuilt once per site,
on every round, including rounds where the action was rejected and
nothing changed. All of that work is a property of the map or of the
stored point records, not of the round.

## 2.2 Static geometry, computed once

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

## 2.3 Exact corridor distances for `roadside`, cached on demand

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
  `resources.seconds.program_cache`. Blocks are never evicted.

A run that never issues `roadside` computes no exact distance.

## 2.4 The check runs only after a state change

State changes only when a request executes, an expansion executes, or a
KPI result is stored. On every other round (rejected action, parse
failure, finish refused) the completion check, the direction records
and the floor are not recomputed; the stored result is reused and the
step record says `check_reused: true`. The rendered context on such a
round differs from the previous one only in the budget block and the
`Last action rejected` block.

## 2.5 Incremental recompute after a query

After an executed action, recompute only: the (area, site, bin)
records of the areas named, for the sites and bins of the locations
touched; every (area, site, bin) record of a bin whose boundary F
moved, for that site; the direction records of those bins. One function
returns the keys to recompute from the touched locations and the
boundary changes; the check reads records and never rebuilds them.

# Part 3. Decision policy for gpt-oss-safeguard-120b

Model core only. The rule core reads none of this.

## 3.1 Reasoning effort as a run parameter

`RunLimits.reasoning_effort`, one of `low`, `medium`, `high`, set by a
required CLI flag `--reasoning-effort` with no default; a run without
it fails to start with a message naming the flag. Recorded in
`run.json` under `limits`. The author chooses the value per run.

## 3.2 System message

Fixed for the run, in this order: the line `Reasoning: <effort>`, then
the policy of 3.3. Nothing in it changes between rounds. The rendered
context is the whole user message. Tool declarations stay where the
client puts them today.

## 3.3 The policy

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

## 3.4 Decisions line in the budget block

After the seconds line, model core only:

```
  decisions     24 rounds, median 48 s each, 1 150 s of 7 200 s used; one round costs about as much as 40 locations
```

From the stored decision calls of this run and the measured coverage
seconds per location in `unit_costs.json`; the last clause is omitted
when that file is absent.

## 3.5 Latency probe beside a run

A script started with a run and stopped with it sends a fixed prompt
(`Reasoning: low`, a ten-line policy, a one-line user message, a
five-token answer) to the same endpoint once a minute and logs
timestamp and seconds to one CSV next to `run.json`. The report joins it
with `decisions` by timestamp: a call is endpoint-slow when the nearest
probe sample is above twice the probe median. The count goes to
`resources.decision.endpoint_slow_calls`.

# Part 4. Tests

- T1. `RunLimits` has exactly the three resource limits,
  `max_consecutive_rejections` and `reasoning_effort`; the CLI rejects
  `--max-steps`, `--max-tool-calls` and `--max-identical-queries`;
  a run without `--reasoning-effort` fails to start naming the flag.
- T2. Executed KPI calls naming 7, 10 and 10 cells with
  `max_kpi_cell_queries` 25 end the run `kpi_budget`; state from the
  code whether the third call executes before the check, and test that
  order.
- T3. A rejected KPI call changes `rejections` and not
  `kpi.cell_queries`.
- T4. One open KPI item and zero cell-queries left: the run ends
  `kpi_budget` before the decision call.
- T5. A fake client with a usage block: every field of 1.5 filled,
  `hidden_tokens = output_tokens - visible_tokens`. Without a usage
  block: token fields null, `notes` names the missing block.
- T6. `resources.seconds`: the parts plus `program_cache` and `idle`
  equal `total` on a synthetic run.
- T7. The rendered budget block has the four lines of 1.2 in order and
  no rounds or tool-call line; the model core adds the decisions line
  from three stored decision calls; the rule core does not.
- T8. Equivalence: on every synthetic fixture, after each action of a
  stored run, the incremental state (2.4, 2.5) equals a full rebuild
  from the point records, field by field.
- T9. Corridor distance: for every location of the largest fixture, the
  grid-lookup result equals the all-pairs result when either is within
  the half-width, and both are null otherwise.
- T10. Cache: a synthetic run with two `roadside` requests on one
  (area, corridor) and one on another corridor ends with exactly two
  blocks; the second request on the first block fills nothing (no
  block named, zero cache seconds); the selected locations equal those
  of the current selector on the same state, in the same order.
- T11. Purity: the selector called twice on the same state returns the
  same list and the state hash is unchanged; a `roadside` selection
  with its block absent raises.
- T12. Expansion: after an expansion adds locations to an area with a
  cached block, the next `roadside` on that area ranks the new
  locations too, and the block has one entry per area location.
- T13. No `roadside` in the run: the cache is empty at the end and
  `program_cache` is zero.
- T14. Rendered context and `run.json` of a stored synthetic run are
  identical before and after part 2, timing fields excluded.
- T15. Performance on the largest synthetic fixture with four sites:
  initialization under 10 seconds; one full check under 2 seconds; one
  rejected round under 0.1 seconds of program time; one executed
  50-location action including the incremental recompute under 2
  seconds; the first `roadside` fill on the largest area reported as a
  number with no target. Record the five numbers in the report and in
  the test output.
- T16. `check_reused` is true on a rejected round and false on an
  executed one.
- T17. The system message starts with the reasoning line carrying the
  configured effort, contains the policy, and is identical on every
  round of a synthetic run; the policy token count is under 600.
- T18. The probe CSV joins with the `decisions` entries and marks the
  endpoint-slow calls on a synthetic pair of files.

# Part 5. Report

State, as file and line: where each corridor distance was computed
before part 2 and the one place after; the field names of the usage
block the endpoint returns, or that it returns none; the current
`max_kpi_calls` value and where it was read, to confirm nothing depends
on it after removal; whether the wall-clock the time cap reads starts
before or after initialization. No measurements on real cases: the
author runs the cases at each reasoning effort and reviews the
decision-time distribution and the pictures.
