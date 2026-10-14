# The concatenation baseline: what it is, how to wire it, how to run the test

Purpose: answer "why is the Codex way, appending raw tool output to one
transcript, not sufficient here" with a measurement, not an argument. This
folder is a copy of `../wiring` (the rendered condition, the harness) plus the pieces that
turn it into the concat condition (append-only transcript). Nothing in `../wiring`
changed.

## 1. What the concat condition is, exactly

Codex CLI drives a model like this: a fixed system prompt (instructions plus
AGENTS.md plus the tool list); then, for every turn, the model's reply and the
raw output of the tool it called are appended to the conversation; the whole
conversation is sent again on the next turn; outputs larger than a cap are
truncated head and tail (10 KiB, 256 lines for shell output); the model
decides when it is done.

The concat condition copies that and keeps everything else equal to the rendered condition:

| | rendered (`../wiring`) | concat (this folder) |
|---|---|---|
| system message | skill, task, geography, areas, actions, completion rules | skill (concat version), task, area list, tool declarations as JSON |
| user message | rendered from State every round: counts per area, per-cell lines, unknowns, budget, provenance, feedback | the transcript so far: every reply and every raw tool output, in order |
| tool output shown | never; counts and lines computed by the program | the artifact file as text, truncated at 10 KiB / 256 lines |
| validation | schema, area exists, cost fits budget, gap checks | schema, area exists |
| rejection | feedback line in the next context, with the reason | an error string appended as the tool output |
| finish | refused until the completion checks pass | accepted as proposed (mode `model`); optional mode `checks` |
| verifier | advisory review | none |
| tools, point API, artifacts, caps, State update | same | same (State hidden, used for scoring only) |

Files that implement concat: `transcript.py` (append-only messages, truncation,
raw output formatting), `context_builder_concat.py` (the two messages),
`investigation_skill_concat.txt` (the skill with the sentences that describe
the rendered context removed), `runner_concat_nodes.py` (the node pieces),
`run_demo_concat.py` (both conditions on the synthetic case, scripted
decisions, no model).

## 2. What the demo already shows, before any model call

`python run_demo_concat.py demo_concat` runs the same four scripted decisions
under rendered and concat on the synthetic case and writes the exact model input per round
to `demo_concat/rendered/LLM_input_NN.txt` and `demo_concat/concat/LLM_input_NN.txt`.

| round | action | rendered input (chars) | concat input (chars) | raw output (bytes) | shown after truncation | points in output | points visible to the model |
|---|---|---|---|---|---|---|---|
| 1 | S1 | 10,644 | 12,296 | 32,644 | 4,964 | 30 | 5 |
| 2 | road_H1 | 15,968 | 17,588 | 37,744 | 4,330 | 42 | 7 |
| 3 | S2 | 17,123 | 22,237 | 8,225 | 4,965 | 8 | 6 |
| 4 | finish | 17,270 | 27,529 | | | | |

Two facts follow without running a model:

- **With Codex's truncation the model never sees the data.** One area of 30
  locations is 32 KB of samples; after the 256-line cut the model sees 5 of
  the 30 locations, the head and the tail of the file. Every count the task
  needs (where the outage sectors serve, where a backup is listed) is in the
  middle that was cut.
- **Without truncation the input is the dataset.** 80 locations are 78 KB of
  raw output, about 20,000 tokens. The 400-location synthetic study area
  would be about 390 KB, about 100,000 tokens, in the context on every round.
  The real study areas have 2,400 locations.

The rendered condition's input stays at 17 KB after three areas and grows only by the
lines the new area adds.

So the question the live test answers is not "does concatenation work"; it
is "when the model is given the raw data, in whatever amount fits, how far
does it get, and what does it get wrong, compared with the rendered State".

## 3. Wiring the concat condition into the internal runner

Start from a copy of the internal package after the per-point steps are done
(`../wiring/STEP_BY_STEP_2026-10-13.md`). Then:

### Step 1. Copy

