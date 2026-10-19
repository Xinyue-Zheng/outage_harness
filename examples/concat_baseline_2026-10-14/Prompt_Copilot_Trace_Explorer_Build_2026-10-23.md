# Prompt for the Copilot: build the Loop Trace Explorer with the real traces

You have two inputs: the page `Loop_Trace_Explorer_2026-10-22.html` (in the
repository's example folders) and the run directories of the completed
runs. Produce one self-contained HTML file that shows those runs in the
page, side by side, with every word and number taken from the run files.
The page's layout, graph, controls and styles do not change; you replace
one JavaScript object and add the per-design graph notes.

Run directories:

```
RENDERED_RUN = <path to the rendered run directory>
CONCAT_RUN   = <path to the concat run directory>
CHECKED_RUN  = <path to the concat_checked run directory, or empty>
```

## 1. What to deliver

In `<OUT_DIR>`:

- `export_trace.py`: the script, run as
  `python export_trace.py <RENDERED_RUN> <CONCAT_RUN> [<CHECKED_RUN>] --page Loop_Trace_Explorer_2026-10-22.html --out <OUT_DIR>`.
- `trace_data.js`: `const RUN_DATA = {...};`, the exported object.
- `index.html`: the page with the placeholder `RUN_DATA` object replaced by
  the exported one (the script does this replacement by locating the text
  between `const RUN_DATA = {` and the line `// Program bookkeeping nodes`
  and substituting it). `placeholder` is `false`, so the yellow banner
  disappears.
- `README.md`: the command, the run directories read, the step and span
  counts per condition, and anything that was "not recorded".

The page already supports several conditions as tabs and side by side; the
checkbox "both designs side by side" is in the control bar. Set it on by
default for the talk: in `index.html`, change `<input type="checkbox" id="side">`
to `<input type="checkbox" id="side" checked>` and the line
`let cond = 0, step = 0, playing = false, timer = null, side = false;` to
`side = true`.

## 2. The shape of `RUN_DATA`

```
RUN_DATA = {
  placeholder: false,
  case: { site, outage_window, model },
  conditions: [ CONDITION, ... ]          // one per run directory, in the order given
}
CONDITION = { id, label, desc, graph: { subs: {node: text}, absent: [node, ...] }, steps: [ STEP, ... ] }
STEP = { step: <int>, title: <string>, kind: "init" | "q" | "x" | "k" | "r" | "e", spans: [ SPAN, ... ] }
SPAN = { node, duration_s: <number>, status: "ok" | "warn" | "bad", summary, input, output }
```

`case`: `site` and `outage_window` from `task.json` (`down_cell_id`;
`start_time` to `end_time`), `model` from `run.json`.

`id` is `run.json`'s `condition`. `label` and `desc`:

| id | label | desc |
|---|---|---|
| rendered | Rendered State | context rendered from State; program checks gate the finish |
| concat | Codex-style concat | transcript of replies and raw tool output; the model decides the end |
| concat_checked | Concat with program completion | transcript input; program checks gate the finish |

`graph` is fixed per id and is not read from files:

```
rendered:        { subs: {}, absent: [] }
concat:          { subs: { render_context: "transcript append", validate_action: "schema only",
                           completion_checks: "recorded, not enforced", update_state: "hidden State",
                           loop_guards: "caps only" },
                   absent: ["verifier", "end_program_stop"] }
concat_checked:  { subs: { render_context: "transcript append", validate_action: "schema only",
                           update_state: "hidden State" },
                   absent: ["verifier"] }
```

## 3. Steps and spans

Node names are the overview's: `initialize` (step 0 only),
`render_context`, `llm_call`, `parse`, `validate_action`, `verifier`,
`execute_query`, `update_state`, `write_step`, `loop_guards`,
`record_error_obs`, `completion_checks`, and the ends `end_cap`,
`end_retry`, `end_program_stop`, `end_complete`. Spans are in the order the
nodes ran.

### Step 0, from `steps/step_00/`

- `initialize`: summary "query_basic_information, query_osm_landuse (30 km
  square)" or, for a run started with `--reuse-osm`, "query_basic_information;
  OSM payload reused from <source run>" (the initialisation observation's
  `source` field says which). Input: the two actions' parameters. Output:
  the metadata row count and the OSM element count. `duration_s` from
  `step.json`'s `started_at` and `ended_at`.
- `update_state`: summary "State 0: N areas, M active locations, frame
  600 x 600" from `state_00.json` (`geography.areas`, `study_area`,
  `grid`). Output: one line per area, `id (name, kind): grid_count locations`,
  then the relations.
- `write_step` 0.05 s and `loop_guards` 0.01 s with the summaries "Step 0
  record" and "caps not hit".

### Every later step, from `steps/step_NN/`

For every file named below, when it is absent the span's `input` or
`output` is the string `not recorded`; a span whose node did not run is not
emitted.

- `render_context`: input the user message from `llm_input.json`, whole;
  output `Rendered(prefix P chars, variable V chars)` for rendered, or
  `transcript: M messages, N chars` for a transcript (count the messages in
  `llm_input.json`). Summary `"<N> chars"` plus, for rendered, the first
  line after "Completion progress" in the user message. `duration_s`: from
  `timing.json` `started_at` to the model call start if recorded, else 0.1.
