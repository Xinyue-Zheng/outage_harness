"""Check that a package has every edit from TODO_AFTER_STEP_10_2026-10-16.md.

    python check_package.py outage_harness_codex_state
    python check_package.py outage_harness_langgraph

Run from the directory that contains the package. Prints one line per check:
OK, or MISSING with the part of the TODO list that fixes it. Reads files
only; nothing is imported or executed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main(package: str) -> int:
    root = Path(package)
    if not root.is_dir():
        print(f"no directory {package} here; run from the directory that contains it")
        return 2
    concat = package.endswith("codex_state")

    def text(name: str) -> str:
        path = root / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    checks: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, fix: str) -> None:
        checks.append((label, ok, fix))

    # A. modules
    pc, cp, rp, rpn, cb, skill = (text(n) for n in (
        "point_coverage.py", "completion_point.py", "report.py", "runner_point_nodes.py",
        "context_builder.py", "investigation_skill.txt"))
    check("point_coverage.py is the -110 dBm version", "COVERAGE_RSRP_DBM = -110.0" in pc, "A: copy harness/point_coverage.py")
    check("completion_point.py is the direction-bin version", "BIN_DEGREES = 30.0" in cp, "A: copy harness/completion_point.py")
    check("report.py is the State-based version", "def build_report" in rp, "A: copy harness/report.py")
    check("runner_point_nodes.py defines AREA_RESOLUTIONS", "AREA_RESOLUTIONS = (" in rpn, "A: copy harness/runner_point_nodes.py")
    check("context_builder.py reads kpi_baselines", 'state.get("kpi_baselines")' in cb, "A: copy harness/context_builder_point.py as context_builder.py")
    check("investigation_skill.txt has the point-coverage sentence", "serving or not" in skill, "A: copy harness/investigation_skill.txt")
    if concat:
        check("investigation_skill.txt is the concat variant", "rendered structured State" not in skill and skill != "",
              "A: the concat package needs the concat skill (no sentences about the rendered context)")
    for name, pattern in (("report.py", r"^from \.completion_point import"),
                          ("completion_point.py", r"^from \.point_coverage import"),
                          ("completion_point.py", r"from \.report import build_report"),
                          ("runner_point_nodes.py", r"^from \.point_coverage import"),
                          ("context_builder.py", r"from \.completion_point import completion_context_lines")):
        check(f"{name}: relative import", re.search(pattern, text(name), re.M) is not None, f"A: relative imports table, {name}")
    for name, pattern in (("report.py", r"^from completion_point import"), ("completion_point.py", r"^from point_coverage import"),
                          ("runner_point_nodes.py", r"^from point_coverage import")):
        check(f"{name}: no bare import left", re.search(pattern, text(name), re.M) is None, f"A: relative imports table, {name}")
    if concat:
        for name in ("context_builder_concat.py", "runner_concat_nodes.py", "transcript.py"):
            check(f"{name} present", (root / name).is_file(), f"concat note step 1: copy {name}")
        check("runner_concat_nodes.py: relative imports", re.search(r"^from \.(point_coverage|transcript) import", text("runner_concat_nodes.py"), re.M) is not None,
              "A: relative imports table, runner_concat_nodes.py")
        check("context_builder_concat.py: relative import", "from .transcript import Transcript" in text("context_builder_concat.py"),
              "A: relative imports table, context_builder_concat.py")

    # B. finish node and imports in langgraph_runner.py
    lr = text("langgraph_runner.py")
    check("langgraph_runner.py imports finish_check from completion_point",
          re.search(r"from \S+\.completion_point import .*finish_check", lr) is not None, "B: imports")
    check("langgraph_runner.py imports is_outage_cell and eligible_backup_cells from radio",
          re.search(r"from \S+\.radio import .*eligible_backup_cells", lr) is not None and "is_outage_cell" in lr, "B: imports")
    check("langgraph_runner.py no longer imports completion_evidence_status from policy",
          re.search(r"from \S+\.policy import[^)]*completion_evidence_status", lr, re.S) is None, "B: remove it from the policy import block")
    check("finish_check_node calls finish_check with is_outage_cell",
          re.search(r"def finish_check_node.*?finish_check\(state, lambda c: is_outage_cell", lr, re.S) is not None, "B: replace finish_check_node")
    check("finish_check_node no longer calls completion_evidence_status(state[\"state\"]) with one argument",
          'completion_evidence_status(state["state"])' not in lr, "B: replace finish_check_node")
    check("no client.call(\"final_step_report\" in the runner", 'client.call("final_step_report"' not in lr, "B: finish_check writes the report itself")
    check("langgraph_runner.py imports PointQuery", "PointQuery" in lr, "E1: add PointQuery to the point_coverage import")
    check("run_case_langgraph takes point_query", re.search(r"def run_case_langgraph\(.*?point_query: PointQuery \| None = None", lr, re.S) is not None, "E2: replace run_case_langgraph")
    check("run_case_langgraph passes point_query to the builder", "point_query=point_query" in lr, "E2: replace run_case_langgraph")
    check("run_case_langgraph does not build the point query itself", "make_point_query(" not in lr.split("def run_case_langgraph")[-1] if "def run_case_langgraph" in lr else False,
          "E2: delete the make_point_query line inside run_case_langgraph")
    check("task.json records the condition", '{**task, "condition": condition}' in lr, "E2: replace run_case_langgraph")
    if concat:
        check("concat_mode switch present", "concat_mode" in lr, "concat note step 2b")
        check("COMPLETION_MODE constant present", "COMPLETION_MODE" in lr, "concat note step 10")

    # C. the report action removed from the model
    runner, policy, gaps, client = text("runner.py"), text("policy.py"), text("gap_checks.py"), text("client.py")
    check("runner.py: final_step_report not in DECISION_SCHEMA or PARAMETERS", '"final_step_report"' not in runner, "C: runner.py")
    check("policy.py: no final_step_report branch in validate_live_action", 'if name == "final_step_report"' not in policy, "C: policy.py")
    check("gap_checks.py: final_step_report removed", '"final_step_report"' not in gaps, "C: gap_checks.py")
    check("the model does not see final_step_report",
          '"final_step_report"' not in client or "final_step_report" in (lr.split("initialize_node")[-1].split("def render_context_node")[0] if "initialize_node" in lr else ""),
          "C: remove its declaration, or filter it out of tools in initialize_node")

    # D. apply_kpi spelling
    es = text("evidence_state.py")
    check("evidence_state.py writes kpi_baselines", "kpi_baselines" in es, "D: apply_kpi must write state['kpi_baselines']")
    check("evidence_state.py: 'weekdat' typo fixed", "weekdat" not in es, "D")
    check("evidence_state.py: 'invferred' typo fixed", "invferred" not in es, "D")

    # E. run script
    rc = text("run_case.py")
    check("run_case.py present", rc != "", "E3: copy run_case.py")
    check(f"run_case.py PACKAGE = \"{package}\"", f'PACKAGE = "{package}"' in rc, "E3: set PACKAGE on line 38")
    check("run_case.py builds OpenAICompatLLM() and RealToolClient(artifacts)", "OpenAICompatLLM()" in rc and 'RealToolClient(arguments.output / "artifacts")' in rc, "E4/E5: copy run_case.py again")

    width = max(len(label) for label, _, _ in checks) + 2
    missing = 0
    for label, ok, fix in checks:
        print(f"{'OK     ' if ok else 'MISSING'} {label:<{width}}{'' if ok else '-> ' + fix}")
        missing += not ok
    print(f"\n{len(checks) - missing} of {len(checks)} checks pass for {package}.")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "outage_harness_codex_state"))