Copy `transcript.py`, `context_builder_concat.py`, `runner_concat_nodes.py`
and `investigation_skill_concat.txt` into the package. Fix the two imports in
`runner_concat_nodes.py` and `context_builder_concat.py` to the package path
(`from outage_harness_codex_state.point_coverage import ...`,
`from outage_harness_codex_state.transcript import ...`).

### Step 2. A condition switch

The condition is one string, `"rendered"` or `"concat"`, chosen when a run starts and
read inside the nodes. It travels through three places in
`langgraph_runner.py`: the builder's signature, the builder's body, and the
entry function. Nodes are closures inside `build_investigation_graph`, so
once the builder has `condition` every node can read it without any change
to `InvestigationState`.

**2a. The builder's signature** (original line 142, `def build_investigation_graph(`):

```python
# old
def build_investigation_graph(
    model: DecisionModel,
    client: Any,
    *,
    point_query: PointQuery,
    fetch_landuse_before_decision: bool = True,
    verifier: DecisionModel | None = None,
    limits: RunLimits | None = None,
):
# new
def build_investigation_graph(
    model: DecisionModel,
    client: Any,
    *,
    point_query: PointQuery,
    condition: str = "rendered",                  # "rendered": context from State; "concat": transcript
    fetch_landuse_before_decision: bool = True,
    verifier: DecisionModel | None = None,
    limits: RunLimits | None = None,
):
```

**2b. The builder's body**, right after `guard = RunGuard(limits or RunLimits())`
(original line 152), before the first node is defined:

```python
    if condition not in ("rendered", "concat"):
        raise ValueError(f"condition must be rendered or concat, got {condition!r}")
    concat_mode = condition == "concat"
```

Every node below tests `if concat_mode:` for its the concat condition branch. Steps 3
to 10 show those branches. The the rendered condition code stays as it is in the `else`
path, so one runner serves both conditions and the comparison is between two
runs of the same file.

**2c. The entry function** `run_case_langgraph` (original line 677): add the
parameter and pass it through.

```python
# old
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
# new
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
    condition: str = "rendered",
) -> dict[str, Any]:
```

and in its body, the call at original line 702:

```python
# old
    graph = build_investigation_graph(
        model, client, point_query=point_query,
        fetch_landuse_before_decision=fetch_landuse_before_decision,
        verifier=verifier, limits=limits,
    )
# new
    graph = build_investigation_graph(
        model, client, point_query=point_query, condition=condition,
        fetch_landuse_before_decision=fetch_landuse_before_decision,
        verifier=None if condition == "concat" else verifier,
        limits=limits,
    )
```

Also write the condition into `task.json` next to the task, so a run
directory says which condition produced it (same line, original 701):

```python
    _write_json(output_dir / "task.json", {**task, "condition": condition})
```

**2d. The run script.** `run_case.py` in this folder is the command line.
Copy it into the package next to `langgraph_runner.py`. It builds the model,
the verifier (rendered only), the tool client, the point query and the caps,
and calls `run_case_langgraph(..., condition=..., point_query=...)`. Two
constructors are yours to match: `_model` (your `llm.OpenAICompatLLM`) and
`_client` (your `client.RealToolClient`); everything else is fixed.

`run_case_langgraph` must accept `point_query` as a keyword and pass it to
the builder (step 8 of `STEP_BY_STEP_2026-10-13.md` built it inside; move
that line out so the script can inject the fake API):

```python
def run_case_langgraph(model, client, state_path, output_dir, *, max_steps=8,
                       case_evidence=None, fetch_landuse_before_decision=True,
                       verifier=None, limits=None, condition="rendered", point_query=None):
    if point_query is None:
        raise ValueError("point_query is required: build it with make_point_query")
```

One run per condition:

```
python -m outage_harness_codex_state.run_case --condition rendered \
    --down-cell CCL06069 --start-time 2026-02-10T09:00:00Z --end-time 2026-02-10T12:00:00Z \
    --output runs/case1_rendered --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b \
    --verifier-model qwen2.5-32b
python -m outage_harness_codex_state.run_case --condition concat \
    --down-cell CCL06069 --start-time 2026-02-10T09:00:00Z --end-time 2026-02-10T12:00:00Z \
    --output runs/case1_concat --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b
```

