# The rules the harness enforces: checklist, and the remaining budget in the context

Two parts. Part 1 is a checklist for the internal copy of
`outage_harness_langgraph` (and the two concat packages where a row says
so): for every rule the program enforces on any decision core, the place,
the expected value or behaviour, and what to report. Answer every row with
the actual value and, where it differs, the file and line. Part 2 adds
the remaining budget to the context, with the code.

Why: the model condition and the rule condition are compared "with the
same rules". The rules are the program's, not the policy's, so they must
be listed and confirmed once on the copy that ran the cases; and the
model has so far not been told how much budget remains, which the rule
policy does not need but a decision core that chooses under a cap does.

---

## Part 1. Checklist

Report for each row: actual value; file:line; whether all three packages
agree; whether the value was the same for every run used in the
comparison.

### A. Initialization

| id | rule | expected | where |
|---|---|---|---|
| A1 | areas from OSM: settlements as discs by place type, corridors as strips | city 3 000 m, town 2 000 m, village 1 000 m, hamlet 500 m; corridor half-width per the strip rule | `build_state0` / `osm_landuse` |
| A2 | frame and study square | FRAME_HALF_WIDTH_M = 30 000 (600 × 600 cells of 100 m); study square 30 km, active cells only | `state0` constants |
| A3 | ring probe at initialization | PROBE_RING_RADII_M = (500, 1 000); one point per bin per radius; PROBE_RESOLUTION_M = 10 | `runner_point_nodes` init |
| A4 | initialization message (concat) | the first user message carries the same facts the rendered state 0 holds | `transcript.initial_user_message` |

### B. Coverage facts

| id | rule | expected | where |
|---|---|---|---|
| B1 | covered location | any sample lists an outage sector at or above COVERAGE_RSRP_DBM = -110, serving or not | `point_coverage` |
| B2 | reachable backup | listed in the same sample as an outage sector; eligible = not in the outage set, same technology | `radio.eligible_backup_cells`, `coobserved_backups` |
| B3 | no sample | status `missing`; counted as unknown, never as uncovered, in every summary and in the direction state | `point_coverage`, `completion_point.location_table` |
| B4 | technology by id pattern | `^[A-Z]{3}\d{5}` LTE, `^[A-Z]{4}\d{6}` NR; KPI routed by it, one call per technology | `radio.radio_technology`, `policy.route_kpi_cells` |
| B5 | query radius | AREA_RESOLUTIONS = (10,), schema enum [10] | `runner_point_nodes`, `synthetic_case` |

### C. Validation (applies to every decision, model or rules)

| id | rule | expected | where |
|---|---|---|---|
| C1 | tool and parameters | unknown function, unknown area id, parameter outside the enum: rejected, reason recorded, round counted | `validate_action` |
| C2 | fully queried area | a query for an area with no unfetched location is rejected | `validate_query_area_coverage` |
| C3 | action must match an open item | an expansion of a direction that is not edge-open, or a KPI call with no named cells, is rejected with the right action named | `validate_action` + completion |
| C4 | repeated identical query | the cap was dropped: max_identical_queries = None | `RunLimits` default and `run_case` argument |
| C5 | consecutive rejections | max_consecutive_rejections = 3 ends the run with end_reason `rejections` | `RunGuard` |
| C6 | caps | max_steps per run_case argument; max_tool_calls = 20; max_time_seconds = 3 600; max_query_locations per argument (1 500 default): report the values used in every comparison run | `RunLimits`, `run.json` |

### D. Direction state and boundary

| id | rule | expected | where |
|---|---|---|---|
| D1 | bins | BIN_DEGREES = 30, MARGIN_BINS = 1 | `completion_point` |
| D2 | closed | the bin's farthest covered location has fetched activity locations beyond it that are sampled and uncovered | `completion_evidence_status` |
| D3 | edge-open | a covered location within EDGE_STRIP_M = 300 (or EDGE_STRIP_CELLS = 3) of the study-square edge; ACCEPT_EDGE_OPEN = False, so it blocks finish | same |
| D4 | unobserved | no sampled location within OBSERVED_RADIUS_M = 2 000 in the bin; a bin whose fetched locations are all `missing` stays unobserved, not closed | same; report which of the two the code does |
| D5 | activity kinds | ACTIVITY_KINDS = {settlement, road_corridor}; other OSM kinds never required | same |
| D6 | open items name the action | each open item carries the one function and parameters that close it (area id for fetch, direction label for expansion, cell list for KPI) | `completion_context_lines`, `progress_lines` |

### E. Backup load

| id | rule | expected | where |
|---|---|---|---|
| E1 | required | REQUIRED_CHECKS = ("boundary", "backup_load") in the rendered and concat_checked packages; backup_load not required in plain concat | `completion_point` of each package |
| E2 | what it requires | observed PRB and RRC for the outage sectors and for every co-observed backup, for every outage hour; `kpi_baselines` keyed as written by apply_kpi | `backup_load_status` |
| E3 | window | kpi_window_for: the outage interval plus the baseline weeks; one call for all named cells of a technology | `kpi_window_for`, `next_calls` |
| E4 | missing rows | a cell with no rows after a call is `missing`, listed, never re-required forever; report what ends a run whose KPI stays missing (cap, auto-stop, program stop) | `backup_load_status`, `program_stop` |
| E5 | metric | PRB_METRIC = MEAN_PRB_USED (percent), RRC_METRIC = AVG_RRC_USERS | `apply_kpi` |

