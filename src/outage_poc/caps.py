"""Run caps and the repeated-query guard. Each produces a typed end reason."""

import hashlib
import json

from outage_poc.decision import convert
from outage_poc.models import (
    ActionSpec,
    Counters,
    EndReason,
    ParameterValue,
    RunConfig,
    StepDigest,
)
from outage_poc.registry import Registry


def hit(counters: Counters, config: RunConfig) -> EndReason | None:
    """Step cap, then query budget, then wall time."""
    if counters.step >= config.step_cap:
        return "step_cap"
    if counters.queried_locations > config.query_budget_locations:
        return "query_budget"
    if counters.elapsed_s > config.time_cap_s:
        return "time_cap"
    return None


def query_key(action: ActionSpec, parameters: dict[str, ParameterValue]) -> str:
    """SHA-256 over the action name and its typed parameters, set members sorted."""
    canonical = json.dumps(
        {"action": action.name, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def repeated(
    history: tuple[StepDigest, ...], registry: Registry, config: RunConfig
) -> bool:
    """True when the last round repeated an accepted query that costs area.

    Only actions whose cost is counted in queried locations are hashed: a
    repeat would spend the budget again. Other repeats are bounded by the step cap.
    """
    if not history or history[-1].validation != "accepted":
        return False
    keys: list[str] = []
    for digest in history:
        if digest.validation != "accepted" or digest.decision is None:
            continue
        action = registry.get(digest.decision.action)
        if action is None:
            raise ValueError(f"Step {digest.index} accepted an unknown action")
        if action.cost != "locations_in_areas":
            continue
        typed = convert(action, digest.decision.parameters)
        if isinstance(typed, str):
            raise ValueError(
                f"Step {digest.index} was accepted with bad parameters: {typed}"
            )
        keys.append(query_key(action, typed))
    last = history[-1].decision
    if last is None:
        return False
    action = registry.get(last.action)
    if action is None or action.cost != "locations_in_areas":
        return False
    return keys.count(keys[-1]) >= config.repeated_query_threshold
