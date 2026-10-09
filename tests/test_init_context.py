"""Initialization against the recorded State 0, the land use, and the context builder."""

import json
import re
import unittest
from collections import Counter
from dataclasses import asdict
from typing import cast

from support import (
    DATASET,
    FIXTURES,
    NEW_AREAS,
    client,
    config,
    initial_state,
    query,
    registry,
)

from outage_poc.checks import key_areas
from outage_poc.context import SKILL, render_context
from outage_poc.decision import DECISION_FORMAT
from outage_poc.init import derive_areas, derive_relations, initialize
from outage_poc.models import (
    CellId,
    CoverageObservation,
    Note,
    ObservationId,
    StepDigest,
    TaskInput,
)
from outage_poc.state import apply_note

CELL_SITES = {"D0", "B1", "B2", "B3"}
# Two State 0 sentences changed on purpose: the cell sites left the geography
# (backup cells are not known at initialization), and a stopping rule now exists.
OLD_SUFFICIENCY = (
    "Investigation sufficiency has not been assessed; no stopping rule is implemented."
)
NEW_SUFFICIENCY = (
    "Investigation sufficiency is unknown until a finish passes the completion checks."
)
REPLY_LINE = (
    "Reply with your next decision in the three-line decision format of the skill.\n"
)


def _json(value: object) -> object:
    return json.loads(json.dumps(value))


def _recorded_state_00() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((FIXTURES / "state_00.json").read_text(encoding="utf-8")),
    )


def _items(value: object) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], value)


def _area_blocks(text: str, section: str) -> dict[str, list[str]]:
    """The lines of one section grouped by area: an entry line and its indented lines."""
    lines = text.splitlines()
    blocks: dict[str, list[str]] = {}
    current: list[str] = []
    for line in lines[lines.index(section) + 1 :]:
        if not line:
            break
        if line.startswith("- "):
            area = line[2:].split(" ", 1)[0].rstrip(":")
            current = blocks.setdefault(area, [])
        if line.startswith(("- ", "  ")):
            current.append(line)
    return blocks


class InitializationTests(unittest.TestCase):
    def test_initialize_keeps_the_recorded_state_00_and_adds_the_land_use(
        self,
    ) -> None:
        task = TaskInput(CellId("D0"), DATASET.task.outage_time, DATASET.task.objective)
        state = initialize(task, client(), config())
        recorded = _recorded_state_00()
        new = cast(dict[str, object], _json(asdict(state)))
        self.assertEqual(
            set(new), set(recorded) | {"kpis", "notes", "cells_seen", "inspection"}
        )
        self.assertEqual(
            (new["kpis"], new["notes"], new["cells_seen"], new["inspection"]),
            ([], [], ["D0"], None),
        )
        for name in (
            "id",
            "source",
            "coordinate_system",
            "grid_spacing_m",
            "grid",
            "observations",
            "evidence",
            "impact",
        ):
            self.assertEqual(new[name], recorded[name], name)
        task_fields = cast(dict[str, object], new["task"])
        self.assertEqual(
            (
                task_fields.pop("site_x_m"),
                task_fields.pop("site_y_m"),
                task_fields.pop("coverage_epoch"),
            ),
            (1000.0, 1300.0, "pre_outage"),
        )
        self.assertEqual(task_fields, recorded["task"])
        # The prototype's eleven areas and their summaries are unchanged.
        for name, key in (("areas", "id"), ("regions", "area_id")):
            kept = [item for item in _items(new[name]) if item[key] not in NEW_AREAS]
            if name == "regions":
                # The per-cell coverage block is new; before any query it is empty.
                self.assertTrue(all(item.pop("cells") == [] for item in kept))
            self.assertEqual(kept, recorded[name], name)
        old_geography = [
            item for item in _items(recorded["geography"]) if item["kind"] != "cell"
        ]
        self.assertEqual(
            [item for item in _items(new["geography"]) if item["id"] not in NEW_AREAS],
            old_geography,
        )
        self.assertEqual(
            [
                item
                for item in _items(new["relations"])
                if item["object_id"] not in NEW_AREAS
            ],
            [
                item
                for item in _items(recorded["relations"])
                if item["object_id"] not in CELL_SITES
            ],
        )
        unknowns = cast(list[str], new["unknowns"])
        self.assertEqual(
            [line for line in unknowns if line.split(":")[0] not in NEW_AREAS],
            [
                NEW_SUFFICIENCY if line == OLD_SUFFICIENCY else line
                for line in cast(list[str], recorded["unknowns"])
            ],
        )

    def test_moved_derivations_keep_their_output(self) -> None:
        recorded = _recorded_state_00()
        areas = derive_areas(DATASET.grid, DATASET.geography, DATASET.grid_spacing_m)
        self.assertEqual(len(areas), 11 + len(NEW_AREAS))
        self.assertEqual(
            _json([asdict(area) for area in areas if area.id not in NEW_AREAS]),
            recorded["areas"],
        )
        relations = derive_relations(DATASET.geography)
        self.assertEqual(
            _json(
                [asdict(item) for item in relations if item.object_id not in NEW_AREAS]
            ),
            recorded["relations"],
        )

    def test_settlements_and_land_use_tile_the_study_area(self) -> None:
        state = initial_state()
        tiles = [
            area
            for area in state.areas
            if area.parent_id == "Study_area" and area.geometry.kind == "polygon"
        ]
        counts = Counter(grid_id for area in tiles for grid_id in area.grid_ids)
        self.assertEqual(set(counts), {point.id for point in state.grid})
        self.assertEqual(set(counts.values()), {1})
        self.assertEqual(len(key_areas(state)), 15)
        self.assertNotIn("S2_roadside", key_areas(state))

    def test_a_road_without_a_declared_width_is_an_error(self) -> None:
        with self.assertRaises(ValueError) as raised:
            derive_areas(DATASET.grid, DATASET.geography, 100.0, {"H1": 300.0})
        self.assertIn("H2", str(raised.exception))

    def test_unknown_down_cell_stops_initialization(self) -> None:
        task = TaskInput(CellId("D9"), DATASET.task.outage_time, DATASET.task.objective)
        with self.assertRaises(ValueError) as raised:
            initialize(task, client(), config())
        self.assertIn("D9", str(raised.exception))


class ContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = registry()
        observations: dict[ObservationId, CoverageObservation] = {}
        state = initial_state()
        for area_id in ("S1", "H1_buffer", "H2_buffer", "S2_roadside"):
            state = query(DATASET, state, area_id, f"obs_{area_id}", observations)
        self.state_04 = state

    def test_state_04_lines_match_the_recorded_text(self) -> None:
        variable = render_context(self.state_04, self.registry, config(), ()).variable
        recorded = (FIXTURES / "state_04.txt").read_text(encoding="utf-8")
        recorded = recorded.replace(" in this reference.", " in this area.")
        for section in ("Investigation progress:", "Coverage observations:"):
            ours = _area_blocks(variable, section)
            theirs = _area_blocks(recorded, section)
            self.assertEqual(set(theirs), set(ours) - set(NEW_AREAS), section)
            for area, lines in theirs.items():
                # The per-cell lines are new; the recorded text predates them.
                kept = [
                    line
                    for line in ours[area]
                    if not re.match(r"  \S+ is present at \d+ of the \d+ valid", line)
                    and " is the strongest cell at " not in line
                ]
                self.assertEqual(kept, lines, f"{section} {area}")

    def test_prefix_lists_every_action_the_epoch_and_the_completion_checks(
        self,
    ) -> None:
        rendered = render_context(self.state_04, self.registry, config(), ())
        prefix = rendered.prefix
        self.assertTrue(prefix.startswith(SKILL.rstrip()))
        self.assertIn(DECISION_FORMAT, prefix)
        actions = prefix.split("Available actions:\n", 1)[1].split("\n\n")[0]
        self.assertEqual(
            [line.split("(", 1)[0] for line in actions.splitlines()],
            [
                "- cell.lookup",
                "- osm.geometry",
                "- coverage.query",
                "- kpi.query",
                "- impact.estimate",
                "- inspect_observation",
                "- finish",
            ],
        )
        self.assertIn('epoch: "pre_outage"', actions)
        self.assertIn('indicators: list of 1 to 2 of "prb_utilization"', actions)
        self.assertIn("Coverage epoch: pre_outage.", prefix)
        self.assertIn("Site of D0: x 1000 m, y 1300 m.", prefix)
        self.assertIn(
            "- key_areas: S1, S2, S3, H1_buffer, H2_buffer, F1, V1, F2, F3, F4, F5, "
            "F6, F7, F8, W1 are each fully queried",
            prefix,
        )
        self.assertIn("query budget of 1600 locations", prefix)
        self.assertNotIn("Site of", rendered.variable)

    def test_variable_part_ends_with_the_feedback_and_the_request(self) -> None:
        rendered = render_context(self.state_04, self.registry, config(), ())
        self.assertNotIn("context preview", rendered.text)
        # Maps are for people: no map file is cited as evidence.
        self.assertNotIn(".svg", rendered.text)
        self.assertTrue(
            rendered.variable.endswith(
                "Feedback from the last two rounds:\n- None.\n\n" + REPLY_LINE
            )
        )
        self.assertEqual(rendered.text, rendered.prefix + "\n\n" + rendered.variable)
        self.assertIn(
            "Actions allowed now (phase backup): coverage.query, kpi.query, "
            "inspect_observation, finish.",
            rendered.variable,
        )
        self.assertIn("Query budget: 276 of 1600 locations used", rendered.variable)
        self.assertNotIn("Recent steps:", rendered.variable)

    def test_feedback_names_the_source_and_the_decision(self) -> None:
        state = apply_note(self.state_04, Note("rejected", 4, "bad_parameter: x"))
        state = apply_note(state, Note("concern", 5, "S3 is far away"))
        history = tuple(
            StepDigest(index, None, "parse_failure", "parse failure")
            for index in range(1, 6)
        )
        variable = render_context(state, self.registry, config(), history).variable
        feedback = variable.split("Feedback from the last two rounds:\n", 1)[1]
        self.assertIn(
            "- Your decision in round 4 was rejected: bad_parameter: x", feedback
        )
        self.assertIn(
            "- The verifier questioned your decision in round 5; its reason, which "
            "may be wrong: S3 is far away",
            feedback,
        )
        later = render_context(state, self.registry, config(), (*history,) * 2)
        self.assertIn("- None.", later.variable.split("Feedback from")[1])

    def test_recent_steps_appear_only_in_condition_b(self) -> None:
        history = (StepDigest(1, None, "parse_failure", "parse failure: x"),)
        with_steps = render_context(
            self.state_04,
            self.registry,
            config(include_recent_steps=True, recent_steps=3),
            history,
        )
        self.assertIn(
            "Recent steps:\n- round 1: unparsed reply; parse failure: x",
            with_steps.variable,
        )

    def test_prefix_does_not_change_with_progress(self) -> None:
        first = render_context(initial_state(), self.registry, config(), ())
        later = render_context(self.state_04, self.registry, config(), ())
        self.assertEqual(first.prefix, later.prefix)
        self.assertNotEqual(first.variable, later.variable)


if __name__ == "__main__":
    unittest.main()
