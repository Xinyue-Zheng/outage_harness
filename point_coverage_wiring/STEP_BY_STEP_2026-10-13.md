# Step by step: switch the internal harness to per-point coverage

Work through the steps in order. Each step names the file, the place (by the
function name and the original line numbers your photographed copies record),
what to remove, and what to put there. After step 9 the run works with the fake
API; step 10 switches to the real one.

Package name below: `outage_harness_langgraph` (the internal package).

---

## Step 1. Copy three modules into the package

Copy from this folder into `outage_harness_langgraph/`:

| Copy | As |
|---|---|
| `wiring/point_coverage.py` | `outage_harness_langgraph/point_coverage.py` |
| `wiring/runner_point_nodes.py` | `outage_harness_langgraph/runner_point_nodes.py` |
| `wiring/context_builder_point.py` | `outage_harness_langgraph/context_builder.py` (overwrite the old file; keep a copy of the old one as `context_builder_heatmap.py` if you want it) |

Then fix one import line in `runner_point_nodes.py`:

```python
# old
from point_coverage import (
# new
from outage_harness_langgraph.point_coverage import (
```

`context_builder.py` and `runner_point_nodes.py` import `radio` from the
package already. Do not copy `test_support/`; it stands in for the real
package only outside.

---

## Step 2. `point_by_point_cover.py`: keep it, fill the two blanks

The function stays as it is. Set `BASE_URL`, and read the token from the
environment in the runner (step 7), never from State. Nothing else changes.

---

## Step 3. `runner.py`: parameters and decision schema

**`PARAMETERS`** (the dict after `DECISION_SCHEMA`): keep
`"query_area_coverage": {"area_id", "resolution"}` as it is. The model still
chooses the resolution; it is now the radius of each point call.

Delete the whole `"query_coverage_heatmap": {...}` entry.

**`DECISION_SCHEMA`**, in `properties.action.properties.function.enum`: delete
the string `"query_coverage_heatmap"`.

**`_validate_decision`**: delete this branch

```python
    if name == "query_coverage_heatmap":
        if supplied != expected:
            raise ValueError(
                "query_coverage_heatmap needs exactly the four bbox values and required resolution"
            )
    elif name == "query_osm_landuse":
```

so it reads

```python
    if name == "query_osm_landuse":
```

Leave `_update_state` and `_apply_coverage_progress` alone. The second is
never reached once State has a `geography` dict.

---

## Step 4. `policy.py`: the location budget

**`RunLimits`** (original 332): add one field and include it in the check loop.

```python
@dataclass(frozen=True)
class RunLimits:
    max_time_seconds: float | None = 300.0
    max_tool_calls: int | None = 20
    max_consecutive_rejections: int | None = 3
    max_identical_queries: int | None = 2
    max_query_locations: int | None = 1500        # new

    def __post_init__(self) -> None:
        for name in ("max_time_seconds", "max_tool_calls", "max_consecutive_rejections",
                     "max_identical_queries", "max_query_locations"):   # add the new name
```

**`RunGuard`** (original 361): add one counter and two methods.

```python
    query_counts: Counter = field(default_factory=Counter)
    queried_locations: int = 0                     # new

    def check_locations(self, new_locations: int) -> str | None:        # new
        limit = self.limits.max_query_locations
        if limit is None:
            return None
        return "query_budget" if self.queried_locations + new_locations > limit else None

    def record_locations(self, new_locations: int) -> None:            # new
        self.queried_locations += new_locations
```

**`validate_live_action`** (original 209): the heatmap branch becomes an
OSM-only branch.

```python
# old
    elif name in {"query_coverage_heatmap", "query_osm_landuse"}:
# new
    elif name == "query_osm_landuse":
```

Also raise `max_time_seconds`. One point call per location with the
`(15, 300)` timeout makes 300 s far too small for a first area. Start with
`max_time_seconds=3600.0` where `RunLimits(...)` is constructed.

---

## Step 5. `client.py`: the declaration the model sees

In `TOOL_DECLARATIONS`, delete the `query_coverage_heatmap` declaration and
add the `query_area_coverage` one. The exact object is `QUERY_AREA_COVERAGE`
in `runner_point_nodes.py`; as a `ToolDeclaration`:

