"""Completion check and finish node for the per-point coverage path.

Replaces policy.completion_evidence_status and the finish_check_node of
langgraph_runner.py. Three things change against the heatmap version:

1. An area counts as fully queried when every grid location was fetched
   (queried == total). Locations with missing data are an API fact the model
   cannot change, so they no longer block completion. The heatmap rule also
   required valid == total and missing == 0, which a point query almost never
   reaches.

2. "Served" replaces "present" for the service distance. The point API lists
   an outage sector at a location whenever it is among the strongest
   neighbours, however weak. Counting those listings as service pushed the
   last service distance outward with every far query, and the boundary could
   never be closed. A sector is served in an area when it is the serving
   sector of at least one sample there (summary cells[cell]["serving"] > 0).
   It is absent from an area when it is never serving and never the strongest
   cell there.

3. The run can end. The old finish node refused every finish when the
   geography was initialized, because it returned the unmet checks
   unconditionally and backup_load was always unknown. Here a finish is
   accepted when every required check is complete; backup_load is reported
   but not required until a load computation exists. The final report is
   produced by the program after the checks pass, not by the model before.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BOUNDARY_KINDS = {"settlement", "road_corridor"}
REQUIRED_CHECKS = ("boundary",)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def completion_evidence_status(state: dict[str, Any], radio_technology: Any) -> dict[str, Any]:
    """Per outage sector: a fully queried settlement or road corridor farther from
    the site than the farthest area where the sector serves shows it absent."""
    summaries = state.get("summaries") or {}
    areas = state.get("geography", {}).get("areas") or {}
    outage_cells = [str(c) for c in state.get("outage_cells", []) if radio_technology(str(c))]

    boundary_areas: list[tuple[float, str, dict[str, Any]]] = []
    for area_id, area in areas.items():
        if area.get("kind") not in BOUNDARY_KINDS:
            continue
        distance = _number(area.get("nearest_distance_from_site_m"))
        if distance is not None:
            boundary_areas.append((distance, area_id, summaries.get(area_id, {})))
    complete = [(d, a, s) for d, a, s in boundary_areas
                if isinstance(s.get("total"), int) and s["total"] > 0 and s.get("queried") == s["total"]]

    def served(summary: dict[str, Any], cell: str) -> bool:
        stats = (summary.get("cells") or {}).get(cell) or {}
        return (stats.get("serving") or 0) > 0

    def absent(summary: dict[str, Any], cell: str) -> bool:
        stats = (summary.get("cells") or {}).get(cell) or {}
        return (stats.get("serving") or 0) == 0 and (stats.get("strongest") or 0) == 0

    unresolved: dict[str, str] = {}
    if not outage_cells:
        unresolved["outage_cells"] = "No LTE/NR outage sector has been observed in valid coverage evidence"
    for cell in outage_cells:
        served_distances = [d for d, _, s in boundary_areas if served(s, cell)]
        if not served_distances:
            unresolved[cell] = "No settlement or road corridor has a sample served by this outage sector"
            continue
        last = max(served_distances)
        beyond = [(d, a) for d, a, s in complete if d > last and absent(s, cell)]
        if not beyond:
            candidates = sorted((d, a) for d, a, s in boundary_areas
                                if d > last and s.get("queried", 0) != s.get("total"))
            hint = (f"; nearest not fully queried areas beyond it: "
                    + ", ".join(f"{a} ({d:g} m)" for d, a in candidates[:3])) if candidates else ""
            unresolved[cell] = (f"No fully queried settlement or road corridor farther than the last served "
                                f"area ({last:g} m) shows this sector never serving and never strongest{hint}")
    boundary = ({"status": "unknown",
                 "reason": "A queried area beyond the last served area must show each outage sector absent",
                 "unresolved": unresolved}
                if unresolved else
                {"status": "complete",
                 "reason": "Every observed outage sector has a fully queried settlement or road corridor "
                           "farther from the site than its last served area where it never serves and is "
                           "never strongest",
                 "outage_cells": outage_cells})
    return {
        "boundary": boundary,
        "backup_load": {"status": "unknown", "required": False,
                        "reason": "No verified backup-load computation exists yet; reported, not required"},
    }


def unmet_required(checks: dict[str, Any]) -> dict[str, Any]:
    return {name: check for name, check in checks.items()
            if name in REQUIRED_CHECKS and check.get("status") != "complete"}


# finish_check_node for langgraph_runner.py --------------------------------------
#
#     def finish_check_node(state: InvestigationState) -> dict[str, Any]:
#         return finish_check(state, client, radio_technology, write_json=_write_json,
#                             model_name=getattr(model, "model", type(model).__name__))
#
# The node no longer requires final_report before finish, and the model no
# longer calls final_step_report as an action: remove it from DECISION_SCHEMA's
# enum, from PARAMETERS and from TOOL_DECLARATIONS shown to the model, and drop
# the "report" line from the completion checks in the context builder.


def finish_check(state: dict[str, Any], client: Any, radio_technology: Any, *,
                 write_json: Any, model_name: str) -> dict[str, Any]:
    checks = completion_evidence_status(state["state"], radio_technology)
    unmet = unmet_required(checks)
    index = state["step_index"]
    output_dir = Path(state["output_dir"])
    if unmet:
        return {"state": {**state["state"], "completion_checks": checks},
                "error": "Completion refused: " + json.dumps(unmet)}
    inputs = state["state"].get("final_report_inputs") or {}
    report = client.call("final_step_report", dict(inputs), call_id=f"step_{index:02d}_report")
    if type(report).__name__ != "ToolSuccess":
        return {"state": {**state["state"], "completion_checks": checks},
                "error": f"Completion checks passed but the final report failed: {getattr(report, 'message', report)}"}
    final_state = {**state["state"], "completion_checks": checks, "final_report": report.output_file}
    finish_step = {"step": index, "decision": state["decision"], "status": "finished",
                   "completion_checks": checks, "final_report": report.output_file}
    steps = [*state["steps"], finish_step]
    write_json(output_dir / "steps.json", steps)
    write_json(output_dir / "state.json", final_state)
    step_dir = output_dir / "steps" / f"step_{index:02d}"
    write_json(step_dir / "finish.json", {"status": "finished", "completion_checks": checks})
    write_json(step_dir / "state_after.json", final_state)
    write_json(output_dir / f"state_{index:02d}.json", final_state)
    write_json(step_dir / "step.json", finish_step)
    write_json(output_dir / "run.json", {
        "case_state": state["case_state_path"], "model": model_name, "steps": len(steps),
        "finished": True, "end_reason": "complete", "observations": len(state["observations"]),
        "tool_declaration_count": len(state["tools"]), "final_report": report.output_file,
        "orchestrator": "langgraph",
    })
    return {"state": final_state, "steps": steps, "finished": True, "error": None}
