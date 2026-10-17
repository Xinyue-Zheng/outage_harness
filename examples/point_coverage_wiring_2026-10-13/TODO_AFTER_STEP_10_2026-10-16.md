# What to do now, in one list

You have the concat package done through step 10 of
`CONCAT_STEP_BY_STEP_2026-10-14.md`, in the version with the condition switch
(`concat_mode`). Since then the completion check, the report and the KPI
reading changed. This list is everything left, for both packages. Do it in
order; each item names the file and the exact change.

Package names below: `outage_harness_langgraph` (rendered) and
`outage_harness_codex_state` (concat). "Both" means do it in each.

## Check first

`check_package.py` in this folder reads the package files and prints one
line per edit of parts A to E: `OK`, or `MISSING` with the part that fixes
it. Copy it next to the packages and run it from the directory that contains
them:

```
python check_package.py outage_harness_codex_state
python check_package.py outage_harness_langgraph
```

Fix every `MISSING` line, rerun until all pass, then go to part F.

## A. Copy the changed modules (both)

The modules live in the `harness/` folder of each example directory
(`examples/point_coverage_wiring_2026-10-13/harness/` for the rendered
package, `examples/concat_baseline_2026-10-14/harness/` for the concat
package). Their in-package imports are relative (`from .point_coverage import
...`), so they work under any package name: copy, do not edit imports.

Copy from `harness/` into the package, replacing what is there:

| file | copy as | why it changed |
|---|---|---|
| `point_coverage.py` | same name | per-area counts `down_cell_covered`, `_with_backup`, `_without_backup` at -110 dBm; per-cell `covered` |
| `completion_point.py` | same name | the direction-bin completion check, the report content, the new `finish_check` |
| `report.py` | same name | replaces the old report tool; same `final_step_report(run_dir, case_state_path)` signature |
| `runner_point_nodes.py` | same name | relative imports |
| `context_builder_point.py` | `context_builder.py` | new completion text, per-direction lines, reads `kpi_baselines`; reads the skill from the file next to it |
| `investigation_skill.txt` | same name | the skill for this package's condition (point version in the rendered folder, concat version in the concat folder) |
| concat package only: `context_builder_concat.py`, `runner_concat_nodes.py`, `transcript.py` | same names | relative imports |

If you already copied earlier versions and see `No module named
'completion_point'` (or `point_coverage`, `report`, `transcript`), the copy
has bare imports. Either copy again from `harness/`, or change these lines
in the package copies to relative imports:

| file | line | change to |
|---|---|---|
| `report.py` | `from completion_point import completion_evidence_status, final_report` | `from .completion_point import ...` |
| `completion_point.py` | `from point_coverage import COVERAGE_RSRP_DBM, read_geometry` | `from .point_coverage import ...` |
| `completion_point.py`, inside `finish_check` | `from report import build_report` | `from .report import build_report` |
| `context_builder.py`, inside `_completion_state_lines` | `from completion_point import completion_context_lines` | `from .completion_point import ...` |
| `context_builder.py` | `def load_skill()` reading `files("outage_harness_...")` | keep yours; it reads the same `investigation_skill.txt` |
| `runner_point_nodes.py` | `from point_coverage import (` | `from .point_coverage import (` |
| `runner_concat_nodes.py` | `from point_coverage import ...` and `from transcript import ...` | `from .point_coverage import ...`, `from .transcript import ...` |
| `context_builder_concat.py` | `from transcript import Transcript` | `from .transcript import Transcript` |

Your old `report.py` is kept in the example folders as
`report_previous_heatmap.py`.

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

In the model-mode branch of that node, the lines after `checks = ...` must
also write the report; the model's finish is accepted, but the report is
still program-generated from the hidden State. Replace the lines from
`final_state = {**state["state"], "completion_checks": checks}` down to the
`finish_step = {...}` dict with:

```python
        markdown, data = build_report({**state["state"], "completion_checks": checks}, output_dir)
        (output_dir / "final_report.md").write_text(markdown, encoding="utf-8")
        _write_json(output_dir / "final_report.json", data)
        final_state = {**state["state"], "completion_checks": checks, "final_report": "final_report.md"}
        finish_step = {"step": index, "decision": state["decision"], "status": "finished",
                       "completion_checks": checks, "accepted_by": "model", "final_report": "final_report.md"}
```

and add `from outage_harness_codex_state.report import build_report` to the
imports. Step 10 of the concat note shows the whole node with this in place.

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

Goal: one command per package runs a case. Two files are involved:
`langgraph_runner.py` (E1, E2) and `run_case.py` (E3 to E5). Do E1 to E5 in
the concat package, then again in the rendered package.

### E1. Add one import to `langgraph_runner.py`

Find the import line from `point_coverage` (added in the concat note, step
3a, or the per-point note, step 6):

```python
from outage_harness_<pkg>.point_coverage import PointQuery, inspect_point_coverage
```

If `PointQuery` is not in it, add it. If the line does not exist, add it
below the other package imports.

### E2. Replace `run_case_langgraph` in `langgraph_runner.py`

Find `def run_case_langgraph(` (original line 677). Select from that line
to the function's last line, `return _read_json(output_dir / "run.json")`,
and replace the whole function with the one in `run_case_langgraph.py` in
this folder. That file holds the complete function; copy it as is.

Then make the package-specific edits that the comments at the top of that
file name:

- concat package: replace `outage_harness_<pkg>` with
  `outage_harness_codex_state` in the `make_task` import. Nothing else.
- rendered package: replace it with `outage_harness_langgraph`. If this
  package's `build_investigation_graph` has no `condition` parameter (you
  did not add the switch there), delete `condition=condition,` from the
  `build_investigation_graph(...)` call and change
  `verifier=None if condition == "concat" else verifier` to
  `verifier=verifier`.

