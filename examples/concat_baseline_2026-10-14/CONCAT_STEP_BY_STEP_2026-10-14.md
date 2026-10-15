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

## 3. Wiring the concat package

Two packages, one per condition. `outage_harness_langgraph` is the rendered
harness and stays as it is (its own fixes are listed in
`FAIR_COMPARISON_2026-10-15.md`). `outage_harness_codex_state` is a full
copy of it, taken after the per-point steps of `STEP_BY_STEP_2026-10-13.md`
were applied, and then changed as below so that it is concat and nothing
else. There is no condition switch: every edit replaces the rendered
behaviour in this copy. Find lines by their text, not by number.

### Step 1. Copy

Copy `transcript.py`, `context_builder_concat.py`, `runner_concat_nodes.py`
and `investigation_skill_concat.txt` into the package. In
`runner_concat_nodes.py` and `context_builder_concat.py` the imports already
name `outage_harness_codex_state`.

### Step 2. The run script

`run_case.py` in this folder is the command line for both packages: copy it
into each package next to `langgraph_runner.py`. It builds the model, the
tool client, the point query and the caps, and calls `run_case_langgraph`.
Two constructors are yours to match: `_model` (your `llm.OpenAICompatLLM`)
and `_client` (your `client.RealToolClient`). The script reads the module
constant `CONDITION` from the package's `langgraph_runner` and writes it into
`task.json` and `run.json`, so a run directory says which package produced
it.

In this package, add at the top of `langgraph_runner.py`, next to the
imports:

```python
CONDITION = "concat"
```

(in the rendered package: `CONDITION = "rendered"`).

`run_case_langgraph` must accept `point_query` as a keyword and pass it to
the builder; step 8 of `STEP_BY_STEP_2026-10-13.md` built it inside. Move
that out:

```python
def run_case_langgraph(model, client, state_path, output_dir, *, max_steps=8,
                       case_evidence=None, fetch_landuse_before_decision=True,
                       verifier=None, limits=None, point_query=None):
    if point_query is None:
        raise ValueError("point_query is required: build it with make_point_query")
```

and in its body pass `point_query=point_query` to `build_investigation_graph`,
and write the condition into the task file:

```python
    _write_json(output_dir / "task.json", {**task, "condition": CONDITION})
```

One run per package, same arguments:

```
export REQUESTS_CA_BUNDLE=/path/to/your/certificate.pem
export SSL_CERT_FILE=/path/to/your/certificate.pem
export COVERAGE_API_TOKEN=...
python -m outage_harness_langgraph.run_case \
    --down-cell CCL06069 --start-time 2026-02-10T09:00:00Z --end-time 2026-02-10T12:00:00Z \
    --output runs/case1_rendered --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b \
    --verifier-model qwen2.5-32b
python -m outage_harness_codex_state.run_case \
    --down-cell CCL06069 --start-time 2026-02-10T09:00:00Z --end-time 2026-02-10T12:00:00Z \
    --output runs/case1_concat --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b
```

`--ca-bundle /path/to/certificate.pem` sets both variables from inside the
script instead of the two exports. `--fake-point-api` drives the real model
against the synthetic point API before any real API call; the token is then
not needed.

### Step 3. `initialize_node`

**3a. Imports**, at the top of the file. Find

```python
from outage_harness_codex_state.context_builder import build_context, load_skill
```

and replace it with

```python
from outage_harness_codex_state import context_builder_concat as concat
from outage_harness_codex_state import runner_concat_nodes as rc
from outage_harness_codex_state.transcript import Transcript
```

Make sure the import from `runner_point_nodes` includes `AREA_RESOLUTIONS`
and `new_locations`:

```python
from outage_harness_codex_state.runner_point_nodes import (
    AREA_RESOLUTIONS, QUERY_AREA_COVERAGE, execute_query_area_coverage, make_point_query,
    new_locations, update_state_query_area_coverage,
)
```

**3b. The graph state.** In `InvestigationState`, after

```python
    system_prompt: str
```

add

```python
    transcript: Transcript
```

**3c. The context the node builds.** Inside `initialize_node`, find the
three consecutive lines

```python
        rendered = build_context(case_state, tools)
        (output_dir / "investigation_skill.txt").write_text(load_skill(), encoding="utf-8")
        (output_dir / "system_prefix.txt").write_text(rendered.prefix, encoding="utf-8")
```

and replace them with

```python
        transcript = concat.new_transcript(case_state, tools)
        (output_dir / "investigation_skill.txt").write_text(concat.load_skill(), encoding="utf-8")
        (output_dir / "system_prefix.txt").write_text(transcript.system, encoding="utf-8")
```

**3d. The node's return value.** In the returned dict, replace

```python
            "system_prompt": rendered.prefix,
```

