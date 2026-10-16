# What to do now, in one list

You have the concat package done through step 10 of
`CONCAT_STEP_BY_STEP_2026-10-14.md`, in the version with the condition switch
(`concat_mode`). Since then the completion check, the report and the KPI
reading changed. This list is everything left, for both packages. Do it in
order; each item names the file and the exact change.

Package names below: `outage_harness_langgraph` (rendered) and
`outage_harness_codex_state` (concat). "Both" means do it in each.

## A. Copy the changed modules (both)

From `examples/point_coverage_wiring_2026-10-13/` (rendered) or
`examples/concat_baseline_2026-10-14/` (concat; same files, package name
already swapped), copy over the versions in the package:

| file | why it changed |
|---|---|
| `point_coverage.py` | per-area counts `down_cell_covered`, `_with_backup`, `_without_backup` at -110 dBm; per-cell `covered` |
| `completion_point.py` | the direction-bin completion check, the report content, the new `finish_check` |
| `report.py` | replaces the old report tool; same `final_step_report(run_dir, case_state_path)` signature |
| `context_builder_point.py` | copy as `context_builder.py`; new completion text, per-direction lines, reads `kpi_baselines` |
| `investigation_skill_point.txt` (rendered) / `investigation_skill_concat.txt` (concat) | copy as `investigation_skill.txt`; new coverage and completion sentences |

Keep your old `report.py` elsewhere if you want it; the package copy is
`report_previous_heatmap.py` in the example folders.

## B. `finish_check_node` (both)

The signature of `finish_check` changed: it takes the outage predicate and
the backup selector, not `radio_technology`. Replace the imports and the
node.

Imports, next to the other package imports in `langgraph_runner.py`:

```python
from outage_harness_<pkg>.completion_point import completion_evidence_status, finish_check
from outage_harness_<pkg>.radio import eligible_backup_cells, is_outage_cell
```

Remove any import of `radio_technology` and of `completion_evidence_status`
from `policy`.

Rendered package, the whole node:

```python
    def finish_check_node(state: InvestigationState) -> dict[str, Any]:
        task = state["state"]["task"]
        return finish_check(state, lambda c: is_outage_cell(c, task),
                            lambda cells: eligible_backup_cells(cells, task), write_json=_write_json,
                            model_name=getattr(model, "model", type(model).__name__))
```

Concat package, the node from step 10, with the two changed lines:

```python
        if not concat_mode or COMPLETION_MODE == rc.COMPLETION_MODE_CHECKS:
            task = state["state"]["task"]
            return finish_check(state, lambda c: is_outage_cell(c, task),
                                lambda cells: eligible_backup_cells(cells, task), write_json=_write_json,
                                model_name=getattr(model, "model", type(model).__name__))
        task = state["state"]["task"]
        checks = completion_evidence_status(state["state"], state["output_dir"], lambda c: is_outage_cell(c, task))
```

The rest of the step 10 node stays. `finish_check` now writes
`final_report.md` and `final_report.json` itself through `report.build_report`;
it no longer calls `client.call("final_step_report", ...)`.

## C. Remove the report action from the model (both)

`final_step_report` is produced by the program after the check passes, never
requested by the model.

- `runner.py`, `DECISION_SCHEMA`, the `function` enum: delete `"final_step_report"`.
- `runner.py`, `PARAMETERS`: delete the `"final_step_report"` entry.
- `client.py` or wherever `TOOL_DECLARATIONS` is built: the model must not
  see it. Either remove its declaration or filter it out of `tools` in
  `initialize_node` next to the `query_coverage_heatmap` filter:
  `tools = tuple(t for t in tools if t.name not in {"query_coverage_heatmap", "final_step_report"})`.
- `gap_checks.py`: remove `"final_step_report"` from `_NO_TARGET_NEEDED` and
  from the result-kind table (the `"report"` entry).
- `policy.py`, `validate_live_action`: delete the `if name == "final_step_report":` branch.
- `context_builder.py` is already the copied one; it has no report line.

## D. `evidence_state.py` (both)

Your `apply_kpi` is complete. Two spelling fixes in strings the context
prints: `weekdat` to `weekday`, `invferred` to `inferred`. Nothing else;
the readers now use your key `kpi_baselines` and the metric `MEAN_PRB_USED`.

## E. The run script (both)

Copy `run_case.py` into each package next to `langgraph_runner.py`; set
`PACKAGE` at its top. In `langgraph_runner.py`, `run_case_langgraph` takes
`point_query` as a keyword (the script passes it) and writes
`{**task, "condition": condition}` to `task.json`. The script's `_model` and
`_client` must match your `llm.py` and `client.py` constructors.

## F. First runs

1. Rendered package, fake API, no model cost beyond the decisions:

```
python -m outage_harness_langgraph.run_case --condition rendered --fake-point-api \
    --down-cell CCL00001 --start-time 2026-02-10T09:00:00Z --end-time 2026-02-10T12:00:00Z \
    --output runs/fake_rendered --max-steps 8 --query-budget 300 \
    --base-url <your /v1 url> --model <name> --verifier-model <name> --ca-bundle <cert.pem>
```

   Expect: the context's "Completion checks" section shows the direction
   rule; after a finish the run directory has `final_report.md`, or
   `steps/step_NN/validation.json` shows "Completion refused" with the open
   directions.

2. Concat package, same command with `--condition concat` and the concat
   module name, no `--verifier-model`.

3. Then the real API, small `--query-budget`, one settlement.

## G. Not changed, on purpose

- The completion check counts only `settlement` and `road_corridor` areas.
  Activity areas are not a kind; they stay inside settlements.
- The transfer tool is yours. The report reads its output from
  `state["impact"]["backup_loads"]` (`cell_id`, `baseline_prb_percent`,
  `estimated_prb_percent`); until it runs, those locations are reported as
  "degrade, unknown cause".
- Scoring is not in the runner.
