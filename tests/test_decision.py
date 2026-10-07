"""The decision core without a model: parser, validation checks, route, completion
checks, verifier replies, and the caps."""

import unittest
from dataclasses import replace

from support import DATASET, SCRIPTS, config, initial_state, query, registry

from outage_poc import caps, checks
from outage_poc.decision import (
    DECISION_FORMAT,
    Finish,
    Query,
    parse,
    route,
    validate,
)
from outage_poc.model import read_script
from outage_poc.models import (
    Accepted,
    AreaId,
    Counters,
    CoverageObservation,
    Decision,
    Gap,
    ObservationId,
    ParseFailure,
    Rejection,
    Review,
    State,
    StepDigest,
    UnreadableReview,
)
from outage_poc.state import (
    apply_impact,
    apply_kpi,
    d0_border_count,
    estimate_impact,
    load_parameters,
)
from outage_poc.verifier import parse_review

REGISTRY = registry()
BUDGET = config().query_budget_locations
FAULTS = read_script(SCRIPTS / "faults.txt")
RECORDED = read_script(SCRIPTS / "recorded.txt")
COMPLETE = read_script(SCRIPTS / "complete.txt")


def _decision(raw: str) -> Decision:
    parsed = parse(raw)
    if isinstance(parsed, ParseFailure):
        raise AssertionError(parsed.reason)
    return parsed


def _validate(raw: str, state: State, budget: int = BUDGET) -> Accepted | Rejection:
    return validate(_decision(raw), state, REGISTRY, budget)


def _accepted(raw: str, state: State) -> Accepted:
    result = _validate(raw, state)
    if not isinstance(result, Accepted):
        raise AssertionError(result)
    return result


def _rejection(raw: str, state: State, budget: int = BUDGET) -> Rejection:
    result = _validate(raw, state, budget)
    if not isinstance(result, Rejection):
        raise AssertionError(f"Expected a rejection, got {result}")
    return result


def _kind(raw: str, state: State) -> str:
    return _rejection(raw, state).kind


class Investigation:
    """Applies accepted decisions in process, as the loop would, without MCP."""

    def __init__(self) -> None:
        self.state = initial_state()
        self.observations: dict[ObservationId, CoverageObservation] = {}
        self.rounds = 0

    def apply(self, accepted: Accepted) -> None:
        self.rounds += 1
        parameters = accepted.parameters
        match accepted.action.name:
            case "coverage.query":
                areas = parameters["areas"]
                assert isinstance(areas, tuple)
                for area in areas:
                    self.state = query(
                        DATASET,
                        self.state,
                        area,
                        f"obs_{self.rounds:02d}_{area}",
                        self.observations,
                    )
            case "kpi.query":
                cells, indicators = parameters["cells"], parameters["indicators"]
                assert isinstance(cells, tuple) and isinstance(indicators, tuple)
                records = tuple(
                    kpi
                    for kpi in DATASET.baseline_kpis
                    if kpi.cell_id in cells and kpi.indicator in indicators
                )
                self.state = apply_kpi(self.state, records, f"state_{self.rounds:02d}")
            case "impact.estimate":
                scope, rsrp, rsrq = (
                    parameters["scope"],
                    parameters["min_rsrp_dbm"],
                    parameters["min_rsrq_db"],
                )
                assert isinstance(scope, str)
                assert isinstance(rsrp, float) and isinstance(rsrq, float)
                impact = estimate_impact(
                    self.state,
                    self.observations,
                    load_parameters(AreaId(scope), rsrp, rsrq),
                )
                self.state = apply_impact(
                    self.state, impact, f"state_{self.rounds:02d}", self.observations
                )
            case "finish":
                pass
            case other:
                raise AssertionError(f"Unexpected action {other}")

    def run(self, replies: tuple[str, ...]) -> None:
        for raw in replies:
            self.apply(_accepted(raw, self.state))