### F. Completion, stop, end of run

| id | rule | expected | where |
|---|---|---|---|
| F1 | finish is a proposal | accepted only when every required check passes; otherwise rejected with the open items | `finish_check` |
| F2 | auto-stop | from round AUTO_STOP_FROM_ROUND = 5 of a stalled run the program offers the stop; the offer is in the variable part | `program_stop`, context builder |
| F3 | end order | completion first, then redistribution once, then the report; report also at cap with the end reason | `end_run` |
| F4 | end reasons recorded | complete, cap (steps, tool calls, time, locations), rejections, program stop; in `run.json` | runner |

### G. Expansion

| id | rule | expected | where |
|---|---|---|---|
| G1 | wedge | bin ±15°, from the current edge outward, distance 500 to 5 000 m; `edge_distance_m` composes across wedges | `expansion` |
| G2 | new areas | OSM fetched for the wedge (cached by bounding box); new areas join the list; the gap target is the direction label | same |
| G3 | offered only when edge-open | the expansion action appears in the offered actions only for edge-open bins | context builder |

### H. End-of-run computation (shared, no decision)

| id | rule | expected |
|---|---|---|
| H1 | redistribution | TrafficRedistributionModel once in end_run; estimated PRB per backup per hour |
| H2 | classification | SIGNAL_MARGIN_DB = 10, SERVICE_RSRP_DBM = -110, LOAD_LIMIT_PERCENT = 80; classes total_loss, degrade_signal, degrade_capacity, degrade_both, served_by_backup, degrade_unknown |
| H3 | report | per area where-and-how-much, per backup table, per hour; run_log.md with one line per step including step 0 |

### I. What the rule policy adds on top (policy, not program)

Confirm these live in `rule_policy.py` only and that the model condition
has no equivalent in code: nearest-first ordering, EXPAND_STEP_M = 2 000,
strongest-edge choice among edge-open bins, VERIFY_DEPTH = 1 with the
finite-evidence requirement, the terminal case with no farther area, the
KPI retry limit of two per fingerprint.

Also confirm the reverse: the model condition has no action the rule
policy lacks. In particular there is no "leave area" action in either.

---

## Part 2. The remaining budget in the context

### Why

The model sees the open items but not how many rounds, tool calls or
locations remain, so it cannot trade verification against cost or prefer
the item that closes a required check when the cap is near. The rule
policy does not use the budget; it stays as it is, so a difference under
a cap is attributable to the decision core.

### 2a. The runner keeps the budget in the state

In `update_state_node` (rendered package) and in the equivalent node of
the two concat packages, after the guard counters are updated, write:

```python
    new_state["budget"] = {
        "round": step_index + 1,
        "rounds_limit": max_steps,
        "tool_calls_used": guard.tool_calls,
        "tool_calls_limit": limits.max_tool_calls,
        "locations_spent": guard.query_locations,
        "locations_limit": limits.max_query_locations,
        "rejections_in_a_row": guard.consecutive_rejections,
        "rejections_limit": limits.max_consecutive_rejections,
        "seconds_used": round(time.monotonic() - run_started, 1),
        "seconds_limit": limits.max_time_seconds,
    }
```

`run_started`, `max_steps`, `limits` and `guard` are what the runner
already holds; pass them into the node the way `run_dir` is passed. The
existing `query_budget` key stays and `_budget_lines` is replaced by the
block below.

### 2b. The context builder renders it

In `context_builder_point.py`, replace `_budget_lines` with:

```python
def _budget_lines(state: Mapping[str, Any]) -> list[str]:
    budget = state.get("budget")
    if not isinstance(budget, Mapping):
        return []

    def left(used: Any, limit: Any) -> str:
        if limit is None:
            return f"{_num(used)} used, no limit"
        return f"{_num(used)} of {_num(limit)} used, {int(limit) - int(used or 0)} left"

    return [
        "Budget:",
        f"- rounds: {left(budget['round'], budget['rounds_limit'])}",
        f"- tool calls: {left(budget['tool_calls_used'], budget['tool_calls_limit'])}",
        f"- locations: {left(budget['locations_spent'], budget['locations_limit'])}",
        f"- rejections in a row: {left(budget['rejections_in_a_row'], budget['rejections_limit'])} "
        "(the run ends at the limit)",
        "A rejected decision costs a round and nothing else. When the run ends at a cap, the report is "
        "written from what was fetched; areas not fetched are reported as not queried.",
    ]
```

The block goes in the variable part, after the progress block and before
the open items, so the model reads the cost next to what remains to do.

In the concat packages, the same lines are appended to the end of each
tool-output user message (the transcript holds no rendered state, so the
budget travels with the observation).

### 2c. One sentence in the skill text

Add to `investigation_skill.txt` and `investigation_skill_rendered.txt`,
in the paragraph on cost: "The Budget block says how many rounds, tool
calls and locations remain. When fewer rounds remain than open items,
take the item that closes a required check first; a verification query
is worth a round only while rounds remain after every required item."

### 2d. Record it

Each step's `llm_input.json` already holds the rendered context, so the
budget shown is recorded per round. `run.json` gains `budget_at_end`, the
last block's values.

### Check

1. Round 1 of a run shows "rounds: 1 of N used, N-1 left" and the location
   count equals `calls.json`.
2. A rules run produces identical decisions with and without the block
   (the policy never reads the rendered text).
3. The concat transcript shows the block at the end of every tool-output
   message and nowhere in the system prefix.
