# Outage investigation harness

This package runs the outage investigation system of the design in the UI repository (`Xinyue-Zheng/outage_agentic_system_design`). A decision model proposes one action per round. The program validates it, a verifier model reviews it, the program runs it against the data server, updates a structured State, and renders the next context from that State. The run ends when the completion checks accept a finish, or when a cap is hit.

**Only the data is synthetic.** The four data actions are functions in a tool library that the loop calls by name through one client interface. The two model nodes call a real model through any OpenAI-compatible chat endpoint. The package has no dependencies beyond the standard library; the development tools are Ruff and ty.

Session report with the live-run results: `REPORT_2026-10-06.md`. Example live run: `examples/live_qwen32b_budget1600/`. State 0 built from real OpenStreetMap data for a rural Illinois site: `examples/init_state0_osm/`.

## The loop

```
START -> initialize -> render_context -> llm_call -> parse -> validate_action -> verifier
verifier --query-->  execute_query -> update_state -> write_step -> loop_guards
verifier --finish--> completion_checks --all four pass--> END: complete
parse --does not parse--> record_error_obs      validate_action --invalid--> record_error_obs
record_error_obs --retry cap or rejection cap--> END
record_error_obs, completion_checks (unmet) --> loop_guards
loop_guards --cap hit--> END        loop_guards --next round--> render_context
```

- `llm_call` and `verifier` call a model. Every other node is program code.
- The loop is plain Python: each node is a function of the loop state that returns the fields it replaced; `run_rounds` in `loop.py` runs them in this order and takes the three conditional edges.
- `initialize` makes the two lookups (`cell.lookup`, `osm.geometry`), derives the grid, areas and relations, and writes State 0. The model is not called.
- `record_error_obs` writes a parse failure or rejection into State as a fact, and counts it against the retry cap (3 in a row) or the rejection cap (5).
- `verifier` is advisory. A concern becomes a fact in State and the action still runs. A verifier reply that does not follow its two-line format is recorded in the Step as `not_run`, with the reply; the action still runs.
- `completion_checks` applies four rules: boundary, key areas, labels, backup load. All pass: `END: complete`. Any fails: the unmet rules are written into State. The key-area rule reads the finish gap: its `targets` list the key areas the model leaves unqueried and its `question` gives the reason; the context shows, for every such area, how many of its unqueried locations border a queried location where the down cell is present.
- When the remaining budget cannot cover the cheapest key area that borders the down cell, the boundary rule can no longer be met. A refused finish, or a query refused for budget, then ends the run as `query_budget`. The context announces this one round ahead.
- `loop_guards` checks the repeated area query, the budget-blocked boundary, the step cap, the query budget and the wall time at the end of every round, including rounds that ended in an error or a refused finish.
- Typed end reasons: `complete`, `step_cap`, `query_budget`, `time_cap`, `retry_cap`, `rejection_cap`, `repeated_query`.

## Set up and check

You need `uv`. Python 3.12.12 is pinned.

```bash
uv sync --locked
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run python -m unittest discover -s tests -v
```

The tests take about 40 seconds and need no model. The live-model test runs only when you set `OUTAGE_LLM_BASE_URL` and `OUTAGE_LLM_MODEL`.

## Run

You need an OpenAI-compatible endpoint for the two model nodes. Every output directory must be new or empty.

```bash
uv run python -m outage_poc --output outputs/run_01 \
    --base-url http://127.0.0.1:8012/v1 \
    --model qwen2.5-32b-instruct-awq --verifier-model qwen2.5-32b-instruct-awq \
    --maps
```

- `--api-key-env VAR` names the environment variable that holds the API key, if the endpoint needs one.
- `--recent-steps 3` adds the last three steps to the context (condition B). The default is condition A.
- `--step-cap`, `--query-budget` (default 1600 locations), `--time-cap`, `--boundary-share` (default 0) set the caps and the boundary threshold.
- `--script FILE` replaces the decision model with recorded replies, for regression; the verifier still calls the model.
- `--maps` writes one SVG map per step and `index.html`.

The command prints the typed end reason and the counters.

### Resume a run (human at the boundary)

A person reads the trace, takes the State of a Step, corrects it, and resumes:

```bash
python3 -c "import json,sys; json.dump(json.load(open(sys.argv[1]))['state_after'], open(sys.argv[2],'w'), indent=2)" \
    outputs/run_01/steps/step_04.json corrected_04.json
# edit corrected_04.json
uv run python -m outage_poc --resume outputs/run_01 --from-step 4 --state corrected_04.json \
    --output outputs/run_01_resumed --base-url ... --model ... --verifier-model ...
```

Resume checks the registry version and the data version against the Step, checks the corrected State against the cached observations, copies steps 1 to 4 unchanged, and continues the loop from `loop_guards` with the corrected State as the State after step 4. The original directory does not change.

### Export for the UI