def _recorded_end() -> Investigation:
    """The recorded decisions up to the impact, without round 7, which is rejected."""
    investigation = Investigation()
    investigation.run(RECORDED[:6] + RECORDED[7:9])
    return investigation


class ParserTests(unittest.TestCase):
    def test_three_labelled_lines_parse(self) -> None:
        decision = _decision(RECORDED[0])
        self.assertEqual(decision.action, "coverage.query")
        self.assertEqual(decision.parameters, {"areas": ["S1"], "epoch": "pre_outage"})
        self.assertEqual(decision.gap.targets, ("S1",))
        self.assertTrue(decision.gap.question.startswith("Which locations in S1"))
        self.assertEqual(decision.raw_text, RECORDED[0])

    def test_blank_lines_and_surrounding_space_are_ignored(self) -> None:
        spaced = "\n\n  " + RECORDED[0].replace("\n", "\n\n") + "  \n"
        self.assertEqual(
            _decision(spaced).parameters, _decision(RECORDED[0]).parameters
        )

    def test_failures_name_the_line_and_repeat_the_format(self) -> None:
        lines = RECORDED[0].splitlines()
        cases = {
            FAULTS[0]: "Line 1 must start with 'action:'",
            "\n".join(
                [lines[1], lines[0], lines[2]]
            ): "Line 1 must start with 'action:'",
            "\n".join(lines[:2]): "only 2 non-blank lines",
            "\n".join([*lines, "Thanks."]): "Line 4 is extra text",
            "\n".join([lines[0], "parameters: {areas: S1}", lines[2]]): "Line 2",
            "\n".join([lines[0], lines[1], 'gap: {"targets": []}']): "Line 3",
            "\n".join([lines[0], lines[1], 'gap: {"targets": [1], "question": "q"}']): (
                "'targets' must be a list of strings"
            ),
            "\n".join([lines[0], 'parameters: {"x": NaN}', lines[2]]): "Line 2",
        }
        for raw, expected in cases.items():
            parsed = parse(raw)
            self.assertIsInstance(parsed, ParseFailure, raw)
            assert isinstance(parsed, ParseFailure)
            self.assertIn(expected, parsed.reason)
            self.assertIn(DECISION_FORMAT, parsed.reason)

    def test_no_repair_of_labels(self) -> None:
        self.assertIsInstance(
            parse(RECORDED[0].replace("action:", "Action:")), ParseFailure
        )


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_0 = initial_state()
        observations: dict[ObservationId, CoverageObservation] = {}
        self.after_s1 = query(DATASET, self.state_0, "S1", "s1", observations)
        self.after_roadside = query(
            DATASET, self.after_s1, "S2_roadside", "roadside", observations
        )

    def test_faults_map_to_the_five_validation_kinds(self) -> None:
        self.assertIsInstance(parse(FAULTS[0]), ParseFailure)
        self.assertEqual(_kind(FAULTS[1], self.state_0), "unknown_action")
        self.assertEqual(_kind(FAULTS[2], self.state_0), "bad_parameter")
        self.assertEqual(_kind(FAULTS[3], self.state_0), "precondition_unmet")
        _accepted(FAULTS[4], self.state_0)
        self.assertEqual(_kind(FAULTS[5], self.after_s1), "action_cannot_answer_gap")
        _accepted(FAULTS[6], self.after_s1)
        self.assertEqual(_kind(FAULTS[7], self.after_roadside), "gap_contradicted")
        # S1 has missing data, so asking again is valid; the repeat guard ends the run.
        _accepted(FAULTS[8], self.after_roadside)

    def test_messages_name_the_wrong_thing_and_the_right_things(self) -> None:
        unknown = _rejection(FAULTS[1], self.state_0)
        self.assertIn("coverage.scan", unknown.message)
        self.assertIn("coverage.query", unknown.message)
        bad_area = _rejection(FAULTS[2], self.state_0)
        self.assertIn(
            'area "S4" does not exist in State; known areas: Study_area, S1',
            bad_area.message,
        )
        early = _rejection(FAULTS[3], self.state_0)
        self.assertIn("no queried location lists D0", early.message)

    def test_every_gap_except_a_finish_names_its_targets(self) -> None:
        no_targets = RECORDED[0].replace('"targets": ["S1"]', '"targets": []')
        rejection = _rejection(no_targets, self.state_0)
        self.assertEqual(rejection.kind, "bad_parameter")
        self.assertIn("names no targets", rejection.message)
        self.assertIsInstance(route(_accepted(RECORDED[9], self.after_s1)), Finish)

    def test_recorded_decisions_against_their_states(self) -> None:
        investigation = Investigation()
        investigation.run(RECORDED[:6])
        # Round 7 asks again about S2_roadside, which State already answers.
        self.assertEqual(_kind(RECORDED[6], investigation.state), "gap_contradicted")
        investigation.run(RECORDED[7:])
        self.assertIsNotNone(investigation.state.impact)

    def test_bad_parameters(self) -> None:
        state = self.after_s1
        gap = '{"targets": ["S1"], "question": "Where is D0 present?"}'
        cases = {
            '{"areas": ["S1"]}': "needs parameter 'epoch'",
            '{"areas": ["S1"], "epoch": "pre_outage", "radius_m": 5}': "no parameter 'radius_m'",
            '{"areas": "S1", "epoch": "pre_outage"}': "must be a list",
            '{"areas": ["S1", "S2", "S3", "F1", "F2"], "epoch": "pre_outage"}': "1 to 4 members",
            '{"areas": ["S1", "S1"], "epoch": "pre_outage"}': "twice",
            '{"areas": [], "epoch": "pre_outage"}': "1 to 4 members",
            '{"areas": ["S1"], "epoch": "post_outage"}': "the task's coverage epoch",
        }
        for parameters, expected in cases.items():
            raw = f"action: coverage.query\nparameters: {parameters}\ngap: {gap}"
            rejection = _rejection(raw, state)
            self.assertEqual(rejection.kind, "bad_parameter", parameters)
            self.assertIn(expected, rejection.message)
        kpi_gap = '{"targets": ["B1"], "question": "How loaded is B1?"}'
        for parameters, expected in {
            '{"cells": ["B9"], "window": "pre_outage", "indicators": ["capacity"]}': (
                'cell "B9" has not been seen'
            ),
            '{"cells": ["B1"], "window": "pre_outage", "indicators": ["rrc"]}': (
                "'rrc' is not one of"
            ),
        }.items():
            raw = f"action: kpi.query\nparameters: {parameters}\ngap: {kpi_gap}"
            self.assertIn(expected, _rejection(raw, state).message)
        unknown_target = RECORDED[0].replace('"targets": ["S1"]', '"targets": ["S7"]')
        self.assertEqual(_kind(unknown_target, state), "bad_parameter")
        text_number = RECORDED[8].replace("-112", '"-112"')
        self.assertEqual(_kind(text_number, state), "bad_parameter")

    def test_a_query_over_the_remaining_budget_is_refused_before_it_runs(
        self,
    ) -> None:
        raw = (
            'action: coverage.query\nparameters: {"areas": ["F3", "F4"], '
            '"epoch": "pre_outage"}\ngap: {"targets": ["F3", "F4"], '
            '"question": "Does D0 reach the farmland around S1?"}'
        )
        _accepted(raw, self.after_s1)
        rejection = _rejection(raw, self.after_s1, budget=300)
        self.assertEqual(rejection.kind, "budget_exceeded")
        self.assertIn(
            "would add 408 new locations (F3 304, F4 104), but only 264 of the "
            "budget of 300 locations remain",
            rejection.message,
        )

    def test_initialization_actions_are_not_allowed_in_the_loop(self) -> None:
        raw = (
            'action: cell.lookup\nparameters: {"cell_id": "D0"}\n'
            'gap: {"targets": ["S1"], "question": "Where is D0?"}'
        )
        self.assertEqual(_kind(raw, self.after_s1), "precondition_unmet")

    def test_impact_needs_both_indicators_for_every_candidate(self) -> None:
        self.assertEqual(_kind(RECORDED[8], self.after_s1), "precondition_unmet")
        prb_only = tuple(
            kpi for kpi in DATASET.baseline_kpis if kpi.indicator == "prb_utilization"
        )
        partial = apply_kpi(self.after_s1, prb_only, "state_prb")
        self.assertIn("B1 has no capacity", _rejection(RECORDED[8], partial).message)
        with_kpi = apply_kpi(self.after_s1, DATASET.baseline_kpis, "state_kpi")
        _accepted(RECORDED[8], with_kpi)
        unqueried_scope = RECORDED[8].replace("Study_area", "F2")
        self.assertEqual(_kind(unqueried_scope, with_kpi), "precondition_unmet")

    def test_kpi_gap_on_a_cell_with_both_indicators_is_contradicted(self) -> None:
        # After S1 only B1 has appeared in a record; B2 and B3 are not known yet.
        self.assertEqual(_kind(RECORDED[7], self.after_s1), "bad_parameter")
        b1_only = RECORDED[7].replace('["B1", "B2", "B3"]', '["B1"]')
        _accepted(b1_only, self.after_s1)
        with_kpi = apply_kpi(self.after_s1, DATASET.baseline_kpis, "state_kpi")
        self.assertEqual(_kind(b1_only, with_kpi), "gap_contradicted")

    def test_inspect_observation(self) -> None:
        def raw(observation: str, first_row: int, target: str) -> str:
            return (
                "action: inspect_observation\n"
                f'parameters: {{"observation": "{observation}", "first_row": {first_row}}}\n'
                f'gap: {{"targets": ["{target}"], "question": "Which cells serve S1?"}}'
            )

        _accepted(raw("s1", 0, "S1"), self.after_s1)
        self.assertIn(
            "outside s1", _rejection(raw("s1", 36, "S1"), self.after_s1).message
        )
        self.assertIn(
            "not in the evidence provenance",
            _rejection(raw("s9", 0, "S1"), self.after_s1).message,
        )
        self.assertEqual(
            _kind(raw("s1", 0, "B1"), self.after_s1), "action_cannot_answer_gap"
        )
        self.assertEqual(_kind(raw("s1", 0, "S1"), self.state_0), "bad_parameter")

    def test_route(self) -> None:
        self.assertIsInstance(route(_accepted(RECORDED[0], self.after_s1)), Query)
        finish = route(_accepted(RECORDED[9], self.after_s1))
        self.assertIsInstance(finish, Finish)
        assert isinstance(finish, Finish)
        self.assertTrue(finish.gap.question.startswith("All key areas are queried"))


class CompletionCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.finish = Finish(Gap((), "Is the investigation complete?"))

    def rules(self, state: State, finish: Finish | None = None) -> list[str]:
        return [
            unmet.rule for unmet in checks.run(state, config(), finish or self.finish)
        ]

    def test_recorded_end_state_fails_the_boundary_and_the_key_areas(self) -> None:
        state = _recorded_end().state
        unmet = checks.run(state, config(), self.finish)
        self.assertEqual([item.rule for item in unmet], ["boundary", "key_areas"])
        self.assertEqual(
            unmet[0].text,
            "unmet boundary: the down cell is present at 99 of 168 query-boundary "
            "locations (allowed share 0)",
        )
        self.assertIn(
            "F1 (240 unqueried, 23 bordering D0), V1 (247 unqueried, 0 bordering D0), F2",
            unmet[1].text,
        )

    def test_the_complete_script_passes_all_four_rules(self) -> None:
        investigation = Investigation()
        investigation.run(COMPLETE[:5])
        state = investigation.state
        finish = route(_accepted(COMPLETE[5], state))
        assert isinstance(finish, Finish)
        self.assertEqual(self.rules(state, finish), [])
        # Without F2, F8 and W1 in the finish targets the key-area rule is unmet.
        self.assertEqual(self.rules(state), ["key_areas"])
        # The program fact the reason rests on: none of their locations borders D0.
        self.assertEqual(
            [d0_border_count(state, AreaId(a)) for a in ("F2", "F8", "W1")], [0, 0, 0]
        )
        # A finish may list only key areas that still have unqueried locations.
        for target in ("S1", "B1"):
            raw = (
                "action: finish\nparameters: {}\n"
                f'gap: {{"targets": ["{target}"], "question": "done"}}'
            )
            rejection = _rejection(raw, state)
            self.assertEqual(rejection.kind, "gap_contradicted")
            self.assertIn(f"finish lists {target} as left unqueried", rejection.message)

    def test_labels_catch_a_corrupted_state(self) -> None:
        state = _recorded_end().state
        study = next(r for r in state.regions if r.area_id == "Study_area")
        broken = replace(study, missing_ids=(*study.missing_ids, study.target_ids[0]))
        corrupted = replace(
            state,
            regions=tuple(
                broken if r.area_id == "Study_area" else r for r in state.regions
            ),
        )
        self.assertIn("labels", self.rules(corrupted))

    def test_backup_load_needs_a_current_impact(self) -> None:
        stale = apply_kpi(_recorded_end().state, DATASET.baseline_kpis, "state_again")
        self.assertIsNone(stale.impact)
        self.assertIn("backup_load", self.rules(stale))


