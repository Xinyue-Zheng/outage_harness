"""Completion check and final report on the synthetic case.

    python run_demo_report.py <output_dir>

Queries S1, road_H1 and S2 through the fake point API, adds a synthetic
KPI baseline for one backup and a synthetic transfer estimate (what the
transfer tool would write to state["impact"]), then runs the completion
check and writes final_report.txt and final_report.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "test_support"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from outage_harness_codex_state.radio import eligible_backup_cells, is_outage_cell  # noqa: E402

from harness.completion_point import completion_context_lines, completion_evidence_status, unmet_required  # noqa: E402
from harness.report import final_step_report  # noqa: E402
from harness.point_coverage import apply_point_coverage, fetch_area_points  # noqa: E402
from harness.synthetic_case import build_case, fake_point_api  # noqa: E402

RESOLUTION = 10


def main(run_dir: Path) -> None:
    state = build_case(run_dir)
    task = state["task"]
    is_outage = lambda cell: is_outage_cell(cell, task)  # noqa: E731
    backups = lambda cells: eligible_backup_cells(cells, task)  # noqa: E731
    for step, area_id in enumerate(("S1", "road_H1", "S2"), start=1):
        result = fetch_area_points(state, area_id, run_dir, fake_point_api, radius_m=float(RESOLUTION), call_id=f"step_{step:02d}")
        observation = {"id": f"real_obs_{step:02d}", "action": {"function": "query_area_coverage",
                       "parameters": {"area_id": area_id, "resolution": RESOLUTION}}, "result": result}
        state = apply_point_coverage(state, observation, run_dir, is_outage, backups)
        checks = completion_evidence_status(state, run_dir, is_outage)
        print(f"after {area_id}: unmet {list(unmet_required(checks))}")
        for line in completion_context_lines(checks):
            print("  " + line)
    # What the KPI tool and the transfer tool would leave in State (synthetic values).
    state["kpi_baselines"] = {"selection": "same weekday and hours, 4 prior weeks", "reference_time": task["start_time"],
                             "cells": {"CCL00002_aa_1": {"MEAN_PRB_USED": {"mean": 41.0, "prior_week_count": 4, "sample_count": 12}},
                                       "CCL00001_aa_1": {"MEAN_PRB_USED": {"mean": 35.0, "prior_week_count": 4, "sample_count": 12}},
                                       "CCL00001_ab_1": {"MEAN_PRB_USED": {"mean": 28.0, "prior_week_count": 4, "sample_count": 12}}}}
    state["impact"] = {"source": "transfer_tool", "backup_loads": [
        {"cell_id": "CCL00002_aa_1", "assigned_locations": 0, "baseline_prb_percent": 41.0, "estimated_prb_percent": 86.0}]}
    checks = completion_evidence_status(state, run_dir, is_outage)
    state["completion_checks"] = checks
    (run_dir / "state.json").write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    md_path = final_step_report(run_dir)
    print()
    print(md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