Add `--fake-point-api` to either command to drive the real model against
the synthetic point API before the first real API call; the token is then
not needed. The real API reads its token from `COVERAGE_API_TOKEN`
(`--token-env` changes the name).

**Check after 2a to 2d.** Run the rendered condition once with `max_steps=1`. Nothing in
its output may differ from a run before step 2, because every the concat condition
branch is behind `concat_mode` and `concat_mode` is false.

### Step 3. `initialize_node`

Four edits, each anchored on a line that exists in `langgraph_runner.py`.
Find the line by its text, not by a number.

**3a. Imports**, at the top of the file. Find

```python
from outage_harness_codex_state.context_builder import build_context, load_skill
```

and add directly below it

```python
from outage_harness_codex_state import context_builder_concat as concat
from outage_harness_codex_state import runner_concat_nodes as rc
from outage_harness_codex_state.transcript import Transcript
```

and make sure the import from `runner_point_nodes` (already there after the
per-point steps) includes `AREA_RESOLUTIONS` and `new_locations`:

```python
from outage_harness_codex_state.runner_point_nodes import (
    AREA_RESOLUTIONS, QUERY_AREA_COVERAGE, execute_query_area_coverage, make_point_query,
    new_locations, update_state_query_area_coverage, validate_query_area_coverage,
)
```

**3b. The graph state.** Find the class `InvestigationState(TypedDict, total=False)`.
Inside it, after the line

```python
    system_prompt: str
```

add

```python
    transcript: Transcript | None
```

**3c. The context the node builds.** Inside `initialize_node`, find these
three consecutive lines (they come right after the `tools = ...` block):

```python
        rendered = build_context(case_state, tools)
        (output_dir / "investigation_skill.txt").write_text(load_skill(), encoding="utf-8")
        (output_dir / "system_prefix.txt").write_text(rendered.prefix, encoding="utf-8")
```

Replace them with

```python
        if concat_mode:
            transcript = concat.new_transcript(case_state, tools)
            system_prompt = transcript.system
            (output_dir / "investigation_skill.txt").write_text(concat.load_skill(), encoding="utf-8")
        else:
            transcript = None
            system_prompt = build_context(case_state, tools).prefix
            (output_dir / "investigation_skill.txt").write_text(load_skill(), encoding="utf-8")
        (output_dir / "system_prefix.txt").write_text(system_prompt, encoding="utf-8")
```

The skill file written into the run is now the one the condition uses, so
the `skill_sha256` that `render_context_node` records stays correct.

**3d. The node's return value.** At the end of `initialize_node`, find

```python
            "system_prompt": rendered.prefix,
```

in the returned dict and replace it with

```python
            "system_prompt": system_prompt,
            "transcript": transcript,
```

Nothing else in `initialize_node` changes: State 0, `geography.json`,
`state_00.json`, `tool_declarations.json` and `query_budget` are written the
same way in both conditions.

### Step 4. `render_context_node`

One edit. Inside `render_context_node`, find the first two lines of the body:

```python
        rendered = build_context(state["state"], state["tools"])
        context = rendered.variable
```

Replace them with

```python
        if concat_mode:
            transcript = state["transcript"]
            if transcript is None:
                raise ValueError("concat condition without a transcript")
            context = concat.build_context(transcript).variable
        else:
            context = build_context(state["state"], state["tools"]).variable
```

Everything after these two lines stays: `full_context`, `context_NN.txt`,
`steps/step_NN/context.txt`, `messages`, `llm_input.json`, `LLM_input.txt`
and `state_before.json` are written from `state["system_prompt"]` and
`context` exactly as before. In the concat condition `context` is the whole
transcript flattened to one user string, so `LLM_input.txt` shows what the
model receives.

If your LLM client takes a messages list rather than (system, user), build
the list from the transcript instead of the two strings, in the same node:

```python
        messages = (state["transcript"].as_messages() if concat_mode else
                    [{"role": "system", "content": state["system_prompt"]},
                     {"role": "user", "content": context}])
```

and send `messages` in `llm_call_node`. The content is the same; the turns
are kept separate.

