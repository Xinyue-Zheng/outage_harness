"""The action registry: one entry per action, built once per run by joining the
server's tool list with the program's policy table.

The server owns each data action's name, description and parameter schema. The
program owns everything else: phase, parameter kinds and units, allowed values,
set caps, preconditions, cost and result kind. Any disagreement between the two
is a startup error.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import assert_never

from outage_poc.data_client import ToolDeclaration
from outage_poc.models import (
    ActionPhase,
    ActionSpec,
    Cost,
    ParameterSpec,
    Phase,
    Precondition,
    ResultKind,
    RunsOn,
    State,
)
from outage_poc.state import candidates_without_kpi, queried_d0_present


class RegistryMismatch(Exception):
    def __init__(self, name: str, detail: str) -> None:
        super().__init__(f"Registry mismatch for {name}: {detail}")
        self.name = name


@dataclass(frozen=True)
class PolicyEntry:
    """The program side of an action: an ActionSpec without the server's description."""

    name: str
    runs_on: RunsOn
    phase: ActionPhase
    parameters: tuple[ParameterSpec, ...]
    precondition: Precondition
    cost: Cost
    result: ResultKind
    # The description of a program action; None for a server action.
    description: str | None


def _number(name: str, unit: str) -> ParameterSpec:
    return ParameterSpec(name, "float", unit, False, 1, "any", None)


def _epoch(name: str) -> ParameterSpec:
    """A parameter that must equal the coverage epoch the task fixed at initialization."""
    return ParameterSpec(name, "str", None, False, 1, "task_epoch", None)


KPI_INDICATORS = ("prb_utilization", "capacity")

POLICY: tuple[PolicyEntry, ...] = (
    PolicyEntry(
        "cell.lookup",
        "server",
        "initialization",
        (ParameterSpec("cell_id", "cell_id", None, False, 1, "any", None),),
        "none",
        "zero",
        "cell_metadata",
        None,
    ),
    PolicyEntry(
        "osm.geometry",
        "server",
        "initialization",
        (
            _number("center_x_m", "m"),
            _number("center_y_m", "m"),
            _number("radius_m", "m"),
        ),
        "none",
        "zero",
        "geography",
        None,
    ),
    PolicyEntry(
        "coverage.query",
        "server",
        "coverage",
        (
            ParameterSpec("areas", "area_id", None, True, 4, "areas_in_state", None),
            _epoch("epoch"),
        ),
        "none",
        "locations_in_areas",
        "coverage_rows",
        None,
    ),
    PolicyEntry(
        "kpi.query",
        "server",
        "backup",
        (
            ParameterSpec("cells", "cell_id", None, True, 4, "cells_in_state", None),
            _epoch("window"),
            ParameterSpec("indicators", "str", None, True, 2, "any", KPI_INDICATORS),
        ),
        "queried_d0_present",
        "zero",
        "kpi_rows",
        None,
    ),
    PolicyEntry(
        "impact.estimate",
        "program",
        "backup",
        (
            ParameterSpec("scope", "area_id", None, False, 1, "areas_in_state", None),
            _number("min_rsrp_dbm", "dBm"),
            _number("min_rsrq_db", "dB"),
        ),
        "kpi_present_for_candidates",
        "zero",
        "impact",
        "Assign the synthetic traffic of each queried location in the scope where "
        "the down cell was present to its strongest eligible backup cell, then "
        "estimate each backup cell's PRB load. Needs both KPI indicators for every "
        "backup candidate.",
    ),
    PolicyEntry(
        "inspect_observation",
        "program",
        "any",
        (
            ParameterSpec(
                "observation",
                "observation_id",
                None,
                False,
                1,
                "observations_in_state",
                None,
            ),
            ParameterSpec("first_row", "int", None, False, 1, "any", None),
        ),
        "observation_present",
        "zero",
        "observation_rows",
        "Show the rows of one coverage observation listed under Evidence provenance, "
        "starting at first_row (0-based), up to the row cap of the run. Use it when "
        "the counts are not enough, for example to see the cells and signal levels "
        "on a query boundary.",
    ),
    PolicyEntry(
        "finish",
        "program",
        "any",
        (),
        "none",
        "zero",
        "none",
        "Propose to end the investigation. The gap targets list the key areas left "
        "unqueried; the gap question gives the reason. The run ends only when the "
        "completion checks pass; otherwise the unmet checks come back as feedback.",
    ),
)


def _json_type(spec: ParameterSpec) -> dict[str, object]:
    match spec.kind:
        case "area_id" | "cell_id" | "observation_id" | "str":
            scalar = "string"
        case "float":
            scalar = "number"
        case "int":
            scalar = "integer"
        case _ as unreachable:
            assert_never(unreachable)
    if spec.set_valued:
        return {"type": "array", "items": {"type": scalar}}
    return {"type": scalar}


