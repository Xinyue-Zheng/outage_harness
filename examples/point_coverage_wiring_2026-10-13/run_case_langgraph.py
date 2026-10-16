"""The complete run_case_langgraph for langgraph_runner.py (TODO list, part E2).

Replace the whole function in the package with this one. Package-specific
edits, see part E2 of TODO_AFTER_STEP_10_2026-10-16.md:
- the make_task import: outage_harness_codex_state (concat) or outage_harness_langgraph (rendered);
- rendered package without the condition switch in build_investigation_graph:
  delete `condition=condition,` from the builder call and use `verifier=verifier`.

Imports this function relies on, already in langgraph_runner.py: Path, Any,
DecisionModel, RunLimits, InvestigationState, build_investigation_graph,
_write_json, _read_json, write_trace; plus PointQuery from point_coverage (E1).
"""


def run_case_langgraph(
    model: DecisionModel,
    client: Any,
    state_path: Path | dict[str, Any],
    output_dir: Path,
    *,
    max_steps: int = 8,
    case_evidence: dict[str, Any] | None = None,
    fetch_landuse_before_decision: bool = True,
    verifier: DecisionModel | None = None,
    limits: RunLimits | None = None,
    condition: str = "rendered",
    point_query: PointQuery | None = None,
) -> dict[str, Any]:
    if point_query is None:
        raise ValueError("point_query is required: build it with make_point_query")
    if isinstance(state_path, Path):
        raise ValueError("Pass a task dictionary, not a saved State or historical evidence file")
    if case_evidence:
        raise ValueError("Historical case evidence is not permitted")
    from outage_harness_<pkg>.task import make_task

    task = make_task(state_path["down_cell_id"], state_path["start_time"], state_path["end_time"],
                     state_path.get("outage_cell_ids"))
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    _write_json(output_dir / "task.json", {**task, "condition": condition})
    graph = build_investigation_graph(
        model, client, point_query=point_query, condition=condition,
        fetch_landuse_before_decision=fetch_landuse_before_decision,
        verifier=None if condition == "concat" else verifier, limits=limits,
    )
    initial: InvestigationState = {
        "case_state_path": (output_dir / "task.json").as_posix(),
        "output_dir": output_dir.as_posix(),
        "max_steps": max_steps,
        "system_prompt": (
            "You are an outage investigation planner. Follow the evidence boundary. "
            "Select one declared function, use only supported parameters, and return JSON."
        ),
        "task": task,
    }
    final = graph.invoke(initial, config={"recursion_limit": max_steps * 10 + 10})
    if not (output_dir / "run.json").is_file():
        summary = {
            "case_state": (output_dir / "task.json").as_posix(),
            "model": getattr(model, "model", type(model).__name__),
            "condition": condition,
            "steps": len(final.get("steps", [])),
            "finished": False,
            "end_reason": "step_cap",
            "observations": len(final.get("observations", [])),
            "tool_declaration_count": len(final.get("tools", ())),
            "orchestrator": "langgraph",
        }
        _write_json(output_dir / "run.json", summary)
        _write_json(output_dir / "steps.json", final.get("steps", []))
        _write_json(output_dir / "state.json", final.get("state", {}))
        write_trace(output_dir)
        return summary
    write_trace(output_dir)
    return _read_json(output_dir / "run.json")
