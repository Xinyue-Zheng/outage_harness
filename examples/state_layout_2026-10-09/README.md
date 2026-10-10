# Proposed State layout, 2026-10-09

A candidate two-file State layout and the context builder that reads it. Not
wired into the harness: the loop, persistence and checkpoints still use the
State in `src/outage_poc`.

- `geography.json`: written once per run after initialization. Coordinate
  system, analysis grid, object geometries, area geometries and area grid ids.
- `state_01.json`: the snapshot after round 1 of a real run. Task, the
  geography section without coordinates (objects, relations, areas, and the
  name and SHA-256 of `geography.json`), the coverage table with one entry per
  queried location, observation references, count-only summaries per area with
  one entry per cell, KPI records, impact, inspection, notes and unknowns.
- `derived_view_B1_in_S1.json`: one cell's RSRP per location in one area, as a
  program derives it from the coverage table; not stored in State.
- `investigation_skill.txt`: the fixed skill text that opens every context.
- `context_01.txt`: the context rendered from `state_01.json`.
- `LLM_input.txt`: how that context reaches the model: the prefix as the
  system message, the variable part as the user message, and the exact JSON
  request body.
- `LLM_input.txt`: the same text laid out as the two chat messages the program
  sends: the prefix as the system message, the variable part as the user message.
- `Verifier_input.txt`: the two messages the verifier model receives for one
  accepted decision: fixed instructions, then the same context plus the decision.
- `state_02.json`: the snapshot after round 2, in which the model asked to
  inspect `obs_01_S1`. Coverage is unchanged; only `inspection` is set.
- `context_02.txt`: the full context rendered from `state_02.json` for round
  3. It includes all 36 drill-down rows of `obs_01_S1`, read from the
  coverage table.
- `builder/state_model.py`: the State contracts, the loader that reads a
  snapshot and the geometry file it names (hash-checked), and the State facts
  the builder needs.
- `builder/context.py`: the context builder for this layout. Same section
  order and `Rendered(prefix, variable)` contract as `src/outage_poc/context.py`.
- `builder/render_example.py`: renders a context from a snapshot.

Render the example from the repository root:

```
cd examples/state_layout_2026-10-09/builder
uv run --project ../../.. python render_example.py ../state_01.json ../context_01.txt
```
