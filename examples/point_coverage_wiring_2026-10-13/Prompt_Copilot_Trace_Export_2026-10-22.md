# Prompt for the Copilot: export a run as trace data for the Loop Trace Explorer

The page `Loop_Trace_Explorer_2026-10-22.html` shows a run the way LangSmith
shows a trace: the loop graph with every node, the nodes that ran in a step
lit in order, a tree of steps and node spans with durations on the left,
and an inspector on the right with the input and output of the selected
node. It reads one JavaScript object, `RUN_DATA`. Write the script that
produces that object from run directories, and nothing else: the page does
not change.

## 1. What to write

`export_trace.py <RUN_DIR> [<RUN_DIR_2> ...] --out trace_data.js` writes

```js
const RUN_DATA = { ... };
```

with the exact shape of the placeholder object at the top of the page's
script (`placeholder: false`). Then replace the placeholder object in a copy
of the page with the file's content, or load the file with a `<script
src="trace_data.js">` tag placed before the page's script and delete the
placeholder object. One `conditions[]` entry per run directory; its `id`
and `label` come from `run.json`'s `condition` (`rendered`, `concat`,
`concat_checked`).

## 2. The shape

```
RUN_DATA = {
  placeholder: false,
  case: { site, outage_window, model },                       // from task.json and run.json
  conditions: [ { id, label, steps: [ STEP, ... ] }, ... ]
}
STEP = { step: <int>, title: <string>, kind: "init" | "q" | "x" | "k" | "r" | "e", spans: [ SPAN, ... ] }
SPAN = { node, duration_s, status: "ok" | "warn" | "bad", summary, input, output }
```

`node` is one of: `render_context`, `llm_call`, `parse`, `validate`,
`verifier`, `execute_tool`, `update_state`, `record_error`, `finish_check`,
`end`. The spans of a step are listed in the order the nodes ran.

## 3. Where each span comes from

Step 0 (`steps/step_00/`):
- `execute_tool`: summary from the two initialisation observations
  (`initialization_observations.json`: function names, row counts, OSM
  element count); input the parameters; output the result summaries.
  `duration_s` from `step.json`'s `started_at` and `ended_at`.
- `update_state`: summary "State 0: N areas, M active locations"; output
  the area ids with names and the relations.

Every later step `steps/step_NN/`, one span per node that ran:
- `render_context`: summary `"<n> chars"` plus the first open item of the
  progress block; input the user message from `llm_input.json` (the whole
  text, the page scrolls it); output `"Rendered(prefix <p> chars, variable <v> chars)"`
  for rendered, or the message count for a transcript. Duration from
  `timing.json` to the LLM call if recorded, else 0.1.
- `llm_call`: summary the action name and its parameters in one line; input
  `"system + user messages"`; output the raw reply from `llm_response.json`.
  Duration from the model client's timing if recorded in `llm_response.json`
  or `timing.json`; else the round duration minus the tool duration.
- `parse`: summary from `decision.json` (action, parameter count, routing
  if any); output the normalised decision as JSON.
- `validate`: from `validation.json`; status `ok` when accepted, `bad` when
  rejected; summary the message; output the file's content.
- `verifier` (rendered only, when `verifier_output.json` exists): status
  `ok` for agree, `warn` for concern; output the two lines.
- `execute_tool`: from `tool_result.json`; summary one line (locations
  fetched, rows, areas added, or the error); input the resolved parameters
  (`resolved_parameters.json` when present); output the result summary;
  `duration_s` from the tool result's `duration_s`.
- `update_state`: summary the change (area queried and its counts, areas
  added, baselines added); output the completion check after the step from
  `completion_checks.json`, rendered as its `progress_lines` text when the
  helper is importable, else as JSON.
- `record_error` (rejected steps): status `bad`; summary and output the
  error from `error.json`.
- `finish_check` (steps whose action was finish): status `bad` when refused
  (output the refusal), `ok` when accepted after a passed check, `warn`
  when accepted as proposed (plain concat); output the checks.
- `end` (the last step of the run): summary the end reason and what was
  written (`final_report.md`, `run_log.md`, `redistribution.json`); output
  the backup loads and the class totals from `final_report.json`.

`kind` per step: `init` for step 0; `q` for a coverage or inspection
query; `x` for an expansion; `k` for a KPI query; `r` for a rejected or
refused step; `e` for the step that ended the run. `title` is the action in
three words ("query S01", "expand east", "KPI backups", "finish refused",
"program stop", "model finish").

## 4. Rules

- Every string comes from the files; where a file is absent, the span's
  `input` or `output` is `"not recorded"`, never an invented value.
- Do not shorten the raw reply or the context text; the inspector scrolls.
- Escape the texts for a JavaScript string (use `json.dumps` on the whole
  object and write `const RUN_DATA = ` + that).
- Deterministic: running twice gives the same file.
- Write a `README.md` next to the output with the command and the run
  directories read.

## 5. Check

Open the page with the exported data: the tab list shows one tab per run;
step 0 lights `execute_tool` and `update_state`; a rejected step lights the
path to `record_error` in red; the last step lights `end` in green; clicking
`llm_call` at any step shows the raw reply; the durations in the tree sum to
the round durations in `run_log.md`.
