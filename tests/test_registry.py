"""Build step 2: the policy table joined with the tool declarations."""

import unittest
from dataclasses import replace

from support import DATASET, initial_state, query, tool_declarations

from outage_poc.data_client import ToolDeclaration
from outage_poc.models import CoverageObservation, ObservationId
from outage_poc.persistence import _object
from outage_poc.registry import RegistryMismatch, build_registry, current_phase
from outage_poc.state import apply_kpi


def _with_schema(tool: ToolDeclaration, schema: dict[str, object]) -> ToolDeclaration:
    return replace(tool, input_schema=schema)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = tool_declarations()

    def test_matching_tool_list_builds(self) -> None:
        registry = build_registry(self.tools)
        self.assertEqual(
            [action.name for action in registry.actions],
            [
                "cell.lookup",
                "osm.geometry",
                "coverage.query",
                "kpi.query",
                "impact.estimate",
                "inspect_observation",
                "finish",
            ],
        )
        server = {tool.name: tool.description for tool in self.tools}
        coverage = registry.get("coverage.query")
        self.assertIsNotNone(coverage)
        assert coverage is not None
        self.assertEqual(coverage.description, server["coverage.query"])
        self.assertEqual(len(registry.version), 64)
        self.assertEqual(build_registry(self.tools).version, registry.version)
        self.assertIsNone(registry.get("coverage.scan"))

    def test_missing_tool_raises_with_its_name(self) -> None:
        tools = tuple(tool for tool in self.tools if tool.name != "kpi.query")
        with self.assertRaises(RegistryMismatch) as raised:
            build_registry(tools)
        self.assertIn("kpi.query", str(raised.exception))

    def test_extra_tool_raises_with_its_name(self) -> None:
        extra = replace(self.tools[0], name="coverage.drop")
        with self.assertRaises(RegistryMismatch) as raised:
            build_registry((*self.tools, extra))
        self.assertIn("coverage.drop", str(raised.exception))

    def test_renamed_parameter_raises_with_the_tool_name(self) -> None:
        tools = []
        for tool in self.tools:
            if tool.name == "coverage.query":
                schema = dict(tool.input_schema)
                properties = dict(_object(schema["properties"]))
                properties["regions"] = properties.pop("areas")
                schema["properties"] = properties
                schema["required"] = ["regions", "epoch"]
                tool = _with_schema(tool, schema)
            tools.append(tool)
        with self.assertRaises(RegistryMismatch) as raised:
            build_registry(tuple(tools))
        self.assertIn("coverage.query", str(raised.exception))
        self.assertIn("regions", str(raised.exception))

    def test_wrong_parameter_type_raises(self) -> None:
        tools = []
        for tool in self.tools:
            if tool.name == "osm.geometry":
                schema = dict(tool.input_schema)
                properties = dict(_object(schema["properties"]))
                properties["radius_m"] = {"type": "string"}
                schema["properties"] = properties
                tool = _with_schema(tool, schema)
            tools.append(tool)
        with self.assertRaises(RegistryMismatch) as raised:
            build_registry(tuple(tools))
        self.assertIn("radius_m", str(raised.exception))

    def test_allowed_actions_follow_the_preconditions(self) -> None:
        registry = build_registry(self.tools)
        observations: dict[ObservationId, CoverageObservation] = {}
        state = initial_state()

        def allowed() -> list[str]:
            return [action.name for action in registry.allowed(state)]

        self.assertEqual(current_phase(state), "coverage")
        self.assertEqual(allowed(), ["coverage.query", "finish"])
        state = query(DATASET, state, "S1", "s1", observations)
        self.assertEqual(current_phase(state), "backup")
        self.assertEqual(
            allowed(), ["coverage.query", "kpi.query", "inspect_observation", "finish"]
        )
        # One indicator per candidate is not enough for impact.estimate.
        prb_only = tuple(
            kpi for kpi in DATASET.baseline_kpis if kpi.indicator == "prb_utilization"
        )
        state = apply_kpi(state, prb_only, "state_prb")
        self.assertNotIn("impact.estimate", allowed())
        state = apply_kpi(state, DATASET.baseline_kpis, "state_kpi")
        self.assertEqual(
            allowed(),
            [
                "coverage.query",
                "kpi.query",
                "impact.estimate",
                "inspect_observation",
                "finish",
            ],
        )


if __name__ == "__main__":
    unittest.main()
