"""Build steps 3 and 4: the synthetic tool library, the local client, and result parsing."""

import json
import time
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from support import DATASET, FIXTURES, NEW_AREAS, client, initial_state

from outage_poc.data_client import (
    LocalClient,
    LocalTool,
    Rows,
    ToolDeclaration,
    ToolFailure,
    ToolTimeout,
    tools_data_version,
)
from outage_poc.data_tools import dataset_version
from outage_poc.models import CoverageRecord, Member, ObservationId
from outage_poc.observation import (
    coverage_member,
    kpi_member,
    observation_status,
    record_observation,
)
from outage_poc.persistence import decode, read_observation

S1_CALL: dict[str, object] = {"areas": ["S1"], "epoch": "pre_outage"}


class DataClientTests(unittest.TestCase):
    client: LocalClient

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = client()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run_dir = Path(temporary.name)
        self.state = initial_state()

    def rows(self, name: str, arguments: dict[str, object]) -> list[dict[str, object]]:
        result = self.client.call(name, arguments, 30.0)
        if not isinstance(result, Rows):
            self.fail(f"{name} returned {result}")
        return list(result.rows)

    def test_lists_four_tools_with_the_dataset_version(self) -> None:
        tools = self.client.list_tools()
        self.assertEqual(
            sorted(tool.name for tool in tools),
            ["cell.lookup", "coverage.query", "kpi.query", "osm.geometry"],
        )
        self.assertEqual(tools_data_version(tools), dataset_version(DATASET))

    def test_calls_each_tool(self) -> None:
        (cell,) = self.rows("cell.lookup", {"cell_id": "D0"})
        self.assertEqual((cell["x_m"], cell["y_m"]), (1000.0, 1300.0))
        geography = self.rows(
            "osm.geometry",
            {"center_x_m": 1000.0, "center_y_m": 1300.0, "radius_m": 4000.0},
        )
        self.assertEqual(
            [row["id"] for row in geography],
            ["Study_area", "S1", "S2", "S3", "H1", "H2", "F1", "V1", "F2"]
            + list(NEW_AREAS),
        )
        # H1 passes 100 m from the site; H2 starts 112 m from it.
        near = self.rows(
            "osm.geometry",
            {"center_x_m": 1000.0, "center_y_m": 1300.0, "radius_m": 100.0},
        )
        self.assertEqual([row["id"] for row in near], ["Study_area", "S1", "H1"])
        nearer = self.rows(
            "osm.geometry",
            {"center_x_m": 1000.0, "center_y_m": 1300.0, "radius_m": 115.0},
        )
        self.assertEqual(
            [row["id"] for row in nearer], ["Study_area", "S1", "H1", "H2"]
        )
        # S1 has 36 locations; the one with missing data has no row.
        coverage = self.rows("coverage.query", S1_CALL)
        self.assertEqual(len(coverage), 35)
        recorded = read_observation(FIXTURES / "obs_01.json").records
        self.assertEqual(
            tuple(
                decode(CoverageRecord, {k: v for k, v in row.items() if k != "area_id"})
                for row in coverage
            ),
            tuple(record for record in recorded if record.status == "valid"),
        )
        rows = self.rows(
            "kpi.query",
            {
                "cells": ["B1"],
                "window": "pre_outage",
                "indicators": ["prb_utilization", "capacity"],
            },
        )
        self.assertEqual(
            [(row["indicator"], row["value"], row["unit"]) for row in rows],
            [("prb_utilization", 52.0, "percent"), ("capacity", 70.0, "Mbps")],
        )

    def test_unknown_area_gives_a_member_error(self) -> None:
        result = self.client.call(
            "coverage.query", {"areas": ["S9"], "epoch": "pre_outage"}, 30.0
        )
        self.assertIsInstance(result, ToolFailure)
        member = coverage_member(
            self.state, "S9", result, ObservationId("obs_01"), self.run_dir
        )
        self.assertEqual(member.status, "error")
        self.assertIsNotNone(member.records_path)
        error = json.loads((self.run_dir / str(member.records_path)).read_text())
        self.assertIn("S9", error["error"])

    def test_unknown_kpi_cell_gives_a_member_error(self) -> None:
        indicators = ("prb_utilization", "capacity")
        result = self.client.call(
            "kpi.query",
            {"cells": ["D0"], "window": "pre_outage", "indicators": list(indicators)},
            30.0,
        )
        member = kpi_member(
            "D0", indicators, result, ObservationId("obs_02"), self.run_dir
        )
        self.assertEqual(member.status, "error")

    def test_timeout_gives_timeout(self) -> None:
        def slow(arguments: dict[str, object]) -> list[dict[str, object]]:
            time.sleep(0.2)
            return []

        declaration = ToolDeclaration("slow.tool", "sleeps", {"type": "object"}, "v")
        with LocalClient((LocalTool(declaration, slow),)) as slow_client:
            result = slow_client.call("slow.tool", {}, 0.01)
        self.assertIsInstance(result, ToolTimeout)
        member = coverage_member(
            self.state, "S1", result, ObservationId("obs_03"), self.run_dir
        )
        self.assertEqual(member, Member("S1", "timeout", None, None))
        # The client stays usable after a timed-out call.
        self.assertEqual(len(self.rows("coverage.query", S1_CALL)), 35)

    def test_unknown_tool_is_a_failure(self) -> None:
        result = self.client.call("no.such.tool", {}, 1.0)
        self.assertEqual(result, ToolFailure("unknown tool 'no.such.tool'"))

    def test_s1_observation_is_ok_with_partial_missing(self) -> None:
        result = self.client.call("coverage.query", S1_CALL, 30.0)
        obs_id = ObservationId("obs_01")
        member = coverage_member(self.state, "S1", result, obs_id, self.run_dir)
        observation = record_observation(
            obs_id,
            "coverage.query",
            {"areas": ("S1",), "epoch": "pre_outage"},
            (member,),
            5,
            "test-version",
            self.run_dir,
        )
        self.assertEqual(observation.status, "ok")
        self.assertEqual(len(observation.members), 1)
        self.assertEqual(member.result_status, "partial_missing")
        written = read_observation(self.run_dir / "observations/obs_01_S1.json")
        recorded = read_observation(FIXTURES / "obs_01.json")
        self.assertEqual(written, replace(recorded, id=written.id))
        self.assertTrue((self.run_dir / "observations/obs_01.json").exists())

    def test_a_member_without_rows_is_all_missing(self) -> None:
        member = coverage_member(
            self.state, "S1", Rows(()), ObservationId("obs_04"), self.run_dir
        )
        self.assertEqual(
            (member.status, member.result_status), ("missing", "all_missing")
        )
        self.assertEqual(observation_status((member,)), "missing")
        written = read_observation(self.run_dir / str(member.records_path))
        self.assertEqual(len(written.records), 36)
        self.assertEqual({record.status for record in written.records}, {"missing"})

    def test_absent_rows_are_missing_and_extra_rows_break_the_contract(self) -> None:
        result = self.client.call("coverage.query", S1_CALL, 30.0)
        assert isinstance(result, Rows)
        dropped = result.rows[0]
        member = coverage_member(
            self.state,
            "S1",
            Rows(result.rows[1:]),
            ObservationId("obs_05"),
            self.run_dir,
        )
        written = read_observation(self.run_dir / str(member.records_path))
        absent = [r for r in written.records if r.grid_id == dropped["grid_id"]]
        self.assertEqual(absent[0].status, "missing")
        self.assertEqual(absent[0].cells, ())
        for rows in (
            (*result.rows, result.rows[0]),
            (*result.rows, {**result.rows[0], "grid_id": "G_r39_c59"}),
        ):
            with self.assertRaises(ValueError):
                coverage_member(
                    self.state, "S1", Rows(rows), ObservationId("obs_06"), self.run_dir
                )

    def test_observation_status_is_the_worst_member(self) -> None:
        members = (
            Member("S1", "ok", "complete", "a"),
            Member("S2", "error", None, "b"),
            Member("S3", "timeout", None, None),
        )
        self.assertEqual(observation_status(members), "timeout")
        self.assertEqual(observation_status(members[:2]), "error")


if __name__ == "__main__":
    unittest.main()