### Step 5. `validate_node`

Replace the whole function with the one below. It is the complete node, no
part left out: the rendered branch is the per-point version from
`STEP_BY_STEP_2026-10-13.md`, step 7, unchanged; the concat branch is new.
`new_locations` and `AREA_RESOLUTIONS` come from `runner_point_nodes` (import
in 3a); `rc` is `runner_concat_nodes`.

```python
    def validate_node(state: InvestigationState) -> dict[str, Any]:
        step_dir = Path(state["output_dir"]) / "steps" / f"step_{state['step_index']:02d}"
        try:
            if concat_mode:
                # Codex way: tool name known, parameters as declared, area id listed. Nothing about State.
                action_name, arguments = rc.validate_schema_only(
                    state["decision"], state["tools"], state["state"], state["output_dir"], AREA_RESOLUTIONS)
                if action_name == "query_area_coverage":
                    cost = new_locations(state["state"], arguments["area_id"], state["output_dir"])
                    if guard.check_locations(cost):
                        # The budget is a cap that ends the run, not feedback the model can act on.
                        return {"end_reason": "query_budget", "error": "query_budget"}
            else:
                action_name, arguments = _validate_decision(state["decision"])
                if action_name == "query_area_coverage":
                    validate_query_area_coverage(arguments, state["state"], state["output_dir"], guard)
                elif action_name == "inspect_observation":
                    if (not all(isinstance(arguments[key], int) and not isinstance(arguments[key], bool)
                                for key in ("offset", "limit"))
                            or arguments["offset"] < 0 or not 1 <= arguments["limit"] <= 100):
                        raise ValueError("Inspection needs offset >= 0 and limit between 1 and 100")
                    inspect_point_coverage(state["state"], arguments["observation_id"], arguments["area_id"],
                                           arguments["offset"], arguments["limit"])
                elif action_name not in {"finish", "query_area_coverage", "inspect_observation"}:
                    routing = state["decision"].get("routing")
                    if routing and len(routing["calls"]) > 1:
                        for call in routing["calls"]:
                            validate_live_action(call["function"], {**arguments, "cell_ids": call["cell_ids"]},
                                                 state["state"], state["output_dir"])
                    else:
                        validate_live_action(action_name, arguments, state["state"], state["output_dir"])
                if fetch_landuse_before_decision:
                    check_gap(state["decision"], action_name, arguments, state["state"])
            cap = guard.check(action_name, arguments)
            if cap:
                return {"end_reason": cap, "error": cap}
            guard.record_validation(True)
            _write_json(step_dir / "validation.json",
                        {"status": "accepted", "action_name": action_name, "arguments": arguments})
            return {"action_name": action_name, "arguments": arguments, "error": None}
        except Exception as error:
            guard.record_validation(False)
            message = f"{type(error).__name__}: {error}"
            _write_json(step_dir / "validation.json", {"status": "rejected", "error": message})
            return {"error": message}
```

What the concat branch does not do, on purpose: no `validate_live_action`
(the KPI window and cell-id checks against State), no `check_gap`, no budget
message with the cost. A rejected decision reaches the model as an error
string appended to the transcript (step 9), which is how Codex returns a tool
error. The KPI routing by id pattern still happens in `parse_node`, because it
belongs to the tool library, not to the context.

### Step 6. `verifier_node`

Find the first line of the body:

```python
        if verifier is None or state.get("error"):
```

Replace it with

```python
        if verifier is None or state.get("error") or concat_mode:
```

Step 2c already passes `verifier=None` under concat; this line is the second
guard, so a verifier handed in by mistake still never runs.

### Step 7. `execute_tool_node`

Replace the whole function with the one below. The inspection branch and
the coverage branch are the per-point versions; the concat condition runs the
same code, because the tools do not change. The KPI routing part after them
is the original, unchanged. `POINT_WORKERS` comes from `runner_point_nodes`.

