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

Five edits. E1 and E2 are in `langgraph_runner.py`; E3 to E5 are in the
copied `run_case.py`. Do them in each package.

**E1. `run_case_langgraph` takes `point_query`.** Find the signature
(original line 677):

```python
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
) -> dict[str, Any]:
```

Add two keywords at the end of the parameter list (after `limits`):

```python
    limits: RunLimits | None = None,
    condition: str = "rendered",
    point_query: PointQuery | None = None,
) -> dict[str, Any]:
```

(`condition` is already there if you added it in step 2c of the concat note;
then add only `point_query`.) `PointQuery` comes from
`outage_harness_<pkg>.point_coverage`; add it to that import line.

Then, as the first statement of the body, before the `isinstance(state_path, Path)` check:

```python
    if point_query is None:
        raise ValueError("point_query is required: build it with make_point_query")
```

**E2. Pass it to the graph and record the condition.** In the same function,
find

```python
    _write_json(output_dir / "task.json", task)
    graph = build_investigation_graph(
        model, client,
```

and change the two statements to

```python
    _write_json(output_dir / "task.json", {**task, "condition": condition})
    graph = build_investigation_graph(
        model, client, point_query=point_query, condition=condition,
```

keeping the rest of the `build_investigation_graph(...)` call as it is. If
the per-point steps already built `point_query` inside this function (the
`make_point_query(query_point_coverage, ...)` lines from step 8 of
`STEP_BY_STEP_2026-10-13.md`), delete those lines: the script builds it now.

If your `build_investigation_graph` has no `condition` parameter (the
rendered package, unless you added the switch there too), drop
`condition=condition` from the call; the script still records the condition
in `task.json`.

**E3. Copy `run_case.py`** from the example folder into the package, next to
`langgraph_runner.py`. Set the one constant at its top:

```python
PACKAGE = "outage_harness_langgraph"      # rendered package
PACKAGE = "outage_harness_codex_state"    # concat package
```

**E4. Match `_model` to your `llm.py`.** The function is

```python
def _model(arguments: argparse.Namespace, name: str) -> Any:
    from llm import OpenAICompatLLM

    api_key = os.environ.get(arguments.api_key_env) if arguments.api_key_env else None
    return OpenAICompatLLM(base_url=arguments.base_url, model=name, api_key=api_key,
                           max_tokens=arguments.max_tokens)
```

Open `debug_live.py`, find the line that constructs `OpenAICompatLLM(...)`,
and make the `return` line use the same keyword names and the same extra
arguments (temperature, timeout, headers, whatever it takes). The values
come from the script's arguments: `arguments.base_url`, `name`,
`arguments.max_tokens`; anything `debug_live.py` hard-codes, hard-code here
the same way.

**E5. Match `_client` to your `client.py`.** The function is

```python
def _client() -> Any:
    return importlib.import_module(f"{PACKAGE}.client").RealToolClient()
```

If `debug_live.py` constructs `RealToolClient(...)` with arguments (a tool
library, a configuration, an MCP endpoint), put the same arguments here.

**Check.** From the directory that contains the package (where
`debug_live.py` runs):

```
python -m outage_harness_langgraph.run_case --help
```

prints the option list. If it fails on an import, the message names the
module: `llm` means E4, `client` means E5, `langgraph_runner` means E1 or E2.

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