```python
ToolDeclaration(
    "query_area_coverage",
    "Fetch pre-outage coverage at every analysis grid location of one listed area through "
    "the point API: for each location, every sample within the resolution radius with its "
    "serving sector and strongest neighbour cells and their RSRP. resolution is the radius "
    "in metres around each location and must be 4, 10 or 100.",
    {"type": "object",
     "properties": {"area_id": {"type": "string"},
                    "resolution": {"type": "number", "enum": [4, 10, 100]}},
     "required": ["area_id", "resolution"], "additionalProperties": False},
)
```

This declaration has no function behind it: `query_area_coverage` runs in the
program, never through `client.call`. If your library pairs every declaration
with a callable for the MCP server, give this one none.

If the point API function `query_point_coverage` is registered in the same
library, it must not reach the model. Step 6 filters it out of `tools`.

---

## Step 6. `langgraph_runner.py`: imports and the graph builder

**Imports** (top of file):

```python
# old
from outage_harness_langgraph.evidence_state import split_geography, apply_coverage, apply_kpi, inspect_coverage, _geometry
# new
from outage_harness_langgraph.evidence_state import split_geography, apply_kpi
from outage_harness_langgraph.point_coverage import PointQuery, inspect_point_coverage
from outage_harness_langgraph.runner_point_nodes import (
    execute_query_area_coverage, make_point_query,
    update_state_query_area_coverage, validate_query_area_coverage,
)
```

Delete the line `AREA_RESOLUTIONS = (100, 10, 4)` and its comment. The same
tuple now lives in `runner_point_nodes.py`, where
`validate_query_area_coverage` checks it.

**`build_investigation_graph` signature**: add the point query.

```python
def build_investigation_graph(
    model: DecisionModel,
    client: Any,
    *,
    point_query: PointQuery,                      # new
    fetch_landuse_before_decision: bool = True,
    verifier: DecisionModel | None = None,
    limits: RunLimits | None = None,
):
```

**`initialize_node`**, after `case_state["geography"]["source"] = {...}` (inside
the `if fetch_landuse_before_decision:` block), add:

```python
            case_state["query_budget"] = {"locations_spent": 0,
                                          "locations_limit": guard.limits.max_query_locations}
```

Still in `initialize_node`, replace the clipped block that extends `tools`
(original 174 to 181, the two `ToolDeclaration(...)` calls) with the block
below. `query_area_coverage` is already declared in the client after step 5,
so it is not added here again. The filter removes the point API function
if the library registers it; use the name the library gives it.

```python
        tools = tuple(tool for tool in tools if tool.name != "query_point_coverage")
        if fetch_landuse_before_decision:
            tools = (*tools,
                     ToolDeclaration("inspect_observation",
                                     "Inspect existing coverage rows without another API query.",
                                     {"type": "object",
                                      "properties": {"observation_id": {"type": "string"}, "area_id": {"type": "string"},
                                                     "offset": {"type": "integer"}, "limit": {"type": "integer"}},
                                      "required": ["observation_id", "area_id", "offset", "limit"],
                                      "additionalProperties": False}))
```

If `ToolDeclaration` takes more positional fields in your client, match its
signature; the three fields above are what the context builder reads.

---

## Step 7. `langgraph_runner.py`: the four nodes

**`validate_node`** (original 280). Replace the `query_area_coverage` block
and the inspection check:

```python
# old
            if action_name == "query_area_coverage":
                geometry = _geometry(state["state"], state["output_dir"])
                if arguments["area_id"] not in geometry["areas"]:
                    raise ValueError("Choose a listed area_id")
                if arguments["resolution"] not in AREA_RESOLUTIONS or isinstance(arguments["resolution"], bool):
                    raise ValueError(...)
            elif action_name == "inspect_observation":
                if not all(isinstance(arguments[key], int) and not isinstance(arguments[key], bool) for key in ("offset", "limit")) or ...:
                    raise ValueError("Inspection needs offset >= 0 and limit between 1 and 100")
                inspect_coverage(state["state"], arguments["observation_id"], arguments["area_id"], arguments["offset"], arguments["limit"])
# new  (validate_query_area_coverage checks the area, the resolution and the budget)
            if action_name == "query_area_coverage":
                validate_query_area_coverage(arguments, state["state"], state["output_dir"], guard)
            elif action_name == "inspect_observation":
                if (not all(isinstance(arguments[key], int) and not isinstance(arguments[key], bool)
                            for key in ("offset", "limit"))
                        or arguments["offset"] < 0 or not 1 <= arguments["limit"] <= 100):
                    raise ValueError("Inspection needs offset >= 0 and limit between 1 and 100")
                inspect_point_coverage(state["state"], arguments["observation_id"], arguments["area_id"],
                                       arguments["offset"], arguments["limit"])
```

