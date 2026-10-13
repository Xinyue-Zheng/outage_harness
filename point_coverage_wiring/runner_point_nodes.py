"""Runner-side pieces for the per-point coverage path.

These replace the heatmap-specific parts of langgraph_runner.py, runner.py and
policy.py. Each item names the function it replaces. Nothing else in the
graph changes: parse, verifier, record_error, finish_check and the caps stay.

1. Tool declaration and decision schema: query_area_coverage takes area_id only.
2. RunLimits/RunGuard: a location budget, so the per-point cost is capped by
   the program, not by the model.
3. validate_node branch: area must exist, cost must fit the budget.
4. execute_tool_node branch: fetch the area's grid locations through the point
   API; no bounding box.
5. update_state_node branch: fold the artifact with apply_point_coverage.
6. inspect_observation: read rows from the coverage table.

The point API client is one function `query_point_coverage(lat, lon, r, token)`.
`make_point_query` binds radius and token so the runner passes a plain
(lat, lon, radius_m) -> samples callable, and secrets never enter State.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from outage_harness_langgraph.radio import eligible_backup_cells, is_outage_cell

from point_coverage import (
    PointQuery,
    apply_point_coverage,
    fetch_area_points,
    inspect_point_coverage,
    read_geometry,
)

# 1. Declaration and schema -----------------------------------------------------

QUERY_AREA_COVERAGE = {
    "name": "query_area_coverage",
    "description": (
        "Fetch pre-outage coverage at every analysis grid location of one listed area "
        "through the point API: for each location, every sample within the radius with "
        "its serving sector and strongest neighbour cells and their RSRP."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"area_id": {"type": "string"}},
        "required": ["area_id"],
        "additionalProperties": False,
    },
}

# runner.PARAMETERS: replace the query_area_coverage entry and drop the heatmap.
PARAMETERS_PATCH = {
    "query_area_coverage": {"area_id"},
    "inspect_observation": {"observation_id", "area_id", "offset", "limit"},
}
# runner.DECISION_SCHEMA["properties"]["action"]["properties"]["function"]["enum"]:
# remove "query_coverage_heatmap". The model has no bounding boxes to give.

# Program configuration, never shown to the model as a parameter.
POINT_RADIUS_M = 50.0
POINT_WORKERS = 4


def make_point_query(query_point_coverage: Callable[..., list[dict[str, Any]]], token: str,
                     radius_m: float = POINT_RADIUS_M) -> PointQuery:
    """Bind the API function to the run's radius and token."""

    def query(lat: float, lon: float, r: float) -> list[dict[str, Any]]:
        return query_point_coverage(str(lat), str(lon), str(int(r)), token)

    return query


# 2. Budget -----------------------------------------------------------------------
#
# policy.RunLimits: add
#     max_query_locations: int | None = 1500
# policy.RunGuard: add
#     queried_locations: int = 0
# and the two methods below (paste into the class).


def guard_check_locations(self: Any, new_locations: int) -> str | None:
    """None when the budget allows the query; else the typed end reason."""
    limit = self.limits.max_query_locations
    if limit is None:
        return None
    if self.queried_locations + new_locations > limit:
        return "query_budget"
    return None


def guard_record_locations(self: Any, new_locations: int) -> None:
    self.queried_locations += new_locations


def new_locations(state: dict[str, Any], area_id: str, run_dir: str | Path) -> int:
    """The cost of a coverage query: grid locations of the area not in the table yet."""
    geometry = read_geometry(state, run_dir)
    table = state.get("coverage") or {}
    return sum(str(g) not in table for g in geometry["areas"][area_id]["grid_ids"])


# 3. validate_node branch ---------------------------------------------------------


