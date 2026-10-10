"""Sample code for the two program checks on an information gap.

A decision carries an action, its parameters, and a gap: the question the
action is meant to answer, with `targets`, the area ids or cell ids the
question is about. The program reads only the targets. The question sentence
is free text for the verifier model and for the trace.

Check 3, targets agree with State:
    every target is an id the State knows, and the State does not already
    answer it for the kind of result the action returns.
Check 4, the action can answer the gap:
    the kind of result the action returns matches the kind of targets, and the
    targets are among the things the action is asked to query.

Both checks return the first Rejection found, or None. A Rejection names the
wrong thing and the right things, so the deciding model can correct itself.

Run the demo from the harness environment, next to the proposed State layout:

    cd examples/gap_checks_2026-10-10
    uv run --project ../.. python gap_checks.py ../state_layout_2026-10-09/state_01.json
"""

import sys
from pathlib import Path
from typing import Literal, assert_never

from outage_poc.models import (
    KPI_UNITS,
    ActionSpec,
    AreaId,
    Gap,
    ParameterValue,
    Rejection,
)

from state_model import State, key_areas, load_state, summary_for

TargetKind = Literal["area", "cell"]


def _known_areas(state: State) -> set[str]:
    return {area.id for area in state.geography.areas}


def _cells_seen(state: State) -> set[str]:
    """Every cell a valid coverage record lists, the down cell included."""
    return {cell.cell_id for cell in summary_for(state, AreaId("Study_area")).cells}


def _kind_of(target: str, state: State) -> TargetKind | None:
    if target in _known_areas(state):
        return "area"
    if target in _cells_seen(state):
        return "cell"
    return None


def _cells_with_both_kpis(state: State) -> set[str]:
    held = {(record.cell_id, record.indicator) for record in state.kpis}
    return {
        cell
        for cell in _cells_seen(state)
        if all((cell, indicator) in held for indicator in KPI_UNITS)
    }


def _open_key_areas(state: State) -> set[str]:
    return {area for area in key_areas(state) if summary_for(state, area).unqueried}


def _ids(parameters: dict[str, ParameterValue], name: str) -> set[str]:
    value = parameters.get(name)
    if not isinstance(value, tuple):
        raise TypeError(f"parameter {name!r} must be a set of ids")
    return set(value)


# Check 3.


def targets_agree_with_state(
    action: ActionSpec, gap: Gap, state: State
) -> Rejection | None:
    """Rule 3a: every target is a known area or a cell seen in a valid record.
    Rule 3b: every action except finish names at least one target.
    Rule 3c: no target is already answered for the result the action returns."""
    if action.name != "finish" and not gap.targets:
        return Rejection(
            "bad_parameter",
            f"the gap of {action.name} names no targets; list the area ids or "
            "cell ids the question is about",
        )
    for target in gap.targets:
        if _kind_of(target, state) is None:
            return Rejection(
                "bad_parameter",
                f'gap target "{target}" is neither a known area nor a cell seen; '
                f"known areas: {', '.join(sorted(_known_areas(state)))}; cells "
                f"seen: {', '.join(sorted(_cells_seen(state)))}",
            )
    match action.result:
        case "coverage_rows":
            # An area with nothing left to learn from a coverage query.
            for target in gap.targets:
                if _kind_of(target, state) != "area":
                    continue
                summary = summary_for(state, AreaId(target))
                if not summary.unqueried and not summary.missing:
                    return Rejection(
                        "gap_contradicted",
                        f"gap target {target} is already answered: all "
                        f"{summary.queried} locations are queried and none has "
                        "missing data",
                    )
        case "kpi_rows":
            complete = _cells_with_both_kpis(state)
            for target in gap.targets:
                if target in complete:
                    return Rejection(
                        "gap_contradicted",
                        f"gap target {target} is already answered: State holds "
                        "both of its pre-outage KPI indicators",
                    )
        case "none":
            # finish: the targets are the key areas it leaves unqueried.
            open_areas = _open_key_areas(state)
            for target in gap.targets:
                if target not in open_areas:
                    return Rejection(
                        "gap_contradicted",
                        f"finish lists {target} as left unqueried, but the key "
                        "areas with unqueried locations are: "
                        f"{', '.join(sorted(open_areas)) or 'none'}",
                    )
        case "impact" | "observation_rows" | "cell_metadata" | "geography":
            # Nothing in State makes these targets already answered.
            pass
        case _ as unreachable:
            assert_never(unreachable)
    return None


# Check 4.