The rest of `validate_node` (the `elif action_name not in {...}` branch,
`check_gap`, `guard.check`, the validation file) stays.

**`execute_tool_node`** (original 358). Replace the inspection block and the
`query_area_coverage` block. Delete the bounding-box code entirely.

```python
        if state["action_name"] == "inspect_observation":
            arguments = state["arguments"]
            rows = inspect_point_coverage(state["state"], arguments["observation_id"], arguments["area_id"],
                                          arguments["offset"], arguments["limit"])
            path = Path(state["output_dir"]) / "artifacts" / f"inspection_{state['step_index']:02d}.json"
            _write_json(path, rows)
            result = ToolSuccess("inspect_observation", str(path), len(rows), ("grid_id", "status", "cells"),
                                 source="state", details={"rows": rows})
            _write_json(Path(state["output_dir"]) / "steps" / f"step_{state['step_index']:02d}" / "tool_result.json",
                        _summarize(result))
            return {"tool_result": result}
        if state["action_name"] == "query_area_coverage":
            summary = execute_query_area_coverage(state["state"], state["arguments"], state["output_dir"],
                                                  state["step_index"], point_query, guard)
            if summary["status"] == "success":
                result = ToolSuccess(summary["tool"], summary["output_file"], summary["row_count"],
                                     tuple(summary["columns"]), source=summary["source"], details=summary["details"])
            else:
                result = ToolFailure(summary["tool"], "PointApiFailure", summary["error"])
            return {"tool_result": result}
```

`execute_query_area_coverage` already writes `resolved_parameters.json` and
`tool_result.json` into the step directory. The KPI routing code after these
two blocks stays as it is.

**`update_state_node`** (original 424). Two edits.

First, the `executed_parameters` lines: keep them. `resolved_parameters.json`
now holds `area_id`, `resolution`, `radius_m` and `fetched`, which is what the
provenance line should show.

Second, replace the coverage branch:

```python
# old
        if state["action_name"] in {"query_coverage_heatmap", "query_area_coverage"} and summary["status"] == "success":
            if isinstance(state["state"].get("geography"), dict):
                evidence_observation = dict(observation)
                if state["action_name"] == "query_area_coverage":
                    evidence_observation = {**observation, "parameters": executed_parameters}
                new_state = apply_coverage(state["state"], evidence_observation, state["output_dir"])
                new_state["coverage_artifacts"] = {**state["state"].get("coverage_artifacts", {}), "latest": summary}
            else:
                new_state = _apply_coverage_progress(new_state, Path(state["output_dir"]))
# new
        if state["action_name"] == "query_area_coverage" and summary["status"] == "success":
            new_state = update_state_query_area_coverage(new_state, observation, state["output_dir"], guard)
```

The inspection branch two lines below keeps working: `summary["details"]["rows"]`
is what the new execute block puts there.

**`loop_or_end`** (original 564): no change needed. A query that does not fit
the budget is rejected in validation with the cost in the message; the model
can pick a smaller area, and the rejection cap ends the run if it keeps trying.

---

## Step 8. `langgraph_runner.py`: `run_case_langgraph`

Build the point query once and pass it to the graph:

```python
    from outage_harness_langgraph.point_by_point_cover import query_point_coverage  # wherever the file lives

    point_query = make_point_query(query_point_coverage)   # the token default inside the function is used
    graph = build_investigation_graph(
        model, client, point_query=point_query,
        fetch_landuse_before_decision=fetch_landuse_before_decision,
        verifier=verifier, limits=limits,
    )
```

