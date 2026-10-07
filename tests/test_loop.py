"""The loop end to end on the synthetic tool library: typed ends, Steps as
checkpoints, the verifier's effects, resume, and an optional live-model run."""

import filecmp
import json
import os
import shutil
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_args

from support import (
    DATASET,
    FIXTURES,
    SCRIPTS,
    AlwaysAgree,
    ScriptedVerifier,
    client,
    config,
)

from outage_poc.checkpoint import resume
from outage_poc.data_client import LocalClient
from outage_poc.export_ui import export_case
from outage_poc.loop import run
from outage_poc.model import ChatEndpoint, ChatModel, ModelAdapter, ScriptedModel
from outage_poc.models import (
    CoverageObservation,
    EndReason,
    ExecutionSource,
    ImpactAnalysis,
    Note,
    Review,
    RunConfig,
    RunResult,
    State,
    Step,
    Trace,
    UnreadableReview,
)
from outage_poc.persistence import (
    read_json,
    read_observation,
    read_state,
    read_step,
    write_json,
)
from outage_poc.verifier import ChatVerifier, VerifierAdapter

TASK = DATASET.task
RECORDED_AREAS = ("S1", "H1_buffer", "H2_buffer", "S2_roadside", "S2_remaining", "S3")


def steps_of(run_dir: Path) -> list[Step]:
    trace = read_json(Trace, run_dir / "trace.json")
    return [read_step(run_dir / path) for path in trace.steps]


class LoopCase(unittest.TestCase):
    client: LocalClient
    temporary: TemporaryDirectory[str]
    root: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = client()
        cls.temporary = TemporaryDirectory()
        cls.root = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.temporary.cleanup()

    def run_loop(
        self,
        name: str,
        model: ModelAdapter,
        run_config: RunConfig,
        verifier: VerifierAdapter | None = None,
        source: ExecutionSource = "scripted_model",
    ) -> tuple[RunResult, Path, list[Step]]:
        run_dir = self.root / name
        result = run(
            run_config,
            TASK,
            model,
            verifier if verifier is not None else AlwaysAgree(),
            self.client,
            run_dir,
            source,
        )
        return result, run_dir, steps_of(run_dir)

    def script(self, name: str, replies: list[str]) -> ScriptedModel:
        path = self.root / f"{name}.txt"
        path.write_text("\n\n".join(replies) + "\n", encoding="utf-8")
        return ScriptedModel(path)