```python
    def execute_tool_node(state: InvestigationState) -> dict[str, Any]:
        guard.record_tool_call(state["action_name"], state["arguments"])
        step_dir = Path(state["output_dir"]) / "steps" / f"step_{state['step_index']:02d}"
        if state["action_name"] == "inspect_observation":
            arguments = state["arguments"]
            rows = inspect_point_coverage(state["state"], arguments["observation_id"], arguments["area_id"],
                                          arguments["offset"], arguments["limit"])
            path = Path(state["output_dir"]) / "artifacts" / f"inspection_{state['step_index']:02d}.json"
            _write_json(path, rows)
            result = ToolSuccess("inspect_observation", str(path), len(rows), ("grid_id", "status", "cells"),
                                 source="state", details={"rows": rows})
            _write_json(step_dir / "tool_result.json", _summarize(result))
            return {"tool_result": result}
        if state["action_name"] == "query_area_coverage":
            summary = execute_query_area_coverage(state["state"], state["arguments"], state["output_dir"],
                                                  state["step_index"], point_query, guard)
            if summary["status"] == "success":
                result = ToolSuccess(summary["tool"], summary["output_file"], summary["row_count"],
                                     tuple(summary["columns"]), source=summary["source"], details=summary["details"])
            else:
                result = ToolFailure(summary["tool"], "PointApiFailure", summary["error"])
            return {"tool_result": result}
        routing = state["decision"].get("routing")
        if routing and len(routing["calls"]) > 1:
            successes, calls = [], []
            for call in routing["calls"]:
                suffix = "nr" if call["function"] == "query_nr_rrc_prb" else "lte"
                result = client.call(call["function"], {**state["arguments"], "cell_ids": call["cell_ids"]},
                                     call_id=f"step_{state['step_index']:02d}_{suffix}")
                calls.append({**call, **_summarize(result)})
                if isinstance(result, ToolSuccess):
                    successes.append(result)
            if successes:
                path = Path(state["output_dir"]) / "artifacts" / f"query_kpi_routed_step_{state['step_index']:02d}.csv"
                row_count, columns = _merge_kpi_csvs(successes, path)
                result = ToolSuccess(state["action_name"], str(path), row_count, columns,
                                     source="routed_kpi", details={"routed_calls": calls})
            else:
                result = ToolFailure(state["action_name"], "RoutedKpiFailure", "; ".join(
                    f"{call['function']}: {call.get('error', 'no result')}" for call in calls))
            _write_json(step_dir / "tool_result.json", {**_summarize(result), "routed_calls": calls})
            return {"tool_result": result}
        result = client.call(state["action_name"], state["arguments"], call_id=f"step_{state['step_index']:02d}")
        _write_json(step_dir / "tool_result.json", _summarize(result))
        return {"tool_result": result}
```

`execute_query_area_coverage` already calls `guard.record_locations`, writes
`resolved_parameters.json` and `tool_result.json`.

### Step 8. `update_state_node`

Replace the whole function with the one below. Two things differ from the
per-point version: the coverage branch keeps the State in both conditions
(under concat it is hidden, used for scoring), and the last statement before
the files are written appends the round to the transcript under concat.

