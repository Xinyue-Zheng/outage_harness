"""Replay the internal node sequence with the per-point pieces, outside LangGraph.

The graph nodes in langgraph_runner.py call these functions in this order for
one round: validate_node -> execute_tool_node -> update_state_node. This test
copies the internal helpers the nodes use (_summarize, _update_state,
ToolSuccess, ToolFailure, RunGuard with the budget patch) verbatim from the
photographed runner.py and policy.py, and runs the exact lines the step-by-step
note puts into the nodes. It then runs the internal gap checks
(gap_checks_partial.py, unchanged) and the internal completion check
(completion_evidence_status, extracted from policy_partial.py) on the State.

    python test_node_sequence.py
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "test_support"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from outage_harness_codex_state.radio import radio_technology  # noqa: E402

import gap_checks_partial as gap_checks  # noqa: E402  (internal module, unchanged)
import runner_point_nodes as rp  # noqa: E402
from context_builder_point import build_context  # noqa: E402
from point_coverage import inspect_point_coverage  # noqa: E402
from synthetic_case import TOOL_DECLARATIONS, build_case, fake_point_api  # noqa: E402


# --- Internal helpers, copied from runner_partial.py and the client usage in langgraph_runner.py.


@dataclass(frozen=True)
class ToolSuccess:
    name: str
    output_file: str
    row_count: int
    columns: tuple[str, ...]
    source: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolFailure:
    name: str
    error_type: str
    message: str


def _summarize(result: ToolSuccess | ToolFailure) -> dict[str, Any]:
    if isinstance(result, ToolFailure):
        return {"status": "error", "tool": result.name, "error_type": result.error_type, "error": result.message}
    return {
        "status": "success", "tool": result.name, "output_file": result.output_file,
        "row_count": result.row_count, "columns": list(result.columns), "source": result.source,
        **({"details": result.details} if result.details is not None else {}),
    }


def _update_state(state: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    observation_id = observation["id"]
    result = observation["result"]
    updated["observations"] = [
        *state.get("observations", []),
        {"observation_id": observation_id, "kind": observation["action"]["function"],
         "files": [result["output_file"]] if result.get("output_file") else [],
         "source": result.get("source", "tool_error")},
    ]
    updated["evidence_ids"] = [*state.get("evidence_ids", []), observation_id]
    if result.get("output_file"):
        updated["available"] = [*state.get("available", []), result["output_file"]]
    return updated


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class RunLimits:
    max_time_seconds: float | None = 3600.0
    max_tool_calls: int | None = 20
    max_consecutive_rejections: int | None = 3
    max_identical_queries: int | None = 2
    max_query_locations: int | None = 1500


@dataclass
class RunGuard:
    limits: RunLimits = field(default_factory=RunLimits)
    tool_calls: int = 0
    consecutive_rejections: int = 0
    query_counts: Counter = field(default_factory=Counter)
    queried_locations: int = 0
    check_locations = rp.guard_check_locations
    record_locations = rp.guard_record_locations

    def record_tool_call(self, name: str, args: dict) -> None:
        self.tool_calls += 1

    def record_validation(self, accepted: bool) -> None:
        self.consecutive_rejections = 0 if accepted else self.consecutive_rejections + 1


def _completion_evidence_status() -> Any:
    """completion_evidence_status, extracted unchanged from policy_partial.py."""
    source = (HERE.parent / "policy_partial.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "completion_evidence_status")
    namespace: dict[str, Any] = {"radio_technology": radio_technology}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "policy_partial.py", "exec"), namespace)
    return namespace["completion_evidence_status"]


# --- The node bodies, as the step-by-step note writes them.


def validate_node(decision: dict[str, Any], st: dict[str, Any], guard: RunGuard) -> dict[str, Any]:
    action_name = decision["action"]["function"]
    arguments = decision["action"]["parameters"]
    try:
        if action_name == "query_area_coverage":
            rp.validate_query_area_coverage(arguments, st["state"], st["output_dir"], guard)
        elif action_name == "inspect_observation":
            if (not all(isinstance(arguments[key], int) and not isinstance(arguments[key], bool)
                        for key in ("offset", "limit"))
                    or arguments["offset"] < 0 or not 1 <= arguments["limit"] <= 100):
                raise ValueError("Inspection needs offset >= 0 and limit between 1 and 100")
            inspect_point_coverage(st["state"], arguments["observation_id"], arguments["area_id"],
                                   arguments["offset"], arguments["limit"])
        gap_checks.check_gap(decision, action_name, arguments, st["state"])
        guard.record_validation(True)
        return {"action_name": action_name, "arguments": arguments, "error": None}
    except Exception as error:  # noqa: BLE001 - the node records any rejection
        guard.record_validation(False)
        return {"error": f"{type(error).__name__}: {error}"}


def execute_tool_node(st: dict[str, Any], guard: RunGuard, point_query: Any) -> dict[str, Any]:
    guard.record_tool_call(st["action_name"], st["arguments"])
    if st["action_name"] == "inspect_observation":
        arguments = st["arguments"]
        rows = inspect_point_coverage(st["state"], arguments["observation_id"], arguments["area_id"],
                                      arguments["offset"], arguments["limit"])
        path = Path(st["output_dir"]) / "artifacts" / f"inspection_{st['step_index']:02d}.json"
        _write_json(path, rows)
        result = ToolSuccess("inspect_observation", str(path), len(rows), ("grid_id", "status", "cells"),
                             source="state", details={"rows": rows})
        _write_json(Path(st["output_dir"]) / "steps" / f"step_{st['step_index']:02d}" / "tool_result.json",
                    _summarize(result))
        return {"tool_result": result}
    if st["action_name"] == "query_area_coverage":
        summary = rp.execute_query_area_coverage(st["state"], st["arguments"], st["output_dir"],
                                                 st["step_index"], point_query, guard)
        if summary["status"] == "success":
            result = ToolSuccess(summary["tool"], summary["output_file"], summary["row_count"],
                                 tuple(summary["columns"]), source=summary["source"], details=summary["details"])
        else:
            result = ToolFailure(summary["tool"], "PointApiFailure", summary["error"])
        return {"tool_result": result}
    raise AssertionError(st["action_name"])


def update_state_node(st: dict[str, Any], guard: RunGuard) -> dict[str, Any]:
    index = st["step_index"]
    summary = _summarize(st["tool_result"])
    decision = st["decision"]
    action = decision["action"]
    executed_parameters = action["parameters"]
    if st["action_name"] == "query_area_coverage":
        executed_parameters = json.loads(
            (Path(st["output_dir"]) / "steps" / f"step_{index:02d}" / "resolved_parameters.json").read_text())
        action = {**action, "parameters": executed_parameters, "requested_area_id": decision["action"]["parameters"]["area_id"]}
    observation = {"id": f"real_obs_{index:02d}", "purpose": decision["purpose"],
                   "information_gaps": decision["information_gaps"], "action": action, "result": summary}
    new_state = _update_state(st["state"], observation)
    if isinstance(new_state.get("observations"), list):
        new_state["observations"] = [*new_state["observations"], observation]
    if st["action_name"] == "query_area_coverage" and summary["status"] == "success":
        new_state = rp.update_state_query_area_coverage(new_state, observation, st["output_dir"], guard)
    if st["action_name"] == "inspect_observation" and summary["status"] == "success":
        new_state["inspection"] = {"step_index": index, **st["arguments"], "rows": summary["details"]["rows"]}
    new_state["id"] = f"state_{index:02d}"
    _write_json(Path(st["output_dir"]) / f"state_{index:02d}.json", new_state)
    return {"state": new_state, "step_index": index + 1, "tool_result": None, "error": None}


# --- The replay.


def decision(function: str, parameters: dict[str, Any], targets: list[str], question: str) -> dict[str, Any]:
    return {"purpose": question, "information_gaps": [question],
            "gap": {"targets": targets, "question": question},
            "action": {"function": function, "parameters": parameters}}


def run_round(st: dict[str, Any], guard: RunGuard, point_query: Any, d: dict[str, Any]) -> dict[str, Any]:
    st = {**st, "decision": d}
    st.update(validate_node(d, st, guard))
    if st.get("error"):
        print(f"  step {st['step_index']}: rejected: {st['error']}")
        return {**st, "step_index": st["step_index"] + 1}
    st.update(execute_tool_node(st, guard, point_query))
    st.update(update_state_node(st, guard))
    build_context(st["state"], TOOL_DECLARATIONS)  # must render without error after every round
    return st


def main() -> None:
    run_dir = (HERE / "replay_run").resolve()
    shutil.rmtree(run_dir, ignore_errors=True)
    state0 = build_case(run_dir)
    guard = RunGuard(RunLimits(max_query_locations=120))
    state0["query_budget"] = {"locations_spent": 0, "locations_limit": guard.limits.max_query_locations}

    def point_query(lat: float, lon: float, r: float) -> list[dict[str, Any]]:
        return fake_point_api(lat, lon, r)

    st: dict[str, Any] = {"state": state0, "output_dir": run_dir.as_posix(), "step_index": 1}
    print("round 1: coverage of S1")
    st = run_round(st, guard, point_query, decision("query_area_coverage", {"area_id": "S1", "resolution": 10}, ["S1"],
                                                    "Where do the outage sectors serve in S1?"))
    s1 = st["state"]["summaries"]["S1"]
    assert s1["queried"] == 30 and s1["down_cell_present"] > 0, s1
    assert st["state"]["query_budget"]["locations_spent"] == 30
    assert any(o.get("id") == "real_obs_01" and "fetched" in o["result"] for o in st["state"]["observations"])

    print("round 2: inspect real_obs_01 rows")
    st = run_round(st, guard, point_query, decision("inspect_observation",
                                                    {"observation_id": "real_obs_01", "area_id": "S1", "offset": 0, "limit": 5},
                                                    ["S1"], "Which cells are listed at the first S1 locations?"))
    assert len(st["state"]["inspection"]["rows"]) == 5

    print("round 3: coverage of S1 again (already fully queried) -> rejected")
    st = run_round(st, guard, point_query, decision("query_area_coverage", {"area_id": "S1", "resolution": 10}, ["S1"], "S1 again?"))
    assert "already fully queried" in st["error"] or "already answered" in st["error"], st["error"]

    print("round 4: gap targets a cell with a coverage query -> rejected by gap check")
    seen = st["state"]["cells_seen"][0]
    st = run_round(st, guard, point_query, decision("query_area_coverage", {"area_id": "road_H1", "resolution": 10}, [seen], "Cell?"))
    assert "action_cannot_answer_gap" in st["error"], st["error"]

    print("round 5: coverage of road_H1 (overlap with S1 is skipped)")
    st = run_round(st, guard, point_query, decision("query_area_coverage", {"area_id": "road_H1", "resolution": 10}, ["road_H1"],
                                                    "Does the outage sector serve along the road?"))
    road = st["state"]["summaries"]["road_H1"]
    obs = next(o for o in st["state"]["observations"] if o.get("id") == "real_obs_05")
    assert obs["result"]["skipped_already_queried"] == 18 and road["queried"] == 60, obs["result"]
    assert st["state"]["query_budget"]["locations_spent"] == 72

    print("round 6a: resolution outside 4/10/100 -> rejected before any API call")
    st = run_round(st, guard, point_query, decision("query_area_coverage", {"area_id": "F1", "resolution": 50}, ["F1"], "F1?"))
    assert "resolution must be one of" in st["error"], st["error"]

    print("round 6: F1 does not fit the remaining budget -> rejected with the cost")
    st = run_round(st, guard, point_query, decision("query_area_coverage", {"area_id": "F1", "resolution": 100}, ["F1"], "F1?"))
    assert "would fetch 54 locations" in st["error"], st["error"]

    print("round 7: every point call fails -> ToolFailure, nothing enters the table")
    def broken(lat: float, lon: float, r: float) -> list[dict[str, Any]]:
        raise ConnectionError("API down")
    before = dict(st["state"]["coverage"])
    st = run_round(st, RunGuard(RunLimits(max_query_locations=1000)), broken,
                   decision("query_area_coverage", {"area_id": "S2", "resolution": 4}, ["S2"], "S2?"))
    assert st["state"]["coverage"] == before
    assert st["state"]["summaries"]["S2"]["queried"] == 8  # the 8 S2 locations the road corridor covered earlier

    print("completion check (internal policy function) on the final State:")
    status = _completion_evidence_status()(st["state"])
    print("  boundary:", status["boundary"]["status"], "-", json.dumps(status["boundary"].get("unresolved", {}))[:160])
    print("  backup_load:", status["backup_load"]["status"])
    print("OK: node sequence, gap checks, budget, failure path and context rendering all pass.")
    shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
