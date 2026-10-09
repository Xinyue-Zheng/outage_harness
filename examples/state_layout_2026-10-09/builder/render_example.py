"""Render the example context from the proposed two-file State layout.

Run from the agentic_test environment, so that the outage_poc package and its
synthetic tool library are importable:

    uv run --project /scr/xiz23015/agentic_test python render_example.py
"""

import sys
from pathlib import Path

from outage_poc.data_client import LocalClient
from outage_poc.data_tools import synthetic_tools
from outage_poc.models import RunConfig
from outage_poc.registry import build_registry
from outage_poc.synthetic import build_dataset

from context import render_context
from state_model import load_state


def main(snapshot: Path, output: Path) -> None:
    state = load_state(snapshot)
    registry = build_registry(
        LocalClient(synthetic_tools(build_dataset())).list_tools()
    )
    rendered = render_context(state, registry, RunConfig(data_version=None), ())
    output.write_text(rendered.text, encoding="utf-8")
    print(
        f"{output}: prefix {len(rendered.prefix)} chars, variable {len(rendered.variable)} chars"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
