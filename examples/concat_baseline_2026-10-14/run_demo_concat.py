"""Run the same scripted rounds under the rendered condition (context rendered from State) and the concat condition
(append-only transcript), on the synthetic case, and compare what the model would
have received.

    python run_demo_concat.py <output_dir>

Writes <output_dir>/rendered and <output_dir>/concat with LLM_input_NN.txt per round, the
hidden State per round, and <output_dir>/comparison.json with input size per
round, bytes truncated away in B, and the scoring facts from the State.

No model is called: the decisions are scripted and identical in both
conditions, so the comparison is about the input, not about a model's
behaviour. The live experiment (see CONCAT_STEP_BY_STEP_2026-10-14.md) runs
the same two conditions with the real model and scores both against the
hidden State.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "test_support"))
sys.path.insert(0, str(HERE))

from outage_harness_codex_state.radio import eligible_backup_cells, is_outage_cell  # noqa: E402

from harness import context_builder_concat as concat  # noqa: E402
from harness import runner_concat_nodes as rc  # noqa: E402
from harness.completion_point import completion_evidence_status  # noqa: E402
from harness.context_builder_point import build_context as build_rendered  # noqa: E402
from harness.point_coverage import apply_point_coverage, fetch_area_points  # noqa: E402
from harness.synthetic_case import TOOL_DECLARATIONS, build_case, fake_point_api  # noqa: E402
from harness.transcript import OUTPUT_CAP_BYTES  # noqa: E402

DECISIONS = [
    {"purpose": "Locate where the outage sectors serve around the site.",
     "gap": {"targets": ["S1"], "question": "Where do the outage sectors serve in S1?"},
     "action": {"function": "query_area_coverage", "parameters": {"area_id": "S1", "resolution": 10}}},
    {"purpose": "Follow the road out of the settlement.",
     "gap": {"targets": ["road_H1"], "question": "Do the outage sectors serve along H1?"},
     "action": {"function": "query_area_coverage", "parameters": {"area_id": "road_H1", "resolution": 10}}},
    {"purpose": "Check the hamlet east of the site.",
     "gap": {"targets": ["S2"], "question": "Does an outage sector reach S2 and which cell serves there?"},
     "action": {"function": "query_area_coverage", "parameters": {"area_id": "S2", "resolution": 10}}},
    {"purpose": "Done.", "gap": {"targets": ["F1"], "question": "Farmland left unqueried."},
     "action": {"function": "finish", "parameters": {}}},
]


class Guard:
    def __init__(self, limit: int) -> None:
        self.limits = type("L", (), {"max_query_locations": limit})()
        self.queried_locations = 0


def run_condition(condition: str, out: Path) -> dict:
    out.mkdir(parents=True)
    state = build_case(out)
    task = state["task"]
    guard = Guard(600)
    transcript = concat.new_transcript(state, TOOL_DECLARATIONS)
    rows = []
    completion = None
    for index, decision in enumerate(DECISIONS, start=1):
        if condition == "rendered":
            rendered = build_rendered(state, TOOL_DECLARATIONS)
        else:
            rendered = concat.build_context(transcript)
        (out / f"LLM_input_{index:02d}.txt").write_text(rendered.text, encoding="utf-8")
        name = decision["action"]["function"]
        if name == "finish":
            completion = completion_evidence_status(state, out, lambda c: is_outage_cell(c, task))
            rows.append({"round": index, "action": "finish", "input_chars": len(rendered.text)})
            break
        result = fetch_area_points(state, decision["action"]["parameters"]["area_id"], out, fake_point_api,
                                   radius_m=float(decision["action"]["parameters"]["resolution"]),
                                   call_id=f"step_{index:02d}")
        guard.queried_locations += result["details"]["fetched"]
        observation = {"id": f"real_obs_{index:02d}", "action": {**decision["action"], "requested_area_id":
                       decision["action"]["parameters"]["area_id"]}, "result": result}
        state = apply_point_coverage(state, observation, out, lambda c: is_outage_cell(c, task),
                                     lambda cs: eligible_backup_cells(cs, task))
        state["query_budget"] = {"locations_spent": guard.queried_locations, "locations_limit": 600}
        state["id"] = f"state_{index:02d}"
        (out / f"state_{index:02d}.json").write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
        raw = Path(result["output_file"]).read_text(encoding="utf-8")
        shown = rc.format_tool_output(name, result, out)
        rc.append_round(transcript, json.dumps(decision), name, result, None, out)
        visible_points = sum(1 for line in shown.splitlines() if '"grid_id"' in line)
        rows.append({"round": index, "action": f"{name} {decision['action']['parameters']['area_id']}",
                     "input_chars": len(rendered.text), "raw_output_bytes": len(raw.encode()),
                     "shown_output_bytes": len(shown.encode()),
                     "points_in_output": result["details"]["fetched"],
                     "points_visible_after_truncation": visible_points if condition == "concat" else None})
    return {"rounds": rows, "final_state_summary": rc.score_against_state(state, completion),
            "final_input_chars": rows[-1]["input_chars"]}


def main(output: Path) -> None:
    shutil.rmtree(output, ignore_errors=True)
    results = {condition: run_condition(condition, output / condition) for condition in ("rendered", "concat")}
    comparison = {"output_cap_bytes": OUTPUT_CAP_BYTES, "conditions": results}
    (output / "comparison.json").write_text(json.dumps(comparison, indent=1) + "\n", encoding="utf-8")
    print(f"{'round':>5} {'action':<28} {'rendered chars':>14} {'concat chars':>14} {'raw out':>9} {'shown':>7} {'pts':>4} {'visible':>8}")
    for a, b in zip(results["rendered"]["rounds"], results["concat"]["rounds"]):
        print(f"{a['round']:>5} {a['action']:<28} {a['input_chars']:>14} {b['input_chars']:>14} "
              f"{b.get('raw_output_bytes', ''):>9} {b.get('shown_output_bytes', ''):>7} "
              f"{b.get('points_in_output', ''):>4} {str(b.get('points_visible_after_truncation', '')):>8}")
    print("final hidden State (identical in rendered and concat):", json.dumps(results["rendered"]["final_state_summary"], indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
