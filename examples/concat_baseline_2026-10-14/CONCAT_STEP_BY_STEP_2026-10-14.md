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

**2d. The command line.** `main()` is not in the photographed copy. Wherever
it builds the arguments, add one option and pass it:

```python
parser.add_argument("--condition", choices=("rendered", "concat"), default="rendered",
                    help="rendered: context rendered from State (the harness); concat: append-only transcript (the Codex way)")
...
run_case_langgraph(model, client, task, output_dir, max_steps=args.max_steps,
                   verifier=verifier, limits=limits, condition=args.condition)
```

Then one run per condition is:

```
python -m outage_harness_codex_state.langgraph_runner --the rendered condition --output runs/case1_A ...
python -m outage_harness_codex_state.langgraph_runner --the concat condition --output runs/case1_B ...
```

**Check after 2a to 2d.** Run the rendered condition once with `max_steps=1`. Nothing in
its output may differ from a run before step 2, because every the concat condition
branch is behind `concat_mode` and `concat_mode` is false.

### Step 3. `initialize_node`

After the State and tools exist:

```python
transcript = concat.new_transcript(case_state, tools)
(output_dir / "system_prefix.txt").write_text(transcript.system, encoding="utf-8")
return {..., "system_prompt": transcript.system, "transcript": transcript}
```

Add `transcript: Any` to `InvestigationState`.

### Step 4. `render_context_node`

```python
rendered = concat.build_context(state["transcript"])
context = rendered.variable
```

The rest of the node (writing `context_NN.txt`, `LLM_input.txt`,
`llm_input.json`, `state_before.json`) is unchanged: the two messages are
still system plus user. If your LLM client accepts a messages list, send
`state["transcript"].as_messages()` instead of the flattened user string; the
content is the same, split into the original turns.

### Step 5. `validate_node`

Replace the body with:

```python
try:
    action_name, arguments = rc.validate_schema_only(
        state["decision"], state["tools"], state["state"], state["output_dir"], AREA_RESOLUTIONS)
    cap = guard.check(action_name, arguments)
    if cap:
        return {"end_reason": cap, "error": cap}
    if action_name == "query_area_coverage":
        cost = new_locations(state["state"], arguments["area_id"], state["output_dir"])
        if guard.check_locations(cost):
            return {"end_reason": "query_budget", "error": "query_budget"}
    guard.record_validation(True)
    ...write validation.json...
    return {"action_name": action_name, "arguments": arguments, "error": None}
except Exception as error:
    guard.record_validation(False)
    ...write validation.json...
    return {"error": f"{type(error).__name__}: {error}"}
```

No `check_gap`. The budget is a cap that ends the run, not a message with a
cost: Codex has no domain budget, so concat gets the cap and nothing else.

### Step 6. `verifier_node`

`if verifier is None or state.get("error") or concat_mode: return {}`. With 2c passing `verifier=None` for the concat condition this line is a second guard, not the only one.

### Step 7. `execute_tool_node`

```python
summary = rc.execute_concat(state["action_name"], state["arguments"], state["state"],
                            state["output_dir"], state["step_index"], point_query, POINT_WORKERS)
guard.record_locations(summary.get("details", {}).get("fetched", 0))
```

wrap into `ToolSuccess`/`ToolFailure` as in the rendered condition.

### Step 8. `update_state_node`

After the observation dict is built:

```python
new_state = rc.update_hidden_state(state["state"], observation, state["output_dir"], guard)
rc.append_round(state["transcript"], json.dumps(state["raw_response"]), state["action_name"],
                summary, None, state["output_dir"])
```

### Step 9. `record_error_node`

Add one line so the model sees the rejection as a tool error:

```python
rc.append_round(state["transcript"], json.dumps(state.get("raw_response", {})),
                (state.get("decision", {}).get("action") or {}).get("function"), None, reason, state["output_dir"])
```

### Step 10. `finish_check_node`

```python
checks = completion_evidence_status(state["state"], radio_technology)   # scored, not enforced
if concat_mode and COMPLETION_MODE == "model":
    ...write finish.json with checks, run.json with end_reason "model_finish"...
    return {"finished": True}
```

Mode `checks` keeps the the rendered condition behaviour (refuse until the checks pass)
and is the concat condition+ in the experiment.

### Step 11. Scoring

After every run, both conditions, write `score.json` from
`rc.score_against_state(final_state, checks)`. The hidden State is computed
by the same code in both conditions, so the numbers are comparable.

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
