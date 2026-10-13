# Per-point coverage wiring for the internal LangGraph harness

Replaces the heatmap coverage path (serving sector only) with the point API
(serving sector plus strongest neighbour cells per sample), so State and the
context know, per area, how many down-cell locations also report an eligible
backup cell. The LLM still names an area id; the program resolves it to grid
locations and calls the point API once per location.

Start with `STEP_BY_STEP_2026-10-13.md`. `WIRING_2026-10-13.md` explains the
design and lists the open gaps. `test_node_sequence.py` replays the node
sequence with the internal helpers copied verbatim and must pass before and
after your edits:

```
python test_node_sequence.py
python run_demo.py demo_run
```

Files:

| File | Role |
|---|---|
| `point_coverage.py` | fetch an area through the point API, fold the artifact into State, per-area summaries, inspection |
| `context_builder_point.py` | the context builder for the new State (replaces `context_builder.py`) |
| `runner_point_nodes.py` | the validate, execute and update pieces for `langgraph_runner.py`, plus the tool declaration and the location budget |
| `point_by_point_cover.py` | the point API function as it is internally (`BASE_URL` and token blank) |
| `synthetic_data_sample.json` | the shape of one API response |
| `synthetic_case.py`, `run_demo.py` | a synthetic site and a fake point API in that shape |
| `test_support/outage_harness_langgraph/` | stand-ins for the internal `radio` module and skill text, used only outside |
| `demo_run/` | the outputs of `run_demo.py`: states, artifacts and rendered contexts |

Sector names: the production modules treat `sector_name` as an opaque string
and never parse it. The sample data uses names such as `CCL00001_aa_1` only as
placeholders. The test double `radio.py` classifies technology by the leading
three letters plus five digits (LTE) or four letters plus six digits (NR), the
rule from the internal policy module; whatever follows is ignored. The real
`radio` module in the package replaces it.
