"""Runner-side pieces for the concatenation baseline (the concat condition).

The rendered condition is the harness as wired in ../wiring: the model reads a context
rendered from State, the program validates gap targets and preconditions,
and completion checks decide the end.

The concat condition keeps the same tools, the same State machinery (hidden, for
evaluation), the same caps, and changes four things to match how Codex CLI
drives a model:

1. Model input is the append-only transcript (transcript.py), not a rendering
   of State. Each tool result is appended as the raw output, truncated.
2. Validation is schema-only: tool name known, parameters match the declared
   schema, area id exists. No gap checks, no budget message with cost (the
   budget cap still ends the run, as a cap, not as feedback the model can act
   on). A rejection goes back as an error output, as Codex returns a tool error.
3. finish is accepted when the model proposes it. The completion checks still
   run, but only to score the run; they do not refuse the finish.
4. No verifier.

What the program still does in B: resolve area ids to points, call the point
API, write artifacts, update the hidden State, enforce caps, write the Step.

Every function here states which node it belongs to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from outage_harness_codex_state.radio import eligible_backup_cells, is_outage_cell

from .point_coverage import apply_point_coverage, fetch_area_points, inspect_point_coverage, read_geometry
from .transcript import Transcript, format_rejection, format_tool_output

COMPLETION_MODE_MODEL = "model"      # finish accepted as proposed (Codex behaviour)
COMPLETION_MODE_CHECKS = "checks"    # finish refused until the program checks pass (concat+checks)


# validate_node ------------------------------------------------------------------


def validate_schema_only(decision: dict[str, Any], tools: list[Any], state: dict[str, Any],
                         run_dir: str | Path, allowed_resolutions: tuple[float, ...]) -> tuple[str, dict[str, Any]]:
    """Name known, parameters as declared, area id listed. Nothing about State."""
    action = decision.get("action")
    if not isinstance(action, dict):
        raise ValueError("action must be an object")
    name, arguments = action.get("function"), action.get("parameters")
    if name == "finish":
        return "finish", {}
    declared = {(t["name"] if isinstance(t, dict) else t.name): (t["input_schema"] if isinstance(t, dict) else t.input_schema)
                for t in tools}
    if name not in declared:
        raise ValueError(f"Unknown tool: {name!r}")
    if not isinstance(arguments, dict):
        raise ValueError("action.parameters must be an object")
    schema = declared[name]
    expected = set(schema.get("required", []))
    if set(arguments) != expected:
        raise ValueError(f"{name} needs exactly {sorted(expected)}")
    if name == "query_area_coverage":
        geometry = read_geometry(state, run_dir)
        if arguments["area_id"] not in geometry["areas"]:
            raise ValueError("Choose a listed area_id")
        if arguments.get("resolution") not in allowed_resolutions:
            raise ValueError(f"resolution must be one of {list(allowed_resolutions)}")
    return name, arguments


# execute_tool_node -----------------------------------------------------------------


def execute_concat(name: str, arguments: dict[str, Any], state: dict[str, Any], run_dir: str | Path,
                   step_index: int, point_query: Any, workers: int) -> dict[str, Any]:
    """Same execution as the rendered condition; returns the result summary dict."""
    if name == "query_area_coverage":
        return fetch_area_points(state, arguments["area_id"], run_dir, point_query,
                                 radius_m=float(arguments["resolution"]), call_id=f"step_{step_index:02d}",
                                 workers=workers)
    if name == "inspect_observation":
        rows = inspect_point_coverage(state, arguments["observation_id"], arguments["area_id"],
                                      arguments["offset"], arguments["limit"])
        path = Path(run_dir) / "artifacts" / f"inspection_{step_index:02d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        return {"status": "success", "tool": name, "output_file": str(path), "row_count": len(rows),
                "columns": ["grid_id", "status", "cells"], "source": "state", "details": {"rows": rows}}
    raise ValueError(f"No executor for {name}")


# update_state_node -----------------------------------------------------------------


def update_hidden_state(state: dict[str, Any], observation: dict[str, Any], run_dir: str | Path,
                        guard: Any) -> dict[str, Any]:
    """The concat condition keeps State for scoring only. Same update as the rendered condition."""
    task = state["task"]
    name = observation["action"]["function"]
    if name == "query_area_coverage" and observation["result"]["status"] == "success":
        updated = apply_point_coverage(
            state, observation, run_dir,
            lambda cell: is_outage_cell(cell, task),
            lambda cells: eligible_backup_cells(cells, task),
        )
        updated["query_budget"] = {"locations_spent": guard.queried_locations,
                                   "locations_limit": guard.limits.max_query_locations}
        return updated
    items = [*state.get("observations", []), {"id": observation["id"], "action": observation["action"],
                                               "result": observation["result"]}]
    return {**state, "observations": items}


def append_round(transcript: Transcript, raw_reply: str, name: str | None, result: dict[str, Any] | None,
                 rejection: str | None, run_dir: str | Path) -> None:
    """What the model sees of one round in the concat condition: its reply, then the raw output."""
    transcript.assistant(raw_reply)
    if rejection is not None:
        transcript.tool(name or "decision", format_rejection(rejection))
        return
    if name is not None and result is not None:
        transcript.tool(name, format_tool_output(name, result, run_dir))


# scoring ---------------------------------------------------------------------------


def score_against_state(state: dict[str, Any], completion_status: dict[str, Any] | None) -> dict[str, Any]:
    """A summary of the final hidden State for the demo printout. Not a score: what a run
    is judged by is not decided; scoring is a separate script over run directories."""
    study = (state.get("summaries") or {}).get("study_area") or {}
    return {
        "locations_queried": study.get("queried"),
        "locations_valid": study.get("valid"),
        "down_cell_present": study.get("down_cell_present"),
        "down_cell_with_backup": study.get("down_cell_with_backup"),
        "down_cell_without_backup": study.get("down_cell_without_backup"),
        "outage_cells": study.get("outage_cells"),
        "backup_candidates": study.get("backup_candidates"),
        "areas_fully_queried": sorted(a for a, s in (state.get("summaries") or {}).items()
                                      if s.get("queried") == s.get("total")),
        "completion": completion_status,
    }