def _check_schema(entry: PolicyEntry, tool: ToolDeclaration) -> None:
    schema = tool.input_schema
    properties = schema.get("properties")
    if schema.get("type") != "object" or not isinstance(properties, dict):
        raise RegistryMismatch(entry.name, "server schema is not an object schema")
    expected = {spec.name for spec in entry.parameters}
    declared = {str(name) for name in properties}
    if declared != expected:
        raise RegistryMismatch(
            entry.name,
            f"server declares parameters {sorted(declared)}, policy expects {sorted(expected)}",
        )
    required = schema.get("required")
    if not isinstance(required, list) or {str(name) for name in required} != expected:
        raise RegistryMismatch(
            entry.name, f"server requires {required}, policy expects {sorted(expected)}"
        )
    for spec in entry.parameters:
        prop = properties[spec.name]
        wanted = _json_type(spec)
        if not isinstance(prop, dict):
            raise RegistryMismatch(entry.name, f"parameter {spec.name} has no schema")
        got = {key: prop[key] for key in wanted if key in prop}
        if got != wanted:
            raise RegistryMismatch(
                entry.name, f"parameter {spec.name} is {got}, policy expects {wanted}"
            )


@dataclass(frozen=True)
class Registry:
    actions: tuple[ActionSpec, ...]
    # SHA-256 over the canonical JSON of the joined entries and the server's tool list.
    version: str

    def get(self, name: str) -> ActionSpec | None:
        matches = [action for action in self.actions if action.name == name]
        return matches[0] if matches else None

    def allowed(self, state: State) -> tuple[ActionSpec, ...]:
        """Loop actions whose precondition holds against the State.

        Coverage actions stay allowed in the backup phase, because the
        investigation may still widen its area after the first D0 location.
        """
        return tuple(
            action
            for action in self.actions
            if precondition_failure(action, state) is None
        )


def build_registry(tools: tuple[ToolDeclaration, ...]) -> Registry:
    """Join the server's tools/list with the policy table. Any mismatch raises."""
    by_name = {tool.name: tool for tool in tools}
    if len(by_name) != len(tools):
        raise RegistryMismatch("tools/list", "the server lists a tool name twice")
    policy_names = {entry.name for entry in POLICY}
    for name in by_name:
        if name not in policy_names:
            raise RegistryMismatch(
                name, "the server offers a tool with no policy entry"
            )
    actions: list[ActionSpec] = []
    for entry in POLICY:
        match entry.runs_on:
            case "server":
                if entry.name not in by_name:
                    raise RegistryMismatch(entry.name, "the server does not offer it")
                if entry.description is not None:
                    raise RegistryMismatch(
                        entry.name,
                        "a server action takes its description from the server",
                    )
                tool = by_name[entry.name]
                _check_schema(entry, tool)
                description = tool.description
            case "program":
                if entry.description is None:
                    raise RegistryMismatch(
                        entry.name, "a program action needs a description"
                    )
                description = entry.description
            case _ as unreachable:
                assert_never(unreachable)
        actions.append(
            ActionSpec(
                entry.name,
                description,
                entry.runs_on,
                entry.phase,
                entry.parameters,
                entry.precondition,
                entry.cost,
                entry.result,
            )
        )
    canonical = json.dumps(
        {
            "actions": [asdict(action) for action in actions],
            "server": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in sorted(tools, key=lambda tool: tool.name)
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return Registry(tuple(actions), hashlib.sha256(canonical.encode()).hexdigest())


def current_phase(state: State) -> Phase:
    """Coverage until a queried location lists the down cell; backup after that."""
    return "backup" if queried_d0_present(state) else "coverage"


def precondition_failure(action: ActionSpec, state: State) -> str | None:
    """None when the action may run against this State; else the State fact that blocks it."""
    if action.phase == "initialization":
        return (
            f"{action.name} runs only during initialization, before the first decision"
        )
    down = state.task.down_cell_id
    match action.precondition:
        case "none":
            return None
        case "queried_d0_present":
            if queried_d0_present(state):
                return None
            return (
                f"precondition queried_d0_present does not hold: no queried "
                f"location lists {down} yet"
            )
        case "kpi_present_for_candidates":
            # Backup candidates exist only once queried locations list the down cell.
            if not queried_d0_present(state):
                return (
                    f"precondition kpi_present_for_candidates does not hold: no "
                    f"queried location lists {down} yet"
                )
            missing = candidates_without_kpi(state)
            if missing:
                return (
                    "precondition kpi_present_for_candidates does not hold: "
                    f"{'; '.join(missing)}"
                )
            return None
        case "observation_present":
            if state.observations:
                return None
            return (
                "precondition observation_present does not hold: no coverage "
                "observation exists yet"
            )
        case _ as unreachable:
            assert_never(unreachable)
