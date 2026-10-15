# Fair comparison: what to change in the rendered package

Two packages, one per condition: `outage_harness_langgraph` (rendered, the
harness you finished, with its known issues) and `outage_harness_codex_state`
(concat, a copy changed as in `CONCAT_STEP_BY_STEP_2026-10-14.md`). For the
comparison to say something about the input format and nothing else, every
part that is not the input format must be the same code in both. This note
lists what the rendered package must change to get there, in order, and what
it must not change.

The principle: the concat package was copied after these changes. If you
make them in the rendered package first and copy again, step 1 of the concat
note is the only copy you need.

## 1. The per-point coverage path (required)

Apply `STEP_BY_STEP_2026-10-13.md` (steps 1 to 9) to the rendered package.
Both packages then share `point_coverage.py`, `runner_point_nodes.py`, the
same tool declaration for `query_area_coverage` (area id and resolution),
the same State update, the same location budget in `RunGuard`, and the same
`execute_tool_node`. The heatmap tool is removed from what the model sees in
both.

Check: a rendered run with `--fake-point-api --max-steps 2` writes
`state_01.json` with `coverage[grid_id]["samples"]` and a context whose
coverage section has the line "Of those N locations, M also list an eligible
backup cell".

## 2. The completion rule (required, provisional)

Copy `completion_point.py` into the rendered package and apply the last
section of `STEP_BY_STEP_2026-10-13.md` ("Completion"): `finish_check_node`
calls `finish_check`; `final_step_report` is removed from the decision schema
enum, from `PARAMETERS`, and from the tool declarations shown to the model;
the "report" line is dropped from the completion text in the context
builder; the report is produced by the program after the checks pass.

This is the same file in both packages. The rule in it is provisional. When
the rule is settled, replace `completion_evidence_status` in that one file
and copy it to the other package; nothing else references the rule's
internals. Until then both packages run the same provisional rule, which is
what the comparison needs: the comparison is between inputs, not between
stopping rules.

Check: the replay test in this folder (`python test_node_sequence.py`)
passes, and a rendered run on the synthetic case can end with
`end_reason: complete` in `run.json`.

## 3. The run script and the certificate (required)

Copy `run_case.py` into the rendered package next to `langgraph_runner.py`,
set `PACKAGE = "outage_harness_langgraph"` at its top, and add
`CONDITION = "rendered"` next to the imports of `langgraph_runner.py`. Make
`run_case_langgraph` take `point_query` as a keyword (concat note, step 2)
and write `{**task, "condition": CONDITION}` to `task.json`. In
`write_cap_node` and the finish path add `"condition": CONDITION` to
`run.json`.

Both packages then run with identical arguments, so the caps (time, tool
calls, rejections, repeats, location budget), the model, the temperature and
the max tokens are the same by construction. One difference is allowed and
is part of the design: `--verifier-model` builds a verifier in the rendered
package; the concat package has no verifier node and ignores it.

The certificate. Your `launch.json` sets it as an environment variable for
the debugger. In a terminal, set the same variable before the command:

```
export REQUESTS_CA_BUNDLE=/path/to/your/certificate.pem
export SSL_CERT_FILE=/path/to/your/certificate.pem
```

or pass `--ca-bundle /path/to/your/certificate.pem` to `run_case.py`, which
sets both before any client is built. Two notes:

- The name in your `launch.json` is spelled `REQUESTS_CA_BULDLE`. The
  variable `requests` reads is `REQUESTS_CA_BUNDLE`. If the misspelling is
  in the file and not only in your message, the debugger run never used the
  certificate; whatever made it work was something else (a system
  certificate store, or a client that does not verify). Check which before
  relying on it.
- `requests` reads `REQUESTS_CA_BUNDLE`. The OpenAI SDK and anything on
  `httpx` or `urllib` read `SSL_CERT_FILE`. The point API uses `requests`;
  the LLM client may use either. Setting both costs nothing.

## 4. The skill text (required)

The rendered package uses `investigation_skill_point.txt` as its
`investigation_skill.txt`; the concat package uses
`investigation_skill_concat.txt`. The second is derived from the first by
removing only the sentences that describe the rendered context (what the
context shows, the budget line, the KPI windows list, the feedback section)
and nothing else. Any later edit to the skill goes into the point version
first, and the concat version is re-derived by the same removals. Keep the
two files side by side in this folder so the diff stays small and readable.

## 5. What must not differ

- Tools and tool declarations shown to the model, except that the concat
  package shows them as JSON in the system message and the rendered package
  as the action lines; the names, parameters and descriptions are the same
  text.
- The task, the study area, the areas derived at initialisation, the grid
  spacing, the point radius choices.
- The State update code, the budget accounting, the caps.
- The completion rule file.
- The model endpoint, name, temperature, max tokens, and the decision JSON
  schema.
- The run directory layout: `task.json`, `run.json`, `state_NN.json`,
  `steps/step_NN/` with the model input and output. The comparison reads
  these only.

## 6. What is not needed for fairness

- The two-file State layout (`examples/state_layout_2026-10-09`). The
  comparison reads the hidden State computed by identical code in both
  packages; how that State is stored does not affect the model's input in
  either condition. Do it for the paper's State description and for run
  size, after the comparison runs.
- Scoring. Removed from the runner. What a run is judged by is to be agreed
  first; then it is one script over the run directories of both packages.
- The gap checks and the verifier. They are design parts of the rendered
  package and stay there; the concat package does not have them by
  definition. Their effect is measured by the ablations, not by this
  comparison.

## 7. Order

1. Section 1 on the rendered package; run with `--fake-point-api`.
2. Section 2; run again; confirm a run can end complete.
3. Section 3 and 4; run both packages with the same command line on the
   fake API, then on the real API with small caps.
4. Then the completion-rule discussion, with the internal report function,
   changing one file in both packages.