def validate_query_area_coverage(arguments: dict[str, Any], state: dict[str, Any],
                                 run_dir: str | Path, guard: Any) -> None:
    """Replaces the `if action_name == "query_area_coverage":` block in validate_node.

    Raises ValueError for a rejection, as the other branches do. A budget
    overrun is a rejection with the cost in the message, so the model can
    choose a smaller area; the run ends as query_budget only when no key
    area fits any more (left to loop_or_end, see the wiring note).
    """
    geometry = read_geometry(state, run_dir)
    if arguments["area_id"] not in geometry["areas"]:
        raise ValueError("Choose a listed area_id")
    cost = new_locations(state, arguments["area_id"], run_dir)
    if cost == 0:
        raise ValueError(f"{arguments['area_id']} is already fully queried; no location would be fetched")
    limit = guard.limits.max_query_locations
    if limit is not None and guard.queried_locations + cost > limit:
        raise ValueError(
            f"query_area_coverage {arguments['area_id']} would fetch {cost} locations, but only "
            f"{limit - guard.queried_locations} of the {limit}-location budget remain"
        )


# 4. execute_tool_node branch -----------------------------------------------------


def execute_query_area_coverage(state: dict[str, Any], arguments: dict[str, Any], run_dir: str | Path,
                                step_index: int, query: PointQuery, guard: Any) -> dict[str, Any]:
    """Replaces the `if state["action_name"] == "query_area_coverage":` block.

    Returns the result summary dict (the shape runner._summarize produces) and
    writes steps/step_NN/tool_result.json. No ToolSuccess object is needed:
    _update_state reads the summary fields.
    """
    result = fetch_area_points(
        state, arguments["area_id"], run_dir, query,
        radius_m=POINT_RADIUS_M, call_id=f"step_{step_index:02d}", workers=POINT_WORKERS,
    )
    guard.record_locations(result["details"]["fetched"])
    step_dir = Path(run_dir) / "steps" / f"step_{step_index:02d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "resolved_parameters.json").write_text(
        json.dumps({"area_id": arguments["area_id"], "radius_m": POINT_RADIUS_M,
                    "fetched": result["details"]["fetched"]}, indent=2) + "\n", encoding="utf-8")
    (step_dir / "tool_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


# 5. update_state_node branch -----------------------------------------------------


def update_state_query_area_coverage(state: dict[str, Any], observation: dict[str, Any],
                                     run_dir: str | Path, guard: Any) -> dict[str, Any]:
    """Replaces the coverage branch of update_state_node.

    `observation` is the dict the node builds (id, purpose, information_gaps,
    action, result). The coverage table, summaries, cell lists, unknowns and
    the observation record are updated by apply_point_coverage; the budget
    line in State mirrors the guard so the context can show it.
    """
    task = state["task"]
    updated = apply_point_coverage(
        state, observation, run_dir,
        lambda cell: is_outage_cell(cell, task),
        lambda cells: eligible_backup_cells(cells, task),
    )
    updated["coverage_artifacts"] = {**state.get("coverage_artifacts", {}), "latest": observation["result"]}
    updated["query_budget"] = {"locations_spent": guard.queried_locations,
                               "locations_limit": guard.limits.max_query_locations}
    failed = observation["result"].get("details", {}).get("error_points", 0)
    if failed:
        updated["notes"] = [*updated.get("notes", []), {
            "kind": "query_failed", "step_index": int(observation["id"].rsplit("_", 1)[-1]),
            "text": f"{failed} point calls of {observation['action']['parameters']['area_id']} failed; "
                    "those locations stay unqueried and can be fetched again.",
        }]
    return updated


# 6. inspect_observation -----------------------------------------------------------
# In validate_node and execute_tool_node, call inspect_point_coverage instead of
# evidence_state.inspect_coverage. The rows carry status, area_ids, sample_count
# and per-cell aggregates (rsrp min/max/mean, sample_count, serving_count); the
# raw samples stay in the table and the artifact.
__all__ = [
    "PARAMETERS_PATCH", "QUERY_AREA_COVERAGE", "execute_query_area_coverage", "guard_check_locations",
    "guard_record_locations", "inspect_point_coverage", "make_point_query", "new_locations",
    "update_state_query_area_coverage", "validate_query_area_coverage",
]