with

```python
            "system_prompt": transcript.system,
            "transcript": transcript,
```

### Step 4. `render_context_node`

Find the first two lines of the body

```python
        rendered = build_context(state["state"], state["tools"])
        context = rendered.variable
```

and replace them with

```python
        context = concat.build_context(state["transcript"]).variable
```

Everything after them stays. `context` is the whole transcript flattened to
one user string, so `LLM_input.txt` shows what the model receives. If your
LLM client takes a messages list, build it as
`state["transcript"].as_messages()` in the same node and send that from
`llm_call_node`; the content is the same, the turns stay separate.

### Step 5. `validate_node`

Replace the whole function with:

```python
    def validate_node(state: InvestigationState) -> dict[str, Any]:
        step_dir = Path(state["output_dir"]) / "steps" / f"step_{state['step_index']:02d}"
        try:
            # Codex way: tool name known, parameters as declared, area id listed. Nothing about State.
            action_name, arguments = rc.validate_schema_only(
                state["decision"], state["tools"], state["state"], state["output_dir"], AREA_RESOLUTIONS)
            if action_name == "query_area_coverage":
                cost = new_locations(state["state"], arguments["area_id"], state["output_dir"])
                if guard.check_locations(cost):
                    # The budget is a cap that ends the run, not feedback the model can act on.
                    return {"end_reason": "query_budget", "error": "query_budget"}
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

Gone on purpose: `validate_live_action`, `check_gap`, the budget message
with the cost, `inspect_coverage` and `validate_query_area_coverage`. A
rejected decision reaches the model as an error string appended to the
transcript (step 9). The KPI routing by id pattern still happens in
`parse_node`, because it belongs to the tool library.

### Step 6. `verifier_node`

Delete the node and its edges. Find

```python
    graph.add_node("verifier", verifier_node)
```

and delete it; find

```python
    graph.add_edge("validate", "verifier")
    graph.add_conditional_edges(
        "verifier",
        route_after_validation,
```

and replace the two lines with

```python
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
```

Delete the `def verifier_node` function. In `build_investigation_graph`,
the `verifier` parameter stays in the signature and is ignored.

### Step 7. `execute_tool_node`

No change. The per-point version from `STEP_BY_STEP_2026-10-13.md`, step 7,
runs the same tools in both packages.

### Step 8. `update_state_node`

The per-point version from `STEP_BY_STEP_2026-10-13.md`, step 7, with one
addition. Find

```python
        new_state["id"] = f"state_{index:02d}"
```

and add directly below it

```python
        # The model's own reply, then the raw tool output, appended in order. Nothing from new_state.
        rc.append_round(state["transcript"], json.dumps(state["raw_response"]), state["action_name"],
                        summary, None, state["output_dir"])
```

The State keeps being updated by the same code as in the rendered package;
here it is hidden from the model and kept for the comparison.

### Step 9. `record_error_node`

Find

```python
        reason = state.get("error") or "Unknown decision error"
```

and add directly below it

```python
        # The rejection reaches the model as a tool error appended to the transcript.
        function = (state.get("decision", {}).get("action") or {}).get("function")
        rc.append_round(state["transcript"], json.dumps(state.get("raw_response", {})),
                        function, None, reason, state["output_dir"])
```

### Step 10. `finish_check_node`

Add one module-level constant next to the imports:

```python
COMPLETION_MODE = rc.COMPLETION_MODE_MODEL   # "model": finish accepted as proposed; "checks": refused until the checks pass
```

Replace the whole function with:

```python
    def finish_check_node(state: InvestigationState) -> dict[str, Any]:
        if COMPLETION_MODE == rc.COMPLETION_MODE_CHECKS:
            # The concat+checks condition: the same completion rule as the rendered package.
            return finish_check(state, client, radio_technology, write_json=_write_json,
                                model_name=getattr(model, "model", type(model).__name__))
        checks = completion_evidence_status(state["state"], radio_technology)   # recorded, not enforced
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
            "condition": CONDITION, "steps": len(steps), "finished": True, "end_reason": "model_finish",
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

The completion rule in `completion_point.py` is provisional and is the same
file in both packages, so whatever rule is settled later replaces one file
in each. In `write_cap_node`, add `"condition": CONDITION` to the `summary`
dict so every `run.json` carries it.

Scoring is not part of the runner. What a run is judged by is still to be
agreed; when it is, it is a separate script over the run directories, which
hold `run.json`, every `state_NN.json`, and every step's model input and
output in both packages.

## 4. The test

[The metrics below are proposals. What a run is judged by is to be agreed
before any of them is implemented; none is computed by the runner.]

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
4. Whether the completion checks pass at the end (computed and written in
   every condition, enforced only in rendered and concat+checks).
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
