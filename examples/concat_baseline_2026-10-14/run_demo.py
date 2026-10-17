"""Run the per-point wiring end to end on the synthetic case.

    python run_demo.py <output_dir>

Steps: build State 0 and geography.json; fetch S1 and road_H1 through the fake
point API (one call per grid location); fold each artifact into State; render
the context after each round; inspect one observation. Everything the real
runner would write for these steps lands in <output_dir>.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "test_support"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from outage_harness_codex_state.radio import eligible_backup_cells, is_outage_cell  # noqa: E402

from harness.completion_point import completion_evidence_status  # noqa: E402
from harness.context_builder_point import build_context  # noqa: E402
from harness.point_coverage import apply_point_coverage, fetch_area_points, inspect_point_coverage  # noqa: E402
from harness.synthetic_case import TOOL_DECLARATIONS, build_case, fake_point_api  # noqa: E402

RESOLUTION = 10  # the model's choice: the point-API radius in metres


def main(run_dir: Path) -> None:
    state = build_case(run_dir)
    task = state["task"]

    def is_outage(cell: str) -> bool:
        return is_outage_cell(cell, task)

    def backups(cells: object) -> list[str]:
        return eligible_backup_cells(cells, task)  # type: ignore[arg-type]

    rendered = build_context(state, TOOL_DECLARATIONS)
    (run_dir / "context_00.txt").write_text(rendered.text, encoding="utf-8")
    for step, area_id in enumerate(("S1", "road_H1"), start=1):
        result = fetch_area_points(state, area_id, run_dir, fake_point_api, radius_m=float(RESOLUTION),
                                   call_id=f"step_{step:02d}")
        observation = {
            "id": f"real_obs_{step:02d}",
            "purpose": f"Coverage of {area_id}",
            "action": {"function": "query_area_coverage", "parameters": {"area_id": area_id, "resolution": RESOLUTION},
                       "requested_area_id": area_id},
            "result": result,
        }
        state = apply_point_coverage(state, observation, run_dir, is_outage, backups)
        state["completion_checks"] = completion_evidence_status(state, run_dir, is_outage)  # as update_state_node does
        state["query_budget"]["locations_spent"] += result["details"]["fetched"]
        state["id"] = f"state_{step:02d}"
        (run_dir / f"state_{step:02d}.json").write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
        rendered = build_context(state, TOOL_DECLARATIONS)
        (run_dir / f"context_{step:02d}.txt").write_text(rendered.text, encoding="utf-8")
        print(f"step {step}: {area_id}: {result['details']}")
    rows = inspect_point_coverage(state, "real_obs_01", "S1", 0, 12)
    state["inspection"] = {"step_index": 3, "observation_id": "real_obs_01", "area_id": "S1", "offset": 0, "limit": 12,
                           "rows": rows}
    rendered = build_context(state, TOOL_DECLARATIONS)
    (run_dir / "context_03_inspection.txt").write_text(rendered.text, encoding="utf-8")
    summary = state["summaries"]["S1"]
    print("S1 summary:", {k: v for k, v in summary.items() if k != "cells"})
    for cell, stats in summary["cells"].items():
        print("  ", cell, stats)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