```python
    def update_state_node(state: InvestigationState) -> dict[str, Any]:
        index = state["step_index"]
        summary = _summarize(state["tool_result"])
        decision = state["decision"]
        action = decision["action"]
        executed_parameters = action["parameters"]
        if state["action_name"] == "query_area_coverage":
            executed_parameters = json.loads((Path(state["output_dir"]) / "steps" / f"step_{index:02d}"
                                              / "resolved_parameters.json").read_text(encoding="utf-8"))
            action = {**action, "parameters": executed_parameters,
                      "requested_area_id": decision["action"]["parameters"]["area_id"]}
        observation = {
            "id": f"real_obs_{index:02d}",
            "purpose": decision.get("purpose"),
            "information_gaps": decision.get("information_gaps"),
            "action": action,
            "result": summary,
        }
        new_state = _update_state(state["state"], observation)
        if isinstance(new_state.get("observations"), list):
            new_state["observations"] = [*new_state["observations"], observation]
        if state["action_name"] == "query_area_coverage" and summary["status"] == "success":
            new_state = update_state_query_area_coverage(new_state, observation, state["output_dir"], guard)
        if (state["action_name"] in {"query_nr_rrc_prb", "query_lte_rrc_prb"} and summary["status"] == "success"
                and isinstance(state["state"].get("geography"), dict)):
            new_state = apply_kpi(state["state"], observation, state["output_dir"])
        if state["action_name"] == "inspect_observation" and summary["status"] == "success":
            new_state["inspection"] = {"step_index": index, **state["arguments"], "rows": summary["details"]["rows"]}
        if decision.get("routing"):
            routes = "; ".join(f"{call['function']}: {','.join(call['cell_ids'])}" for call in decision["routing"]["calls"])
            new_state["notes"] = [*new_state.get("notes", []), {
                "kind": "rerouted", "step_index": index,
                "text": f"{decision['routing']['requested_function']} cells were routed by ID pattern: {routes}"}]
        new_state["id"] = f"state_{index:02d}"
        if concat_mode:
            # The model's own reply, then the raw tool output, appended in order. Nothing from new_state.
            rc.append_round(state["transcript"], json.dumps(state["raw_response"]), state["action_name"],
                            summary, None, state["output_dir"])
        output_dir = Path(state["output_dir"])
        _write_json(output_dir / f"observation_{index:02d}.json", observation)
        step_dir = output_dir / "steps" / f"step_{index:02d}"
        _write_json(step_dir / "observation.json", observation)
        _write_json(step_dir / "tool_result.json", summary)
        _write_json(step_dir / "state_after.json", new_state)
        _write_json(output_dir / f"state_{index:02d}.json", new_state)
        _write_json(step_dir / "step.json", {"step": index, "decision": decision, "result": summary})
        steps = [*state["steps"], {"step": index, "decision": decision, "result": summary}]
        observations = [*state["observations"], observation]
        _write_json(output_dir / "steps.json", steps)
        _write_json(output_dir / "state.json", new_state)
        return {
            "state": new_state,
            "steps": steps,
            "observations": observations,
            "step_index": index + 1,
            "tool_result": None,
            "error": None,
        }
```

`update_state_query_area_coverage` is the per-point function; it already
applies the coverage artifact, refreshes the summaries and the budget line.
`rc.update_hidden_state` in `runner_concat_nodes.py` does the same for a
runner without the per-point function; here the per-point one is used so
both conditions run identical State code.

### Step 9. `record_error_node`

Find the line

```python
        reason = state.get("error") or "Unknown decision error"
```

and add directly below it

```python
        if concat_mode:
            # The rejection reaches the model as a tool error appended to the transcript.
            function = (state.get("decision", {}).get("action") or {}).get("function")
            rc.append_round(state["transcript"], json.dumps(state.get("raw_response", {})),
                            function, None, reason, state["output_dir"])
```

The rest of the node is unchanged: the note of kind `rejected` still goes
into the hidden State, where it is scored but never rendered under concat.

### Step 10. `finish_check_node`

Add one module-level constant next to the imports:

```python
COMPLETION_MODE = rc.COMPLETION_MODE_MODEL   # "model": finish accepted as proposed; "checks": refused until the checks pass
```

Replace the whole function with the one below. Under the rendered condition,
and under concat with `COMPLETION_MODE == "checks"` (the concat+checks
condition), it is the per-point `finish_check` from `completion_point.py`.
Under concat with mode `model` the finish is accepted as proposed, the checks
are computed and written, but they decide nothing.