- `llm_call`: input `system + user messages (see render_context)`; output
  the raw reply from `llm_response.json` as text, whole. Summary: the
  action name and its parameters in one line from `decision.json`.
  `duration_s`: the model client's duration when `llm_response.json` or
  `timing.json` records one; else the round duration (`timing.json`
  `started_at` to `step.json` `ended_at`) minus the tool duration, and the
  README notes that this is derived.
- `parse`: summary from `decision.json`: action, number of parameters,
  `routing` when present; output the normalised decision as pretty JSON.
  0.01 s.
- `validate_action`: from `validation.json`: status `ok` when `accepted`,
  `bad` when `rejected`; summary the message or "accepted: <arguments>";
  output the file as pretty JSON. 0.02 s.
- `verifier`: only when `verifier_output.json` exists: status `ok` for
  `agree`, `warn` for `concern`; summary `agree` or `concern: <reason>`;
  input `context + decision`; output the two lines. `duration_s` from the
  file or `timing.json` when recorded, else 0.
- `execute_query`: from `tool_result.json`: summary one line, by action:
  coverage "N point calls; V with samples, M missing" from `details`;
  expansion "OSM for the wedge box; C cells; K areas added" from the
  `expand_NN.json` artifact; KPI "R rows"; inspection "R rows"; an error
  "failed: <error>" with status `bad`. Input: `resolved_parameters.json`
  when present, else the decision's parameters. Output: the result
  summary as pretty JSON. `duration_s` from the result's `duration_s`.
- `update_state`: summary the change: for coverage "<area> queried
  Q/T; outage sector covers C; with backup B" from `state_after.json`'s
  `summaries[area]`; for expansion "geography_vN.json; <areas> added"; for
  KPI "kpi_baselines: K cells". Output: the completion progress after the
  step, as the text of `progress_lines(completion_checks.json)` (import it
  from the package; if the import fails, the pretty JSON of
  `completion_checks.json`). `duration_s` from `timing.json` when recorded,
  else 0.3.
- `write_step` 0.05 s, summary "Step record: decision, validation,
  observation, State after", output the step directory path.
- `loop_guards` 0.01 s, summary "caps not hit: next round", or on the
  program-stop step "every check passes at round >= 5: program stop".
- `record_error_obs` (steps with `error.json`): status `bad`; summary and
  output the error text.
- `completion_checks` (steps whose action is `finish`, and the program-stop
  step): status `bad` when refused (output the refusal from `error.json`),
  `ok` when the checks passed, `warn` when the finish was accepted as
  proposed (`finish.json` has `accepted_by: model`); output the checks as
  the `progress_lines` text.
- the end node, on the last step only, chosen by `run.json`'s
  `end_reason`: `end_complete` for `complete` and `model_finish`,
  `end_program_stop` for `complete_program_stop`, `end_retry` for
  `rejection_cap`, `end_cap` for every other value. Summary the end reason
  and the files written; output: the `backup_loads` of `redistribution.json`
  (cell, baseline PRB, estimated PRB, worst hour) and the class totals of
  `final_report.json`. `duration_s` from `timing.json` when recorded, else 0.

Node order within a step follows the runner: `render_context`, `llm_call`,
`parse`, `validate_action`, then `verifier` if present, then either
`record_error_obs` (rejected), or `completion_checks` then
`record_error_obs` (finish refused) or the end node (finish accepted), or
`execute_query`, `update_state`, `write_step`, `loop_guards`, then the end
node if the run ended here.

`kind`: `init` for step 0; `r` when `error.json` exists; `e` for the last
step; `x` for `expand_study_area`; `k` for `query_lte_rrc_prb` or
`query_nr_rrc_prb`; `q` otherwise. `title`: "query <area id> (<name>)",
"expand <direction>", "KPI <n> cells", "inspect <observation>",
"finish refused", "finish accepted", "program stop", "cap: <end_reason>".

## 4. Rules

- Every string comes from the files; `not recorded` where a file is absent;
  nothing invented, nothing shortened.
- The script is deterministic and prints the step and span counts per
  condition when it finishes.
- `json.dumps` the whole object with `ensure_ascii=False` and write
  `const RUN_DATA = ` + that + `;`.
- Do not edit anything in the page other than the `RUN_DATA` object and the
  two side-by-side defaults in section 1.

## 5. Check

Open `index.html`:

1. Two (or three) panels side by side, the yellow banner gone.
2. Step 0 lights `initialize`, `update_state`, `write_step`, `loop_guards`
   in both panels.
3. In the rendered panel, a refused finish lights `completion_checks` red
   and `record_error_obs`; the last step lights its end pill green.
4. In the concat panel, `verifier` is dotted and never lit; the last step
   lights `completion_checks` in yellow and `end_complete`.
5. Clicking `llm_call` at any step shows the raw reply; clicking
   `render_context` shows the whole user message.
6. The durations of a step's spans sum to within one second of that step's
   duration in `run_log.md`; the README lists any step where they do not.
