# Resource caps, KPI accounting, decision-call accounting, fixed picture set

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Builds on `Copilot_Budget_In_Context_2026-10-28.md`,
`Copilot_Completion_Check_v2_2026-10-29.md` part 7, and
`Copilot_Rejection_Handling_2026-10-31.md`. No completion rule changes.

## Why

In the stored runs the rule core ends at the tool-call cap and the model
core ends at the time cap, so the two never stop at the same resource
spend. A tool-call cap is not a resource: a 10-location call and a
500-location call count the same, and twenty "attempted KPI calls"
include rejected calls that cost nothing. Decision calls vary from 15
seconds to 3 minutes between adjacent rounds with similar context, and
nothing in the records says whether the time went to queueing or to
output tokens.

## 1. Three resource caps

The caps that can end a run on resources are these and no others:

| cap | counter | end reason |
|---|---|---|
| `max_query_locations` | locations charged by executed coverage requests | `query_budget` |
| `max_kpi_cell_queries` | cell-queries of executed KPI calls (part 2) | `kpi_budget` |
| `max_time_seconds` | wall-clock seconds since run start, decision time included | `time_cap` |

Delete `max_steps`, `max_tool_calls` and `max_identical_queries` from
`RunLimits`, the CLI, the budget record, the rendered budget block and
`run.json`. Delete the end reasons `step_cap` and `tool_call_cap`. There
is no round guard: time bounds the rounds. `max_consecutive_rejections`
stays at 3 with its meaning and end reason `rejection_cap`; it is a
defect detector, not a resource cap. "Program may stop from round 5"
is unchanged.

The budget record becomes:

```json
"budget": {
  "round": 3,
  "locations_used": 640, "locations_limit": 1500,
  "kpi_cell_queries_used": 12, "kpi_cell_queries_limit": 200,
  "consecutive_rejections": 0, "rejections_limit": 3,
  "seconds_elapsed": 412, "seconds_limit": 12000
}
```

and the rendered block lists the same four lines in that order, with
`left` on locations, cell-queries and seconds. Values come from the same
counters the caps read, as before.

Both packages read one limits set with the same values, as the
2026-10-27 instruction requires; the three values are reported in
`run.json` under `limits`.

## 2. KPI accounting

A KPI call that reaches the client and returns, with rows or without,
is executed. A call rejected by the validator is not executed and costs
nothing here; it is counted under `rejections`.

Per executed call record: cells named, rows returned, `query_id`,
client wall seconds. Cell-queries of a call is the number of cells it
names; a cell named in two calls counts twice. `resources.kpi` in
`run.json`:

```json
"kpi": {"calls": 3, "cell_queries": 42, "rows": 1830,
        "query_ids": ["..."], "seconds": 71.2}
```

The time window is fixed per run and recorded next to it, so
cell-queries is proportional to rows scanned.

## 3. Affordability guard, extended

The guard of the rejection-handling instruction part 2 ends the run
with `query_budget` when the remaining locations are below
`min_action_locations`. Add: when every open item is a KPI item and
the remaining cell-queries are below the smallest cell count of an open
KPI item (one), the run ends with `kpi_budget` before the decision call.
`run.json` records the remaining cell-queries and the open items.

## 4. Decision-call accounting

For every call to the model, the runner records one entry under
`decisions` in `run.json`, and the per-round fields in the step record:

| field | source |
|---|---|
| `round` | runner |
| `input_tokens` | API usage field |
| `output_tokens` | API usage field, total generated tokens |
| `reasoning_tokens` | API usage field for thinking or reasoning tokens; `null` with `reasoning_tokens_reported: false` when the API does not report them separately |
| `ttft_s` | seconds from request sent to first streamed token; `null` with `streaming: false` when the client does not stream |
| `total_s` | seconds from request sent to response complete |
| `retries` | client retries before the recorded response |
| `http_status` | of the recorded response |
| `finish_reason` | API field (stop, length, and so on) |
| `context_chars` | length of the rendered context sent |

Do not estimate a missing field. If the API gives no usage block,
record `null` and say so in `resources.decision.notes`.

`resources.decision` in `run.json` sums the calls and gives, over the
calls of the run, `total_s` p50 and p95, `ttft_s` p50 and p95,
`output_tokens` p50 and p95, and `reasoning_tokens` the same. The rule
core writes `decisions: []` and `resources.decision` with zero calls.

The budget block does not show tokens; this is accounting, not context.

## 5. End-of-run time split

`resources.seconds` keeps the split of v2 part 7 (`coverage`, `kpi`,
`osm`, `decision`, `program`, `total`), with `decision` equal to the sum
of `total_s` in part 4 and `total` equal to the wall-clock the time cap
reads. The five parts plus idle must sum to `total`; `run.json` records
`idle` as the difference, so a gap is visible rather than hidden.

## 6. Fixed picture set on every end reason

Every run, whatever its end reason, writes the same pictures with the
same window, layers, legend and file names:

1. coverage map: queried locations by pattern, covered locations by
   RSRP class, the down site, the activity areas;
2. hole map: covered locations with no backup at or above -110 dBm;
3. backup and PRB map: backup cells with a fetched baseline, their PRB
   load class, and cells observed without a baseline marked as such.

Each picture carries one margin line:

```
end: time_cap | locations 1480/1500 | KPI cell-queries 42/200 | 11 820 s (decision 6 210 s) | core: model
```

The picture code reads the values from `run.json`; nothing is computed
in the plotting code. A run that ends by cap before any KPI call writes
picture 3 with every observed backup marked "no baseline", not an empty
file.

## 7. Tests

1. `RunLimits` has exactly the three resource limits plus
   `max_consecutive_rejections`; the CLI rejects `--max-steps`,
   `--max-tool-calls` and `--max-identical-queries` with an error.
2. A run whose executed KPI calls name 7, 10 and 10 cells with
   `max_kpi_cell_queries` 25 ends `kpi_budget` at the third call's
   check, and `kpi.cell_queries` is 27 only if the third call executed
   before the check; state which, from the code, and test that order.
3. A rejected KPI call changes `rejections` and not `kpi.cell_queries`.
4. The guard: one open KPI item, zero cell-queries left: the run ends
   `kpi_budget` before the decision call.
5. A fake model client that returns a usage block with reasoning tokens
   and streams: the `decisions` entry has every field of part 4 filled
   and `ttft_s < total_s`.
6. A fake client without a usage block: `input_tokens`, `output_tokens`,
   `reasoning_tokens` are `null`, `reasoning_tokens_reported` is false,
   and `resources.decision.notes` names the missing block.
7. `resources.seconds`: the five parts plus `idle` equal `total` on a
   synthetic run.
8. A run ended by `time_cap` before any KPI call writes all three
   pictures, picture 3 marks every observed backup "no baseline", and
   the margin line matches `run.json`.
9. The rendered budget block has four lines, in the order of part 1,
   and no rounds or tool-call line.

## Questions to answer with the report

1. The model client in use: whether it streams, whether its usage block
   reports reasoning tokens separately, and the field names (file and
   line of the client call).
2. Whether the wall-clock the time cap reads starts before or after
   initialization (geometry load, OSM), and where the step spans of v2
   part 7 start and end, so `idle` in part 5 is interpretable.
3. The current `max_kpi_calls` value and where it is read, to confirm
   nothing else depends on it after removal.