class VerifierReplyTests(unittest.TestCase):
    def test_two_labelled_lines_are_a_review(self) -> None:
        self.assertEqual(
            parse_review("outcome: concern\nreason: S1 is already queried."),
            Review("concern", "S1 is already queried."),
        )
        self.assertEqual(
            parse_review("\n outcome: agree \n\nreason: fine\n"),
            Review("agree", "fine"),
        )

    def test_other_replies_are_unreadable_not_guessed(self) -> None:
        for raw in (
            "agree\nreason: fine",
            "outcome: maybe\nreason: fine",
            "outcome: agree",
            "outcome: agree\nreason:",
            "Outcome: agree\nReason: fine",
        ):
            result = parse_review(raw)
            self.assertIsInstance(result, UnreadableReview, raw)
            assert isinstance(result, UnreadableReview)
            self.assertEqual(result.reply, raw)


class CapTests(unittest.TestCase):
    def test_hit_checks_step_cap_then_budget_then_time(self) -> None:
        run_config = config(step_cap=5, query_budget_locations=100, time_cap_s=10.0)
        self.assertIsNone(caps.hit(Counters(4, 0, 0, 100, 10.0), run_config))
        self.assertEqual(caps.hit(Counters(5, 0, 0, 101, 11.0), run_config), "step_cap")
        self.assertEqual(
            caps.hit(Counters(4, 0, 0, 101, 11.0), run_config), "query_budget"
        )
        self.assertEqual(caps.hit(Counters(4, 0, 0, 100, 11.0), run_config), "time_cap")

    def test_repeat_guard_counts_area_queries_only(self) -> None:
        def digest(index: int, raw: str) -> StepDigest:
            return StepDigest(index, _decision(raw), "accepted", "ok")

        impact = RECORDED[8]
        twice_impact = (digest(1, impact), digest(2, impact))
        self.assertFalse(caps.repeated(twice_impact, REGISTRY, config()))
        twice_query = (
            digest(1, RECORDED[0]),
            digest(2, impact),
            digest(3, RECORDED[0]),
        )
        self.assertTrue(caps.repeated(twice_query, REGISTRY, config()))
        self.assertFalse(
            caps.repeated(twice_query, REGISTRY, config(repeated_query_threshold=3))
        )
        rejected_last = (
            digest(1, RECORDED[0]),
            StepDigest(2, _decision(RECORDED[0]), "rejected", "rejected"),
        )
        self.assertFalse(caps.repeated(rejected_last, REGISTRY, config()))


if __name__ == "__main__":
    unittest.main()
