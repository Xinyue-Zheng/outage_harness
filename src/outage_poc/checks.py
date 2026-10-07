"""Completion checks: the only way a run ends with `complete`.

Passing the checks shows that these conditions hold. It does not show that the
investigation is sufficient; that needs comparison with known correct results.
"""

from dataclasses import dataclass
from typing import Literal

from outage_poc.decision import Finish, new_locations
from outage_poc.models import AreaId, RunConfig, State
from outage_poc.state import (
    STUDY_AREA,
    backup_candidates,
    baseline_kpis,
    d0_border_count,
    key_areas,
    summary_for,
)


@dataclass(frozen=True)
class Unmet:
    rule: Literal["boundary", "key_areas", "labels", "backup_load"]
    # Written for the model, with the numbers.
    text: str


def _boundary(state: State, config: RunConfig) -> Unmet | None:
    """The down cell's share of the study area's query boundary is within the cap.

    An empty boundary passes. A boundary without the down cell does not show
    that no location beyond it lists the down cell.
    """
    study = summary_for(state, STUDY_AREA)
    if not study.boundary_ids:
        return None
    share = len(study.boundary_target_ids) / len(study.boundary_ids)
    if share <= config.boundary_d0_max_share:
        return None
    return Unmet(
        "boundary",
        f"unmet boundary: the down cell is present at {len(study.boundary_target_ids)} "
        f"of {len(study.boundary_ids)} query-boundary locations "
        f"(allowed share {config.boundary_d0_max_share:g})",
    )


def _key_areas(state: State, finish: Finish) -> Unmet | None:
    """Every key area is fully queried, or the finish decision names it as left out.

    The finish gap's targets are the key areas the model leaves unqueried; its
    question gives the reason. Naming is the whole of the rule: whether the
    reason is good is for the verifier and for offline review, not for a check.
    """
    open_areas = [
        area_id
        for area_id in key_areas(state)
        if summary_for(state, area_id).unqueried_ids
        and area_id not in finish.gap.targets
    ]
    if not open_areas:
        return None
    counts = ", ".join(
        f"{area_id} ({len(summary_for(state, area_id).unqueried_ids)} unqueried, "
        f"{d0_border_count(state, area_id)} bordering {state.task.down_cell_id})"
        for area_id in open_areas
    )
    return Unmet(
        "key_areas",
        f"unmet key_areas: {counts}; query them, or list each one you leave "
        "unqueried in the finish gap targets and give the reason in the question",
    )


def _labels(state: State) -> Unmet | None:
    """Every study-area location has exactly one class: an invariant of the State."""
    study = summary_for(state, STUDY_AREA)
    classes = (
        study.unqueried_ids,
        study.missing_ids,
        study.no_coverage_ids,
        study.other_cells_only_ids,
        study.target_ids,
    )
    labelled = [grid_id for members in classes for grid_id in members]
    if len(labelled) == len(set(labelled)) and set(labelled) == set(study.total_ids):
        return None
    return Unmet(
        "labels",
        f"unmet labels: {len(study.total_ids)} study-area locations but "
        f"{len(labelled)} class labels ({len(set(labelled))} distinct)",
    )


def _backup_load(state: State) -> Unmet | None:
    """Impact is computed with a KPI record and a load for every backup candidate."""
    if state.impact is None:
        return Unmet(
            "backup_load", "unmet backup_load: impact.estimate has not been computed"
        )
    with_kpi = set(baseline_kpis(state))
    with_load = {load.cell_id for load in state.impact.backup_loads}
    missing = [
        cell
        for cell in backup_candidates(state)
        if cell not in with_kpi or cell not in with_load
    ]
    if not missing:
        return None
    return Unmet(
        "backup_load",
        f"unmet backup_load: no complete KPI or estimated load for {', '.join(missing)}",
    )


def budget_blocks_boundary(state: State, config: RunConfig) -> str | None:
    """The fact that ends a run as query_budget: some key area still borders an
    observed down-cell location, and even the cheapest such area costs more
    than the budget that remains. The boundary rule can then never pass, so
    the investigation cannot complete within this budget.

    Returns the sentence for the model and the Step, or None when the budget
    still allows at least one of those areas.
    """
    spent = len(summary_for(state, STUDY_AREA).queried_ids)
    remaining = config.query_budget_locations - spent
    bordering: list[tuple[int, AreaId]] = [
        (new_locations(state, (area_id,)), area_id)
        for area_id in key_areas(state)
        if summary_for(state, area_id).unqueried_ids
        and d0_border_count(state, area_id) > 0
    ]
    if not bordering:
        return None
    cost, cheapest = min(bordering)
    if cost <= remaining:
        return None
    return (
        f"the boundary check cannot be met within the budget: {cheapest} is the "
        f"cheapest key area whose unqueried locations border {state.task.down_cell_id} "
        f"and it would cost {cost} locations, but only {remaining} remain"
    )


def run(state: State, config: RunConfig, finish: Finish) -> tuple[Unmet, ...]:
    results = (
        _boundary(state, config),
        _key_areas(state, finish),
        _labels(state),
        _backup_load(state),
    )
    return tuple(result for result in results if result is not None)
