"""Test double of the internal radio helpers: outage prefixes, technology, backup eligibility.

Semantics mirrored from the internal context builder and policy module:
- `task["outage_cell_ids"]`, when present, lists explicit outage prefixes;
  otherwise the prefix is `task["down_cell_id"]`.
- A prefix without a dash names a whole EnodeB: every sector whose ID starts
  with it is an outage cell.
- LTE IDs are three letters + five digits (CCL06069...), NR IDs four letters +
  six digits (CCSN003553...). A backup must share the technology of an outage
  prefix and must not be an outage cell.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_NR_ID = re.compile(r"^[A-Z]{4}\d{6}(?!\d)")
_LTE_ID = re.compile(r"^[A-Z]{3}\d{5}(?!\d)")


def outage_prefixes(task: Mapping[str, Any]) -> list[str]:
    explicit = task.get("outage_cell_ids")
    if isinstance(explicit, list) and explicit:
        return [str(item) for item in explicit]
    down = task.get("down_cell_id")
    return [str(down)] if down else []


def radio_technology(cell: str) -> str | None:
    if _NR_ID.match(cell):
        return "NR"
    if _LTE_ID.match(cell):
        return "LTE"
    return None


def is_outage_cell(cell: str, task: Mapping[str, Any]) -> bool:
    return any(cell == prefix or cell.startswith(prefix) for prefix in outage_prefixes(task))


def eligible_backup_cells(cells: Iterable[str], task: Mapping[str, Any]) -> list[str]:
    technologies = {
        technology
        for prefix in outage_prefixes(task)
        if (technology := radio_technology(prefix))
    }
    return sorted(
        cell
        for cell in set(cells)
        if not is_outage_cell(cell, task)
        and (technology := radio_technology(cell)) is not None
        and (not technologies or technology in technologies)
    )