```python
    def finish_check_node(state: InvestigationState) -> dict[str, Any]:
        if not concat_mode or COMPLETION_MODE == rc.COMPLETION_MODE_CHECKS:
            return finish_check(state, client, radio_technology, write_json=_write_json,
                                model_name=getattr(model, "model", type(model).__name__))
        checks = completion_evidence_status(state["state"], radio_technology)   # scored, not enforced
        index = state["step_index"]
        output_dir = Path(state["output_dir"])
        final_state = {**state["state"], "completion_checks": checks}
        finish_step = {"step": index, "decision": state["decision"], "status": "finished",
                       "completion_checks": checks, "accepted_by": "model"}
        steps = [*state["steps"], finish_step]
        step_dir = output_dir / "steps" / f"step_{index:02d}"
        _write_json(step_dir / "finish.json", {"status": "finished", "accepted_by": "model", "completion_checks": checks})
        _write_json(step_dir / "state_after.json", final_state)
        _write_json(step_dir / "step.json", finish_step)
        _write_json(output_dir / f"state_{index:02d}.json", final_state)
        _write_json(output_dir / "steps.json", steps)
        _write_json(output_dir / "state.json", final_state)
        _write_json(output_dir / "run.json", {
            "case_state": state["case_state_path"], "model": getattr(model, "model", type(model).__name__),
            "condition": "concat", "steps": len(steps), "finished": True, "end_reason": "model_finish",
            "observations": len(state["observations"]), "tool_declaration_count": len(state["tools"]),
            "orchestrator": "langgraph",
        })
        return {"state": final_state, "steps": steps, "finished": True, "error": None}
```

Imports this needs, next to the ones from step 3a:

```python
from outage_harness_codex_state.completion_point import completion_evidence_status, finish_check
from outage_harness_codex_state.radio import radio_technology
```

### Step 11. Scoring

Every run, both conditions, ends in one of two nodes: `finish_check_node`
(the model proposed finish) or `write_cap_node` (a cap ended the run). Each
writes `score.json` from the hidden State, so the two conditions are scored
by the same code.

In `finish_check_node`, in both return paths above, add before the `return`:

```python
        _write_json(output_dir / "score.json", rc.score_against_state(final_state, checks))
```

(In the `finish_check` path from `completion_point.py` the final State and
the checks are the ones it computed; add the same line inside that function,
before its `return`.)

In `write_cap_node`, find

```python
        _write_json(out / "run.json", summary)
```

and add directly below it

```python
        _write_json(out / "score.json", rc.score_against_state(
            state["state"], completion_evidence_status(state["state"], radio_technology)))
        summary["condition"] = "concat" if concat_mode else "rendered"
        _write_json(out / "run.json", summary)
```

`score.json` holds: locations queried and valid, down-cell locations, how
many of them have a backup and how many have none, the outage cells and the
backup candidates seen, the areas fully queried, and the completion checks.
The comparison between conditions reads these files and `run.json` only.

## 4. The test

**Cases.** The synthetic case here, plus the two or three real cases you can
run internally. Same task input, same tools, same caps, same model and
temperature in every condition. Three runs per case and condition, because
the model is not deterministic.

**Conditions.**

| id | input | validation | finish |
|---|---|---|---|
| rendered | rendered State | full | completion checks |
| concat | transcript, truncated as Codex | schema only | model |
| concat+checks | transcript, truncated as Codex | schema only | completion checks |
| concat-full | transcript, no truncation, until the context window is full | schema only | model |

concat is the Codex way. concat+checks isolates the input from the stopping rule. concat-full
shows whether the problem is the cut or the raw form.

**Metrics, all from the hidden State and the run record.**

1. End reason and rounds to end.
2. Locations queried and the budget spent.
3. Of the down-cell locations in the State, how many the model's final
   report names correctly (where the outage sectors serve), and how many
   backup cells it names that are in `backup_candidates`, and how many it
   names that are not (invented or ineligible).
4. Whether the completion checks pass at the end (scored in every condition,
   enforced only in rendered and concat+checks).
5. Repeated or wasted queries: areas queried twice, areas fully queried
   before the query.
6. Input size per round (chars) and the share of raw output the model saw.

**What result justifies the design.** If concat reaches the same completion rate
and the same correctness as rendered at a comparable budget, rendering is prompt
engineering and the paper has no system contribution. If concat ends by caps or
model finish with wrong or missing facts while rendered completes,
and concat+checks does not
close the gap, then the program-owned State is doing work the transcript
cannot: it is the thing to present. Report both outcomes honestly; the
measurement is the contribution either way.

## 5. What this folder does not contain

- The real LLM client. `complete_json(system, user, schema)` takes the two
  messages; for the messages-list form add one method to your client.
- A run with a model. The demo scripts the decisions to compare the inputs.
- The real cases.