What the new function changes against yours: two new keywords `condition`
and `point_query`; a guard that raises when `point_query` is missing; the
`make_point_query(...)` line removed, because the script builds the query;
`condition` written into `task.json`; `point_query` and `condition` passed
to the builder; the verifier dropped under concat; `condition` in the
cap-ended `run.json`. Everything else is your code.

### E3. Copy `run_case.py` into the package

Copy `run_case.py` from this folder to the package directory, next to
`langgraph_runner.py`. Open it and set the constant on its line 38:

```python
PACKAGE = "outage_harness_codex_state"    # concat package
PACKAGE = "outage_harness_langgraph"      # rendered package
```

### E4 and E5. `_model` and `_client`: done

`run_case.py` already builds them as `debug_live.py` does:
`OpenAICompatLLM()` with no arguments, and
`RealToolClient(<run directory>/artifacts)`. `--base-url` and `--model` are
accepted and ignored, because `OpenAICompatLLM` reads its own configuration.
The verifier is a second `OpenAICompatLLM()` under the rendered condition
unless `--no-verifier` is given; the concat condition never has one.

### E6. Check

From the directory where `debug_live.py` runs:

```
python -m outage_harness_codex_state.run_case --help
```

prints the option list. An error names what is wrong:

| error mentions | fix in |
|---|---|
| `llm` | `llm.py` is not importable from this directory; run from where `debug_live.py` runs |
| `client` | `RealToolClient` takes something other than the artifacts directory; edit `_client` in `run_case.py` |
| `langgraph_runner`, `PointQuery` | E1 |
| `run_case_langgraph`, `point_query`, `condition` | E2 |
| `No module named outage_harness_...` | E3, the `PACKAGE` constant, or run from the wrong directory |

Repeat with `outage_harness_langgraph` for the rendered package.

## F. Running

From the directory that holds `.venv`, the two packages and `debug_live.py`.

### F1. Activate the environment

| shell | command |
|---|---|
| bash or zsh | `source .venv/bin/activate` |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows cmd | `.venv\Scripts\activate.bat` |

Or skip activation and call the interpreter by path:
`.venv/bin/python` (Linux, macOS) or `.venv\Scripts\python` (Windows) in
place of `python` below.

### F2. The certificate and the point API token

The certificate file must be PEM: its first line is
`-----BEGIN CERTIFICATE-----`. A `.crt` file usually is. Check with
`head -1 <file>`; if the first line is binary, convert once with
`openssl x509 -inform der -in cert.crt -out cert.pem` and use the `.pem`.

Pass it with `--ca-bundle`; the script sets `REQUESTS_CA_BUNDLE` and
`SSL_CERT_FILE` before any client is imported.

The point API token has two sources; the script uses the first that exists:

1. The environment variable `COVERAGE_API_TOKEN` (another name with
   `--token-env`): `export COVERAGE_API_TOKEN=<token>` in bash or zsh,
   `$env:COVERAGE_API_TOKEN = "<token>"` in PowerShell.
2. A default on the `token` parameter of `query_point_coverage` in the
   package's `point_by_point_cover.py`:

   ```python
   TOKEN = "<your token>"

   def query_point_coverage(lat: str, lon: str, r: str, token: str = TOKEN):
   ```

   The token then never appears on a command line. Keep that file out of
   version control.

### F3. The commands

Concat package:

```
python -m outage_harness_codex_state.run_case --condition concat \
    --down-cell <ID> --start-time <YYYY-MM-DDTHH:MM:SSZ> --end-time <YYYY-MM-DDTHH:MM:SSZ> \
    --output runs/case1_concat --max-steps 10 --query-budget 300 \
    --ca-bundle /path/to/certificate.crt
```

Rendered package, same case:

```
python -m outage_harness_langgraph.run_case --condition rendered \
    --down-cell <ID> --start-time <YYYY-MM-DDTHH:MM:SSZ> --end-time <YYYY-MM-DDTHH:MM:SSZ> \
    --output runs/case1_rendered --max-steps 10 --query-budget 300 \
    --ca-bundle /path/to/certificate.crt
```

Options and their defaults: `--max-steps 8`, `--query-budget 1500`
locations, `--time-cap 3600` seconds, `--tool-call-cap 20`,
`--rejection-cap 3`, `--repeat-cap 2`. Explicit outage sectors:
`--outage-cell-ids <id1> <id2>`. The rendered package runs a verifier unless
`--no-verifier` is given; the concat package never does. The output
directory must be new or empty; each run gets its own.

Start with a small `--query-budget` (300) and one case; raise it once a run
ends with `complete`.

### F4. What to look at afterwards

In the output directory:

- `run.json`: `end_reason` (`complete`, or a cap), `steps`, `condition`.
- `final_report.md` and `final_report.json`: only when the run completed.
- `steps/step_NN/LLM_input.txt`: exactly what the model received that round.
- `steps/step_NN/validation.json`: `accepted`, or `rejected` with the
  reason; a refused finish reads "Completion refused" and lists the open
  directions.
- `state_NN.json`: the State after each round; `summaries` has the per-area
  counts, `coverage` the per-location samples.
- `trace.txt`: the whole run in one file.

Keep the whole directory; nothing outside it is written.

## G. Not changed, on purpose

- The completion check counts only `settlement` and `road_corridor` areas.
  Activity areas are not a kind; they stay inside settlements.
- The transfer tool is yours. The report reads its output from
  `state["impact"]["backup_loads"]` (`cell_id`, `baseline_prb_percent`,
  `estimated_prb_percent`); until it runs, those locations are reported as
  "degrade, unknown cause".
- Scoring is not in the runner.
