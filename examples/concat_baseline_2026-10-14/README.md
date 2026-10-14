# Concatenation baseline (condition B) for the internal harness

A copy of `examples/point_coverage_wiring_2026-10-13` (condition A, the
harness with a rendered State) plus the pieces that turn it into the Codex
way of driving a model: an append-only transcript with raw tool output,
truncated as Codex truncates, schema-only validation, finish accepted as
proposed, no verifier.

- `CONCAT_STEP_BY_STEP_2026-10-14.md`: what condition B is, the measured
  input sizes on the synthetic case, the edits to the internal runner, and the
  live test design (conditions A, B, B+, B-full; metrics).
- `transcript.py`, `context_builder_concat.py`, `runner_concat_nodes.py`,
  `investigation_skill_concat.txt`: the condition B modules.
- `run_demo_concat.py`: both conditions on the synthetic case with the same
  scripted decisions; writes the exact model input per round to
  `demo_concat/A` and `demo_concat/B` and `demo_concat/comparison.json`.
- Everything else is the condition A base, unchanged.