`make_point_query` calls `query_point_coverage(lat, lon, r)` with three
arguments, so the token must have a default in the function signature
(`token: str = "..."`). If it has none, pass it: `make_point_query(query_point_coverage, token)`.

The radius of each point call is the model's `resolution` (4, 10 or 100 m),
passed per call. `POINT_WORKERS` at the top of `runner_point_nodes.py` sets
how many point calls run at once; start with 4.

---

## Verified before you start

`python test_node_sequence.py` replays the node sequence of steps 7 and 8 with
the internal helpers (`_summarize`, `_update_state`, `ToolSuccess`,
`ToolFailure`, `RunGuard`) copied from the photographed files, then runs the
unchanged `gap_checks_partial.py` and the unchanged `completion_evidence_status`
on the resulting State. It passes: coverage round, inspection round, repeated
area rejected, cell-target gap rejected, resolution outside 4/10/100 rejected,
overlap skipped, budget rejection with the cost, all-calls-failed path, context
rendered after every round.

What that test cannot see, because the files are not here:

- the exact constructor of `ToolDeclaration`, `ToolSuccess` and `ToolFailure`
  in `client.py` (the test uses the field order the runner's own calls show);
- the real `radio.eligible_backup_cells` and `is_outage_cell` (the test double
  follows the regexes in `policy.py`);
- the LangGraph edges themselves, which do not change.

## Step 9. Skill text and first run with the fake API

In `investigation_skill.txt`, find the sentence that describes coverage
queries (heatmap, bounding box, resolution). Replace it with:

> A coverage query names one area and a resolution of 4, 10 or 100. The
> program fetches every analysis grid location of that area through the point
> API, one call per location with the resolution as the search radius in
> metres, and the cost is the number of locations fetched for the first time.
> Each sample lists its serving sector and the strongest neighbour cells with
> RSRP; a cell that is not listed is not shown to be absent.

Then run once with the fake API to check the wiring before any real call:

```python
from wiring.synthetic_case import fake_point_api      # or copy the function next to the runner
point_query = lambda lat, lon, r: fake_point_api(lat, lon, r)
```

Pass that `point_query` to `build_investigation_graph` instead of the real
one, with `max_steps=3`, and read `steps/step_01/LLM_input.txt` and
`state_01.json`. The context must show the lines "outage sectors ... are listed
at N of the V valid locations" and "Of those N locations, M also list an
eligible backup cell". The state must have `coverage[grid_id]["samples"]`.

---

## Step 10. Switch to the real API

1. Call `query_point_coverage` once by hand for the down site's own grid
   location with r = 4, 10 and 100. Count the samples and read one: confirm
   `info.serving.sector_name`, `info.topN.rsrp` and the coordinates are where
   `sample_cells` in `point_coverage.py` expects them. If the keys differ,
   change `sample_cells` only.
2. Confirm the samples are pre-outage (open gap 2 in the wiring note).
3. Run with `max_steps=2` and `max_query_locations=100` on the smallest
   settlement area, then read `artifacts/step_01_<area>.json` and the context.
4. Raise the limits.

---

## Two dead mentions of the heatmap name

After steps 3 to 7, the name `query_coverage_heatmap` survives in two places
that no code path reaches. Deleting them is optional but recommended:

- `runner.py`, `_update_state`, the branch `if action == "query_coverage_heatmap":`
  that writes `coverage["latest"]`. If it ever ran it would put a non-grid key
  into the coverage table, so delete the branch.
- `gap_checks.py`, the `RESULT_KIND` entry
  `"query_coverage_heatmap": "coverage_rows"`. A dead key; delete the line.

## What you do not touch

- `evidence_state.py`: `apply_kpi`, `split_geography`, `_geometry`, `_record`
  stay. `apply_coverage`, `_summary`, `_refresh`, `inspect_coverage` are no
  longer called for coverage; leave them or delete them later.
- `gap_checks.py`: reads `summaries[area]` counts and `cells_seen`; both are
  still produced.
- `parse_node`, `verifier_node`, `record_error_node`, `finish_check_node`,
  `write_cap_node`, `write_trace`: unchanged.