class LoopTests(LoopCase):
    def test_complete_script_ends_complete_and_every_step_is_a_checkpoint(
        self,
    ) -> None:
        result, run_dir, steps = self.run_loop(
            "complete", ScriptedModel(SCRIPTS / "complete.txt"), config()
        )
        self.assertEqual(result.end_reason, "complete")
        self.assertEqual(result.counters.queried_locations, 1480)
        self.assertEqual(
            [step.outcome.split(" (")[0] for step in steps],
            [
                "obs_01 ok",
                "obs_02 ok",
                "obs_03 ok",
                "obs_04 ok",
                "obs_05 ok",
                "finish accepted: completion checks passed",
            ],
        )
        initial = read_state(run_dir / "states/state_00.json")
        prefix = (run_dir / "contexts/prefix.txt").read_text(encoding="utf-8")
        before: State = initial
        for step in steps:
            # The Step holds the decision, the observation and both full States.
            self.assertEqual(step.state_before, before)
            self.assertEqual(step.state_after.id, f"state_{step.index:02d}")
            before = step.state_after
            self.assertEqual(step.registry_version, steps[0].registry_version)
            variable = (
                run_dir
                / (
                    "contexts/state_00.txt"
                    if step.index == 1
                    else steps[step.index - 2].context_after
                )
            ).read_text(encoding="utf-8")
            sent = (run_dir / step.context).read_text(encoding="utf-8")
            self.assertEqual(sent, prefix + "\n\n" + variable)
        self.assertEqual(
            steps[-1].query_cache, ("obs_01", "obs_02", "obs_03", "obs_04", "obs_05")
        )
        observation = steps[0].observation
        assert observation is not None
        self.assertEqual(
            [member.member_id for member in observation.members],
            ["F1", "S1", "S2", "V1"],
        )
        final = steps[-1].state_after
        self.assertIsNotNone(final.impact)
        study = next(r for r in final.regions if r.area_id == "Study_area")
        self.assertEqual(len(study.boundary_target_ids), 0)
        record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["end_reason"], "complete")
        self.assertEqual(record["verifier_model"], "test verifier: always agree")
        case = export_case(run_dir)
        self.assertEqual(case["run"]["end_reason"], "complete")
        self.assertEqual(len(case["steps"]), 6)
        self.assertEqual(len(case["states"]), 7)

    def test_recorded_decisions_reach_the_designed_refusal(self) -> None:
        result, run_dir, steps = self.run_loop(
            "recorded", ScriptedModel(SCRIPTS / "recorded.txt"), config(step_cap=10)
        )
        self.assertEqual(result.end_reason, "step_cap")
        for number, area in enumerate(RECORDED_AREAS, start=1):
            written = read_observation(
                run_dir / f"observations/obs_{number:02d}_{area}.json"
            )
            recorded = read_json(
                CoverageObservation, FIXTURES / f"obs_{number:02d}.json"
            )
            self.assertEqual(written, replace(recorded, id=written.id), area)
        self.assertEqual(steps[6].outcome, "rejected: gap_contradicted")
        impact = read_json(
            ImpactAnalysis, run_dir / "observations/obs_09_Study_area.json"
        )
        self.assertEqual(impact, read_json(ImpactAnalysis, FIXTURES / "impact_08.json"))
        unmet = [
            note.text.split(":")[0]
            for note in steps[9].state_after.notes
            if note.kind == "unmet"
        ]
        self.assertEqual(unmet, ["unmet boundary", "unmet key_areas"])
        self.assertIn(
            "99 of 168 query-boundary locations",
            steps[9].state_after.notes[-2].text,
        )

    def test_faults_produce_feedback_and_end_with_the_repeated_query(self) -> None:
        result, run_dir, steps = self.run_loop(
            "faults", ScriptedModel(SCRIPTS / "faults.txt"), config(rejection_cap=6)
        )
        self.assertEqual(result.end_reason, "repeated_query")
        outcomes = [step.outcome.split(" (")[0] for step in steps]
        self.assertTrue(outcomes[0].startswith("parse failure: Line 1 must start"))
        self.assertEqual(
            outcomes[1:],
            [
                "rejected: unknown_action",
                "rejected: bad_parameter",
                "rejected: precondition_unmet",
                "obs_05 ok",
                "rejected: action_cannot_answer_gap",
                "obs_07 ok",
                "rejected: gap_contradicted",
                "obs_09 ok",
            ],
        )
        self.assertEqual((result.counters.retries, result.counters.rejections), (0, 5))
        self.assertEqual(
            [(note.kind, note.step_index) for note in steps[-1].state_after.notes],
            [
                ("parse_failure", 1),
                ("rejected", 2),
                ("rejected", 3),
                ("rejected", 4),
                ("rejected", 6),
                ("rejected", 8),
            ],
        )
        self.assertIsNone(steps[1].observation)
        self.assertEqual(steps[1].review, "not_run")
        third = (run_dir / "inputs/round_03.txt").read_text(encoding="utf-8")
        feedback = third.split("Feedback from the last two rounds:\n", 1)[1]
        self.assertIn("- Your reply in round 1 did not parse: Line 1", feedback)
        self.assertIn(
            "- Your decision in round 2 (coverage.scan) was rejected: unknown_action: "
            'action "coverage.scan"',
            feedback,
        )

    def test_rejection_cap_and_retry_cap_end_the_run(self) -> None:
        result, _, steps = self.run_loop(
            "rejections", ScriptedModel(SCRIPTS / "faults.txt"), config()
        )
        self.assertEqual((result.end_reason, len(steps)), ("rejection_cap", 8))
        prose = (SCRIPTS / "faults.txt").read_text(encoding="utf-8").split("\n\n")[0]
        result, _, steps = self.run_loop(
            "retries", self.script("prose", [prose] * 3), config()
        )
        self.assertEqual((result.end_reason, len(steps)), ("retry_cap", 3))

    def test_refused_finishes_reach_the_step_cap_not_a_graph_error(self) -> None:
        finish = (
            "action: finish\nparameters: {}\n"
            'gap: {"targets": [], "question": "Is the investigation complete?"}'
        )
        result, _, steps = self.run_loop(
            "step_cap", self.script("finishes", [finish] * 20), config(step_cap=20)
        )
        self.assertEqual((result.end_reason, len(steps)), ("step_cap", 20))
        self.assertTrue(
            all(step.outcome.startswith("finish refused") for step in steps)
        )

    def test_budget_that_blocks_the_boundary_ends_the_run_as_query_budget(
        self,
    ) -> None:
        """After the four recorded queries (276 locations) the cheapest key area that
        borders D0 is F5 at 26 locations; a budget of 300 leaves 24, so neither a
        finish nor a budget-refused query can lead anywhere, and the run ends."""
        replies = (SCRIPTS / "recorded.txt").read_text(encoding="utf-8").split("\n\n")
        finish = (
            "action: finish\nparameters: {}\n"
            'gap: {"targets": [], "question": "Is the investigation complete?"}'
        )
        model = self.script("blocked_finish", replies[:4] + [finish])
        result, run_dir, steps = self.run_loop(
            "blocked_finish", model, config(query_budget_locations=300)
        )
        self.assertEqual((result.end_reason, len(steps)), ("query_budget", 5))
        self.assertTrue(steps[-1].outcome.startswith("finish refused"))
        texts = [
            note.text for note in steps[-1].state_after.notes if note.kind == "unmet"
        ]
        self.assertTrue(any("F5 is the cheapest key area" in text for text in texts))
        fifth = (run_dir / "inputs/round_05.txt").read_text(encoding="utf-8")
        self.assertIn("Budget limit reached for completion: the boundary check", fifth)
        query = (
            'action: coverage.query\nparameters: {"areas": ["F5"], "epoch": "pre_outage"}\n'
            'gap: {"targets": ["F5"], "question": "Does D0 reach F5?"}'
        )
        model = self.script("blocked_query", replies[:4] + [query])
        result, _, steps = self.run_loop(
            "blocked_query", model, config(query_budget_locations=300)
        )
        self.assertEqual((result.end_reason, len(steps)), ("query_budget", 5))
        self.assertEqual(steps[-1].outcome, "rejected: budget_exceeded")

    def test_inspection_rows_reach_the_next_context_once(self) -> None:
        replies = (SCRIPTS / "recorded.txt").read_text(encoding="utf-8").split("\n\n")
        inspect = (
            "action: inspect_observation\n"
            'parameters: {"observation": "obs_01_S1", "first_row": 30}\n'
            'gap: {"targets": ["S1"], "question": "Which cells serve the last rows of S1?"}'
        )
        model = self.script("inspect", [replies[0], inspect, replies[1]])
        result, run_dir, steps = self.run_loop("inspect", model, config(step_cap=3))
        self.assertEqual(result.end_reason, "step_cap")
        inspection = steps[1].state_after.inspection
        assert inspection is not None
        self.assertEqual((inspection.first_row, inspection.total_rows), (30, 36))
        self.assertEqual(len(inspection.records), 6)
        third = (run_dir / "inputs/round_03.txt").read_text(encoding="utf-8")
        self.assertIn("Inspected rows 30 to 35 of 36 in obs_01_S1 (area S1)", third)
        after = (run_dir / steps[2].context_after).read_text(encoding="utf-8")
        self.assertNotIn("Inspected rows", after)

    def test_verifier_concern_is_a_fact_and_unreadable_reviews_are_recorded(
        self,
    ) -> None:
        verifier = ScriptedVerifier(
            [
                Review("concern", "F1 and V1 lie far from the site."),
                UnreadableReview("agree", "the reply has 1 lines, not 2"),
            ]
            + [Review("agree", "fine")] * 4
        )
        result, run_dir, steps = self.run_loop(
            "verifier",
            ScriptedModel(SCRIPTS / "complete.txt"),
            config(),
            verifier=verifier,
        )
        self.assertEqual(result.end_reason, "complete")
        self.assertEqual((steps[0].review, steps[1].review), ("concern", "not_run"))
        self.assertIsNotNone(steps[0].observation)
        self.assertIsNotNone(steps[1].observation)
        self.assertEqual(
            steps[1].review_reason,
            "unreadable verifier reply (the reply has 1 lines, not 2): agree",
        )
        self.assertEqual(
            steps[0].state_after.notes,
            (Note("concern", 1, "F1 and V1 lie far from the site."),),
        )
        second = (run_dir / "inputs/round_02.txt").read_text(encoding="utf-8")
        self.assertIn(
            "- The verifier questioned your decision in round 1 (coverage.query); its "
            "reason, which may be wrong: F1 and V1 lie far from the site.",
            second,
        )


