"""Behavioral tests for evidence isolation, geometry, snapshots and synthetic load."""

import json
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from support import DATASET, config, initial_state, query, registry

from outage_poc.context import render_context
from outage_poc.geometry import query_boundary
from outage_poc.init import resolve_area
from outage_poc.models import (
    AreaId,
    CellId,
    CoverageObservation,
    CoverageRecord,
    ObservationId,
    Signal,
    State,
)
from outage_poc.persistence import load_observations, read_observation, write_json
from outage_poc.state import (
    apply_coverage,
    apply_impact,
    apply_kpi,
    estimate_impact,
    load_parameters,
    records_from_state,
    summary_for,
)
from outage_poc.synthetic import query_coverage

REGISTRY = registry()
CONFIG = config()
S2 = AreaId("S2")
S1 = AreaId("S1")
STUDY = AreaId("Study_area")


def context(state: State) -> str:
    return render_context(state, REGISTRY, CONFIG, ()).text


class InvestigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = DATASET
        self.observations: dict[ObservationId, CoverageObservation] = {}
        self.initial = initial_state()

    def query(self, state: State, area_id: str, observation_id: str) -> State:
        return query(self.dataset, state, area_id, observation_id, self.observations)

    def test_s2_required_counts_come_from_returned_grid_records(self) -> None:
        state = self.initial
        for area_id in ("S1", "H1_buffer", "H2_buffer"):
            state = self.query(state, area_id, area_id)
        state = self.query(state, "S2_roadside", "roadside")
        summary = summary_for(state, S2)
        observation = self.observations[ObservationId("roadside")]
        target_records = tuple(
            record
            for record in observation.records
            if any(signal.cell_id == state.task.down_cell_id for signal in record.cells)
        )
        rsrps = tuple(
            signal.rsrp_dbm
            for record in target_records
            for signal in record.cells
            if signal.cell_id == state.task.down_cell_id
        )
        self.assertEqual(len(summary.total_ids), 200)
        self.assertEqual(len(observation.records), 40)
        self.assertEqual(len(summary.queried_ids), len(observation.records))
        self.assertEqual(len(summary.valid_ids), 40)
        self.assertEqual(len(summary.missing_ids), 0)
        self.assertEqual(len(summary.unqueried_ids), 160)
        self.assertEqual(len(target_records), 20)
        self.assertEqual(set(summary.target_ids), {r.grid_id for r in target_records})
        self.assertEqual(summary.target_rsrp_min_dbm, min(rsrps))
        self.assertEqual(summary.target_rsrp_max_dbm, max(rsrps))
        self.assertEqual((min(rsrps), max(rsrps)), (-111.0, -104.0))
        self.assertEqual(len(summary.boundary_ids), 8)
        self.assertEqual(len(summary.boundary_target_ids), 4)
        for evidence in state.evidence:
            linked = self.observations[evidence.observation_id]
            self.assertIn(evidence.grid_id, {r.grid_id for r in linked.records})

    def test_unqueried_coverage_cannot_change_state_or_context(self) -> None:
        hidden_ids = set(
            resolve_area(self.initial.grid, self.initial.areas, "S2_remaining").grid_ids
        )
        changed_records = tuple(
            CoverageRecord(
                record.grid_id, "valid", (Signal(CellId("D0"), -45.0, -8.0),), 1.0
            )
            if record.grid_id in hidden_ids
            else record
            for record in self.dataset.records
        )
        changed_dataset = replace(self.dataset, records=changed_records)
        self.assertEqual(self.initial, initial_state(changed_dataset))
        state = self.query(self.initial, "S2_roadside", "roadside")
        changed_observations: dict[ObservationId, CoverageObservation] = {}
        changed_state = query(
            changed_dataset,
            initial_state(changed_dataset),
            "S2_roadside",
            "roadside",
            changed_observations,
        )
        self.assertEqual(state, changed_state)
        self.assertEqual(context(state), context(changed_state))
        self.assertFalse(hidden_ids & {e.grid_id for e in state.evidence})
        self.assertFalse(hidden_ids & set(summary_for(state, S2).target_ids))
        revealed = query(
            changed_dataset,
            changed_state,
            "S2_remaining",
            "interior",
            changed_observations,
        )
        self.assertEqual(summary_for(revealed, S2).target_rsrp_max_dbm, -45.0)
        self.assertEqual(len(summary_for(revealed, S2).unqueried_ids), 0)

    def test_repeated_and_overlapping_queries_use_unique_grid_locations(self) -> None:
        first = self.query(self.initial, "S2_roadside", "first")
        repeated = self.query(first, "S2_roadside", "repeat")
        self.assertEqual(len(summary_for(repeated, S2).queried_ids), 40)
        self.assertEqual(len(repeated.evidence), 40)
        self.assertEqual(len(repeated.observations), 2)
        overlapped = self.query(repeated, "S2", "whole")
        self.assertEqual(len(summary_for(overlapped, S2).queried_ids), 200)
        self.assertEqual(len(overlapped.evidence), 200)
        self.assertEqual(len({e.grid_id for e in overlapped.evidence}), 200)

    def test_missing_no_coverage_and_other_cells_only_are_distinct(self) -> None:
        state = self.query(self.initial, "Study_area", "all")
        summary = summary_for(state, STUDY)
        records = self.observations[ObservationId("all")].records
        missing_ids = {r.grid_id for r in records if r.status == "missing"}
        empty_ids = {r.grid_id for r in records if r.status == "valid" and not r.cells}
        other_ids = {
            r.grid_id
            for r in records
            if r.status == "valid"
            and r.cells
            and all(s.cell_id != "D0" for s in r.cells)
        }
        self.assertTrue(missing_ids)
        self.assertTrue(empty_ids)
        self.assertTrue(other_ids)
        self.assertEqual(set(summary.missing_ids), missing_ids)
        self.assertEqual(set(summary.no_coverage_ids), empty_ids)
        self.assertEqual(set(summary.other_cells_only_ids), other_ids)
        self.assertFalse(missing_ids & set(summary.valid_ids))
        self.assertFalse(empty_ids & other_ids)

    def test_boundary_uses_orthogonal_geometry_not_signal_values(self) -> None:
        addresses = {(p.column, p.row): p.id for p in self.dataset.grid}
        self.assertEqual(
            query_boundary({addresses[(0, 0)]}, {addresses[(1, 1)]}, self.dataset.grid),
            (),
        )
        grid, areas = self.initial.grid, self.initial.areas
        queried = set(resolve_area(grid, areas, "S2_roadside").grid_ids)
        unqueried = set(resolve_area(grid, areas, "S2_remaining").grid_ids)
        highest_queried_row = max(p.row for p in self.dataset.grid if p.id in queried)
        expected_boundary = {
            p.id
            for p in self.dataset.grid
            if p.id in queried and p.row == highest_queried_row
        }
        self.assertEqual(len(expected_boundary), 8)
        self.assertEqual(
            set(query_boundary(queried, unqueried, self.dataset.grid)),
            expected_boundary,
        )
        state = self.query(self.initial, "S2_roadside", "original")
        original = self.observations[ObservationId("original")]
        altered_observation = replace(
            original,
            id=ObservationId("altered"),
            records=tuple(
                replace(
                    record,
                    cells=(Signal(CellId("B1"), -85.0, -10.0),),
                    down_cell_traffic_mbps=0.0,
                )
                for record in original.records
            ),
        )
        altered = apply_coverage(
            self.initial,
            ((altered_observation, "observations/altered.json"),),
            "state_altered",
            {altered_observation.id: altered_observation},
        )
        self.assertEqual(
            summary_for(state, S2).boundary_ids,
            summary_for(altered, S2).boundary_ids,
        )
        self.assertEqual(len(summary_for(altered, S2).boundary_target_ids), 0)
        interior = self.query(state, "S2_remaining", "interior")
        self.assertEqual(summary_for(interior, S2).boundary_ids, ())

    def test_incomplete_tool_result_is_rejected_not_assumed_uncovered(self) -> None:
        grid, areas = self.initial.grid, self.initial.areas
        observation = query_coverage(
            self.dataset,
            resolve_area(grid, areas, "S2_roadside"),
            ObservationId("incomplete"),
        )
        incomplete = replace(observation, records=observation.records[:-1])
        with self.assertRaises(ValueError):
            apply_coverage(
                self.initial,
                ((incomplete, "observations/incomplete.json"),),
                "invalid_state",
                {incomplete.id: incomplete},
            )
        with self.assertRaises(ValueError):
            resolve_area(grid, areas, "nonexistent_region")

    def test_state_resolves_saved_original_query_records(self) -> None:
        observation = query_coverage(
            self.dataset,
            resolve_area(self.initial.grid, self.initial.areas, "S2_remaining"),
            ObservationId("persisted"),
        )
        relative_path = "observations/persisted.json"
        with TemporaryDirectory(
            prefix="synthetic-observation-", dir=Path(__file__).parent
        ) as temporary:
            output = Path(temporary)
            write_json(output / relative_path, observation)
            decoded = read_observation(output / relative_path)
            self.assertEqual(decoded, observation)
            state = apply_coverage(
                self.initial,
                ((decoded, relative_path),),
                "state_persisted",
                {decoded.id: decoded},
            )
            resolved = records_from_state(state, load_observations(state, output))
            self.assertEqual(
                resolved, {record.grid_id: record for record in observation.records}
            )

    def test_later_updates_do_not_change_old_snapshot(self) -> None:
        first = self.query(self.initial, "S2_roadside", "first")
        previous_json = json.dumps(asdict(first), sort_keys=True)
        previous_context = context(first)
        later = self.query(first, "S2_remaining", "later")
        self.assertEqual(json.dumps(asdict(first), sort_keys=True), previous_json)
        self.assertEqual(context(first), previous_context)
        self.assertEqual(len(summary_for(first, S2).unqueried_ids), 160)
        self.assertEqual(len(summary_for(later, S2).unqueried_ids), 0)

    def test_context_counts_match_state_and_preserve_other_regions(self) -> None:
        state = self.query(self.initial, "S1", "s1")
        roadside = self.query(state, "S2_roadside", "roadside")
        interior = self.query(roadside, "S2_remaining", "interior")
        for snapshot in (roadside, interior):
            text = context(snapshot)
            s2 = summary_for(snapshot, S2)
            s1 = summary_for(snapshot, S1)
            self.assertIn(
                f"S2 contains {len(s2.total_ids)} analysis grid locations: "
                f"{len(s2.queried_ids)} queried, {len(s2.unqueried_ids)} not queried.",
                text,
            )
            self.assertIn(
                f"S2: D0 is present at {len(s2.target_ids)} "
                f"of the {len(s2.queried_ids)} queried locations.",
                text,
            )
            self.assertIn(
                f"S1: D0 is present at {len(s1.target_ids)} "
                f"of the {len(s1.queried_ids)} queried locations.",
                text,
            )
        text = context(roadside)
        self.assertIn("ranges from -111 to -104 dBm", text)
        self.assertIn("D0 is present at 4 of 8 boundary locations", text)
        self.assertIn("S2_remaining", text)
        self.assertIn("S2_roadside", text)
        self.assertIn("unknown", text.lower())
        for area in roadside.areas:
            parameters = resolve_area(roadside.grid, roadside.areas, area.id)
            self.assertEqual(parameters.grid_ids, area.grid_ids)
            self.assertEqual(parameters.geometry, area.geometry)

    def test_state_keeps_every_cell_s_coverage_per_area(self) -> None:
        state = self.query(self.initial, "S1", "s1")
        s1 = summary_for(state, S1)
        by_cell = {cell.cell_id: cell for cell in s1.cells}
        self.assertEqual(sorted(by_cell), ["B1", "D0"])
        b1 = by_cell[CellId("B1")]
        self.assertEqual(
            (len(b1.present_ids), len(b1.strongest_ids), len(b1.with_down_cell_ids)),
            (29, 7, 29),
        )
        self.assertEqual((b1.rsrp_min_dbm, b1.rsrp_max_dbm), (-91.79, -82.25))
        d0 = by_cell[CellId("D0")]
        self.assertEqual((len(d0.present_ids), len(d0.strongest_ids)), (33, 26))
        self.assertEqual(d0.with_down_cell_ids, ())
        self.assertEqual(set(d0.present_ids), set(s1.target_ids))
        # Every strongest location belongs to exactly one cell.
        strongest = [g for cell in s1.cells for g in cell.strongest_ids]
        self.assertEqual(len(strongest), len(set(strongest)))
        self.assertEqual(set(strongest), set(s1.valid_covered_ids))
        text = context(state)
        self.assertIn(
            "B1 is present at 29 of the 35 valid locations, strongest at 7, "
            "together with D0 at 29; RSRP -91.79 to -82.25 dBm.",
            text,
        )
        self.assertIn("D0 is the strongest cell at 26 of these 33 locations.", text)
        self.assertIn(
            "- B1: present at 29 queried locations, together with D0 at 29", text
        )

    def test_load_uses_observed_target_traffic_and_excludes_down_cell(self) -> None:
        state = self.query(self.initial, "S1", "s1")
        state = self.query(state, "S2_roadside", "roadside")
        state = apply_kpi(state, self.dataset.baseline_kpis, "state_kpi")
        parameters = load_parameters(STUDY, -112.0, -16.0)
        impact = estimate_impact(state, self.observations, parameters)
        summary = summary_for(state, STUDY)
        self.assertEqual(impact.target_location_count, len(summary.target_ids))
        self.assertEqual(set(impact.excluded_unqueried_ids), set(summary.unqueried_ids))
        self.assertEqual(set(impact.excluded_missing_ids), set(summary.missing_ids))
        self.assertTrue(impact.excluded_unqueried_ids)
        self.assertTrue(impact.assignments)
        self.assertNotIn("D0", {a.backup_cell_id for a in impact.assignments})
        self.assertEqual(
            {a.grid_id for a in impact.assignments}, set(summary.target_ids)
        )
        self.assertAlmostEqual(
            impact.total_target_traffic_mbps,
            sum(a.traffic_mbps for a in impact.assignments),
        )
        self.assertAlmostEqual(
            impact.total_target_traffic_mbps,
            impact.unserved_traffic_mbps
            + sum(load.transferred_mbps for load in impact.backup_loads),
        )
        for load in impact.backup_loads:
            self.assertAlmostEqual(
                load.location_share,
                load.assigned_locations / impact.target_location_count,
            )
            self.assertAlmostEqual(
                load.traffic_share,
                load.transferred_mbps / impact.total_target_traffic_mbps,
            )
            self.assertAlmostEqual(
                load.estimated_prb_percent,
                load.baseline_prb_percent
                + 100.0 * load.transferred_mbps / load.capacity_mbps,
            )
        self.assertTrue(
            any(
                abs(load.location_share - load.traffic_share) > 1e-8
                for load in impact.backup_loads
            )
        )
        after = apply_impact(state, impact, "with_impact", self.observations)
        self.assertIsNone(state.impact)
        self.assertEqual(after.impact, impact)
        for invalid_impact in (
            replace(impact, target_location_count=999),
            replace(impact, assignments=(*impact.assignments, impact.assignments[0])),
        ):
            with self.assertRaises(ValueError):
                apply_impact(state, invalid_impact, "invalid_impact", self.observations)


if __name__ == "__main__":
    unittest.main()
