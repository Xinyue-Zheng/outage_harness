"""Final report tool: the same report the finish node writes, callable from the tool library.

Replaces the previous report.py, which read the coverage heatmap CSV and
withheld every outcome share because a heatmap gives one serving sector per
point. With per-point coverage the outcome classes are computed from State
(completion_point.final_report). What survives from the previous version:
the Markdown plus JSON pair, the provenance block (every observation with its
artifact path), the run steps, and a KPI section. What is dropped: the
heatmap summary, the land-use sampling over a GeoJSON artifact (land use is
not demand; the area descriptions already carry it), and the one-week
reference comparison (the KPI baseline in State is built from several prior
weeks by apply_kpi).

final_step_report(run_dir, case_state_path=None) keeps the old signature so
a tool library that registers it keeps working. It is not offered to the
model: the finish node calls it after the completion check passes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from outage_harness_codex_state.radio import eligible_backup_cells, is_outage_cell

from .completion_point import completion_evidence_status, final_report

REPORT_TOOL_DESCRIPTION = "Write the final Markdown and JSON outage report from the run's State."


def _task_window(task: dict[str, Any]) -> tuple[str, str]:
    if task.get("start_time") and task.get("end_time"):
        return str(task["start_time"]), str(task["end_time"])
    window = str(task.get("outage_time", ""))
    if " through " in window:
        start, end = window.split(" through ", 1)
        return start, end
    return window, window


def _kpi_lines(state: dict[str, Any]) -> list[str]:
    baseline = state.get("kpi_baselines") or {}
    cells = baseline.get("cells") or {}
    if not cells:
        return ["No KPI baseline in State: no backup cell's load before the outage is known."]
    lines = [f"KPI baseline ({baseline.get('selection', 'selection not recorded')}):"]
    for cell, metrics in sorted(cells.items()):
        parts = []
        for metric, stats in sorted((metrics or {}).items()):
            if isinstance(stats, dict) and stats.get("mean") is not None:
                parts.append(f"{metric} mean {stats['mean']:g} over {stats.get('prior_week_count', '?')} prior weeks "
                             f"({stats.get('sample_count', '?')} samples)")
        lines.append(f"- {cell}: " + ("; ".join(parts) if parts else "no usable metric"))
    return lines


def _provenance(state: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for obs in state.get("observations") or []:
        result = obs.get("result") if isinstance(obs, dict) else None
        if not isinstance(result, dict):
            continue
        items.append({"id": obs.get("id"), "function": (obs.get("action") or {}).get("function") or obs.get("function"),
                      "area": obs.get("requested_area_id"), "file": result.get("output_file") or result.get("csv_path"),
                      "status": result.get("status")})
    return items


def build_report(state: dict[str, Any], run_dir: Path) -> tuple[str, dict[str, Any]]:
    """Markdown text and JSON twin from State. The check result is recomputed here so the
    report is the same whether the finish node or the tool writes it."""
    task = state["task"]
    is_outage = lambda cell: is_outage_cell(cell, task)  # noqa: E731
    backups = lambda cells: eligible_backup_cells(cells, task)  # noqa: E731
    checks = state.get("completion_checks") or completion_evidence_status(state, run_dir, is_outage)
    text, data = final_report(state, run_dir, is_outage, backups, checks)
    start, end = _task_window(task)
    body = ["# Final outage report: " + str(task.get("down_cell_id")), "",
            f"- Outage window: {start} to {end} (planned; not evidence that it happened)",
            f"- Objective: {task.get('objective', '')}",
            f"- Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"- Run end: {state.get('end_reason', 'complete')}; boundary check {checks.get('boundary', {}).get('status', 'unknown')}; "
            f"backup_load check {checks.get('backup_load', {}).get('status', 'unknown')} ({checks.get('backup_load', {}).get('reason', '')}).",
            "- Program-generated from the run's State; the model wrote none of it. A run ended by a cap keeps "
            "every unresolved item below as unknown.",
            "", "```", text.rstrip(), "```", "", "## KPI baseline", "", *_kpi_lines(state),
            "", "## Provenance", ""]
    for item in _provenance(state):
        body.append(f"- {item['id']}: {item['function']}" + (f" area {item['area']}" if item.get("area") else "")
                    + f"; {item['status']}; file {item['file']}")
    body.append("")
    report = {"report_type": "final_outage_investigation_report",
              "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "case": {"down_cell_id": task.get("down_cell_id"), "outage_cell_ids": task.get("outage_cell_ids"),
                       "start_time": start, "end_time": end, "objective": task.get("objective")},
              **data, "kpi_baselines": state.get("kpi_baselines"), "provenance": _provenance(state)}
    return "\n".join(body), report


def final_step_report(run_dir: Path, case_state_path: Path | None = None,
                      notebook_calculation_state_path: Path | None = None) -> Path:
    """Tool entry point, old signature. Reads state.json in run_dir (or case_state_path)."""
    run_dir = Path(run_dir).resolve()
    state_path = run_dir / "state.json"
    if not state_path.is_file() and case_state_path is not None:
        state_path = Path(case_state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"Expected a JSON object in {state_path}")
    markdown, report = build_report(state, run_dir)
    (run_dir / "final_report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    md_path = run_dir / "final_report.md"
    md_path.write_text(markdown, encoding="utf-8")
    return md_path