```bash
uv run python -m outage_poc.export_ui --run outputs/run_01 --out /tmp/case.js
```

The export carries, per step, the decision, the validation outcome and message, the review and its reason, the Notes added, and the counters; per run, the end reason. The UI scenes do not read this format yet.

## Modules

| Module | Responsibility |
| --- | --- |
| `models.py` | All data contracts: frozen dataclasses, `Literal` sets, `NewType` ids |
| `data_tools.py` | The synthetic tool library: `cell.lookup`, `osm.geometry`, `coverage.query`, `kpi.query`, each with its declaration |
| `data_client.py` | The data seam: `DataClient` protocol, `LocalClient` over tool functions, typed results, per-call timeout |
| `registry.py` | Policy table, startup join with the tool declarations, phases, preconditions, registry version |
| `init.py` | Initialization: the two lookups, `derive_areas`, `derive_relations`, State 0 |
| `context.py` | Stable prefix and variable part rendered from State |
| `model.py` | `llm_call`'s model (`ChatModel`), the chat client, `ScriptedModel` for regression |
| `decision.py` | Parser, validation checks, budget check, route |
| `verifier.py` | The verifier's model (`ChatVerifier`) and its strict reply parser |
| `observation.py` | Tool rows per member parsed into one Observation; absent rows are missing data |
| `state.py` | State updates: coverage, KPI, impact, inspection, Notes; `estimate_impact` |
| `checks.py` | The four completion rules |
| `caps.py` | Caps and the repeated area-query guard |
| `loop.py` | The nodes, the plain loop over them, Step writing, the runner |
| `checkpoint.py` | Resume from a Step |
| `persistence.py` | JSON writing, strict decoding |
| `synthetic.py` | The synthetic data behind the tool library; the harness never imports it |
| `render.py`, `export_ui.py`, `run.py` | Maps and page, UI export, command line |

## Actions

| Action | Runs on | Phase | Parameters |
| --- | --- | --- | --- |
| `cell.lookup` | tool library | initialization | cell id |
| `osm.geometry` | tool library | initialization | centre x, y (m), radius (m) |
| `coverage.query` | tool library | coverage | 1 to 4 areas, epoch (the task's); costs the new locations |
| `kpi.query` | tool library | backup | 1 to 4 cells seen in coverage, window (the task's), indicators `prb_utilization`, `capacity` |
| `impact.estimate` | program | backup | scope area, min RSRP (dBm), min RSRQ (dB); needs both indicators for every backup candidate |
| `inspect_observation` | program | any | an observation id from the provenance list, first row; returns up to 50 rows into the next context |
| `finish` | program | any | none; the reason is the gap question |

The model's reply is three lines: `action:`, `parameters:` (JSON), `gap:` (JSON with `targets` and `question`). Every gap except a finish names its targets.

## Run directory

```
run.json                      run id, config, both model names, end reason, counters
trace.json                    config, the Step files in order, end reason
states/state_00.json          State 0 (and a corrected State after a resume)
contexts/prefix.txt           the stable prefix: skill, task, geography, areas, actions, completion checks
contexts/state_NN.txt         the variable part rendered after round NN
inputs/round_NN.txt           the exact text sent to the model: prefix, blank line, variable part
outputs/round_NN.txt          the model's reply
observations/obs_NN.json      the Observation of round NN
observations/obs_NN_<m>.json  the parsed rows of member <m>
steps/step_NN.json            the Step: decision, validation, review, Observation, both full States,
                              counters, data version, query cache, registry version
maps/step_NN.svg, index.html  with --maps; for people only
```

## Synthetic case

A 6 km by 4 km study area with a 100 m grid (2,400 locations), down cell D0 and backup cells B1, B2, B3. Fifteen top-level areas tile the study area: settlements S1, S2, S3, road corridors H1_buffer (300 m) and H2_buffer (500 m), and land use F1 to F8, V1, W1. S2 has two sub-areas, S2_roadside and S2_remaining. The key areas of the completion check are the fifteen top-level areas: each must be queried, or listed in the finish gap targets with the reason in the question.

The cheapest query set that leaves no D0 on the query boundary is 1,432 locations; with the corridors and S3 it is about 1,480, inside the default budget of 1,600. `tests/scripts/complete.txt` is such a run.

## Data semantics

- Unqueried, queried with missing data, valid with no cell, and valid with other cells but not the down cell are different observations. A requested location without a row has missing data.
- Pre-outage presence of the down cell does not show that it served the location. The synthetic traffic is an explicit demand value, not population from land use.
- Land-use labels do not establish demand; farmland or forest does not mean zero demand.
- The query boundary of an area is the queried locations with an unqueried edge neighbour in the same area. Signal values do not select it.
- A grid location counts once; the newest observation wins. New coverage or KPI evidence invalidates a computed impact.
- The load formula is a PRB-only demonstration, not a calibrated network model.

Passing the completion checks shows that the four rules hold. It does not show that the investigation is sufficient.