def action_can_answer_gap(
    action: ActionSpec,
    parameters: dict[str, ParameterValue],
    gap: Gap,
    state: State,
) -> Rejection | None:
    """Rule 4a: the result kind matches the target kind (areas for coverage,
    cells for KPI, one scope area for impact).
    Rule 4b: the targets are among the ids the action is asked to query."""
    areas = [t for t in gap.targets if _kind_of(t, state) == "area"]
    cells = [t for t in gap.targets if _kind_of(t, state) == "cell"]
    match action.result:
        case "coverage_rows":
            if cells:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} returns coverage of areas; it cannot answer a "
                    f"question about cell {cells[0]}; use kpi.query for cell KPI",
                )
            outside = sorted(set(areas) - _ids(parameters, "areas"))
            if outside:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} queries {sorted(_ids(parameters, 'areas'))}, "
                    f"so it cannot answer a question about {outside[0]}; add it "
                    "to the areas or change the gap targets",
                )
        case "kpi_rows":
            if areas:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} returns KPI of cells; it cannot answer a "
                    f"question about area {areas[0]}; use coverage.query for areas",
                )
            outside = sorted(set(cells) - _ids(parameters, "cells"))
            if outside:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} queries {sorted(_ids(parameters, 'cells'))}, "
                    f"so it cannot answer a question about {outside[0]}; add it "
                    "to the cells or change the gap targets",
                )
        case "impact":
            scope = parameters.get("scope")
            if cells or len(areas) > 1 or (areas and areas[0] != scope):
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} answers a question about its one scope area "
                    f"({scope}); the gap targets are {list(gap.targets)}",
                )
        case "observation_rows":
            if cells:
                return Rejection(
                    "action_cannot_answer_gap",
                    f"{action.name} shows coverage rows of an area; it cannot "
                    f"answer a question about cell {cells[0]}",
                )
        case "none" | "cell_metadata" | "geography":
            pass
        case _ as unreachable:
            assert_never(unreachable)
    return None


def check_gap(
    action: ActionSpec,
    parameters: dict[str, ParameterValue],
    gap: Gap,
    state: State,
) -> Rejection | None:
    """Check 3, then check 4. The first failure is the rejection."""
    rejection = targets_agree_with_state(action, gap, state)
    if rejection is not None:
        return rejection
    return action_can_answer_gap(action, parameters, gap, state)


# Demo against the round-1 State of the proposed layout.


def _demo(snapshot: Path) -> None:
    from outage_poc.data_client import LocalClient
    from outage_poc.data_tools import synthetic_tools
    from outage_poc.registry import build_registry
    from outage_poc.synthetic import build_dataset

    state = load_state(snapshot)
    registry = build_registry(
        LocalClient(synthetic_tools(build_dataset())).list_tools()
    )

    def spec(name: str) -> ActionSpec:
        action = registry.get(name)
        if action is None:
            raise ValueError(name)
        return action

    cases: list[tuple[str, ActionSpec, dict[str, ParameterValue], Gap]] = [
        (
            "accepted: open areas, same as the queried areas",
            spec("coverage.query"),
            {"areas": ("F5", "H2_buffer"), "epoch": "pre_outage"},
            Gap(("F5", "H2_buffer"), "Does D0 coverage continue east along H2?"),
        ),
        (
            "3a: unknown target",
            spec("coverage.query"),
            {"areas": ("F5",), "epoch": "pre_outage"},
            Gap(("F9",), "Is F9 covered by D0?"),
        ),
        (
            "3b: no target",
            spec("coverage.query"),
            {"areas": ("F5",), "epoch": "pre_outage"},
            Gap((), "Is F5 covered by D0?"),
        ),
        (
            "3c: area already fully queried with no missing data",
            spec("coverage.query"),
            {"areas": ("S2_roadside",), "epoch": "pre_outage"},
            Gap(("S2_roadside",), "Is the roadside of S2 covered by D0?"),
        ),
        (
            "3c: finish names an area that is not an open key area",
            spec("finish"),
            {},
            Gap(("S1",), "S1 is left unqueried because it is far from D0."),
        ),
        (
            "4a: coverage query asked about a cell",
            spec("coverage.query"),
            {"areas": ("F5",), "epoch": "pre_outage"},
            Gap(("B1",), "How loaded is B1?"),
        ),
        (
            "4a: KPI query asked about an area",
            spec("kpi.query"),
            {"cells": ("B1",), "window": "pre_outage", "indicators": ("capacity",)},
            Gap(("F5",), "Can B1 carry F5?"),
        ),
        (
            "4b: target outside the queried areas",
            spec("coverage.query"),
            {"areas": ("F5",), "epoch": "pre_outage"},
            Gap(("S3",), "Is S3 covered by D0?"),
        ),
        (
            "4a: impact asked about two areas",
            spec("impact.estimate"),
            {"scope": "Study_area", "min_rsrp_dbm": -110.0, "min_rsrq_db": -15.0},
            Gap(("S1", "S2"), "Which backup serves S1 and S2?"),
        ),
    ]
    for title, action, parameters, gap in cases:
        result = check_gap(action, parameters, gap, state)
        print(f"[{title}]")
        print(f"  {action.name} {parameters} targets={list(gap.targets)}")
        if result is None:
            print("  -> accepted")
        else:
            print(f"  -> rejected ({result.kind}): {result.message}")
        print()


if __name__ == "__main__":
    _demo(Path(sys.argv[1]))
