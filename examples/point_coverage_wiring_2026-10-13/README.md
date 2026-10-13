# Per-point coverage wiring for the internal LangGraph harness

Modules, a synthetic case and two notes for switching the internal harness
from the coverage heatmap (serving sector only) to the per-point API (serving
sector plus the strongest neighbour cells per sample), so the State can say
at how many locations the outage sectors serve and at how many of those an
eligible backup cell is also observed.

- `STEP_BY_STEP_2026-10-13.md`: the edits, file by file, in order.
- `WIRING_2026-10-13.md`: data flow, State fields, the context lines, open gaps.
- `point_coverage.py`, `context_builder_point.py`, `runner_point_nodes.py`:
  the modules to copy into the internal package.
- `point_by_point_cover.py`: the point API function as it is today (URL and
  token blank). `synthetic_data_sample.json`: the shape of one API reply
  (Python literal, not JSON; numbers blanked).
- `synthetic_case.py`, `run_demo.py`, `test_node_sequence.py`,
  `test_support/`: run outside the internal environment with any Python 3.12.
- `demo_run/`: output of `run_demo.py`.

The internal files these patch (`langgraph_runner.py`, `runner.py`,
`policy.py`, `evidence_state.py`, `context_builder.py`, `gap_checks.py`) are
not in this repository.