class ResumeTests(LoopCase):
    original: Path

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.original = cls.root / "original"
        run(
            config(),
            TASK,
            ScriptedModel(SCRIPTS / "complete.txt"),
            AlwaysAgree(),
            cls.client,
            cls.original,
            "scripted_model",
        )

    def corrected_state(self, run_dir: Path, name: str) -> Path:
        """A person's corrected State 2: here an unchanged copy of the Step's State."""
        path = self.root / f"{name}_state_02.json"
        write_json(path, read_step(run_dir / "steps/step_02.json").state_after)
        return path

    def resume_from(self, run_dir: Path, name: str) -> tuple[RunResult, Path]:
        out_dir = self.root / name
        result = resume(
            run_dir,
            2,
            self.corrected_state(run_dir, name),
            ScriptedModel(SCRIPTS / "resume.txt"),
            AlwaysAgree(),
            self.client,
            out_dir,
            "scripted_model",
        )
        return result, out_dir

    def test_resume_keeps_steps_one_and_two_and_runs_new_steps(self) -> None:
        original_steps = steps_of(self.original)
        result, out_dir = self.resume_from(self.original, "resumed")
        self.assertEqual((result.end_reason, result.counters.step), ("complete", 6))
        for index in (1, 2):
            for relative in (
                f"steps/step_{index:02d}.json",
                f"inputs/round_{index:02d}.txt",
                f"outputs/round_{index:02d}.txt",
                f"contexts/state_{index:02d}.txt",
            ):
                self.assertTrue(
                    filecmp.cmp(
                        self.original / relative, out_dir / relative, shallow=False
                    ),
                    relative,
                )
        steps = steps_of(out_dir)
        self.assertEqual(steps[:2], original_steps[:2])
        third = steps[2]
        self.assertEqual(third.execution_source, "resume")
        self.assertEqual(third.state_before.id, "state_02_corrected")
        self.assertEqual(steps[3].execution_source, "scripted_model")
        self.assertEqual(third.query_cache[:2], original_steps[1].query_cache)
        record = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
        original = json.loads((self.original / "run.json").read_text(encoding="utf-8"))
        self.assertNotEqual(record["run_id"], original["run_id"])
        self.assertTrue(record["resumed_from"].endswith("#step_02"))
        self.assertEqual(steps_of(self.original), original_steps)

    def test_version_mismatch_raises(self) -> None:
        for field, name in (("registry_version", "registry"), ("data_version", "data")):
            copy = self.root / f"tampered_{name}"
            shutil.copytree(self.original, copy)
            step = read_step(copy / "steps/step_02.json")
            write_json(copy / "steps/step_02.json", replace(step, **{field: "0" * 64}))
            with self.assertRaises(ValueError) as raised:
                self.resume_from(copy, f"refused_{name}")
            self.assertIn(
                f"{name.capitalize()} version mismatch", str(raised.exception)
            )

    def test_inconsistent_corrected_state_raises(self) -> None:
        state = read_step(self.original / "steps/step_02.json").state_after
        corrected = self.root / "inconsistent_state.json"
        write_json(corrected, replace(state, evidence=state.evidence[1:]))
        with self.assertRaises(ValueError):
            resume(
                self.original,
                2,
                corrected,
                ScriptedModel(SCRIPTS / "resume.txt"),
                AlwaysAgree(),
                self.client,
                self.root / "refused_state",
                "scripted_model",
            )


LIVE_URL = os.environ.get("OUTAGE_LLM_BASE_URL")
LIVE_MODEL = os.environ.get("OUTAGE_LLM_MODEL")


@unittest.skipUnless(
    LIVE_URL and LIVE_MODEL, "set OUTAGE_LLM_BASE_URL and OUTAGE_LLM_MODEL"
)
class LiveModelTests(LoopCase):
    def test_both_model_nodes_on_a_live_endpoint_end_with_a_typed_reason(
        self,
    ) -> None:
        assert LIVE_URL is not None and LIVE_MODEL is not None
        endpoint = ChatEndpoint(LIVE_URL, LIVE_MODEL, None, 0.0, 512, 300.0)
        result, _, steps = self.run_loop(
            "live",
            ChatModel(endpoint),
            config(step_cap=6),
            verifier=ChatVerifier(replace(endpoint, max_tokens=256)),
            source="llm",
        )
        self.assertIn(result.end_reason, get_args(EndReason))
        self.assertEqual(len(steps), result.counters.step)
        self.assertTrue(all(step.execution_source == "llm" for step in steps))


if __name__ == "__main__":
    unittest.main()
