"""The transcript (append-only) context method: it changes only what the model reads."""

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from support import DATASET, SCRIPTS, AlwaysAgree, config

from outage_poc.data_tools import synthetic_client
from outage_poc.loop import run as run_state_context
from outage_poc.model import ScriptedModel
from outage_poc.models import CellId, Observation, TaskInput
from outage_poc.persistence import read_json, read_step
from outage_poc.transcript import (
    COMPACTION_INSTRUCTIONS,
    Message,
    Round,
    RoundResult,
    Transcript,
    TranscriptConfig,
    append,
    estimate_tokens,
    maybe_compact,
    tool_output,
    truncate_middle,
)
from outage_poc.transcript_loop import run as run_transcript_context
from outage_poc.transcript_model import HeadSummarizer, ScriptedTranscriptModel

TASK = TaskInput(CellId("D0"), DATASET.task.outage_time, DATASET.task.objective)
RECORDED = SCRIPTS / "recorded.txt"
COMPLETE = SCRIPTS / "complete.txt"
FAULTS = SCRIPTS / "faults.txt"


class CountingSummarizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return "counting summarizer"

    def summarize(self, text: str) -> str:
        self.calls.append(text)
        return f"summary {len(self.calls)}"


def _transcript(n_rounds: int, size: int) -> Transcript:
    rounds = tuple(Round(i, f"reply {i}", "x" * size) for i in range(1, n_rounds + 1))
    return Transcript("system", "opener", None, 0, rounds, 0)


class TranscriptUnitTests(unittest.TestCase):
    def test_messages_alternate_and_only_grow_at_the_end(self) -> None:
        transcript = _transcript(2, 10)
        roles = [m.role for m in transcript.messages()]
        self.assertEqual(
            roles, ["system", "user", "assistant", "user", "assistant", "user"]
        )
        longer = append(transcript, 3, "reply 3", "out 3")
        self.assertEqual(longer.messages()[:6], transcript.messages())
        with self.assertRaises(ValueError):
            append(transcript, 5, "skipped", "out")

    def test_truncation_keeps_head_and_tail_and_reports_omitted_bytes(self) -> None:
        text = "A" * 6000 + "B" * 6000
        cut = truncate_middle(text, 1000)
        self.assertTrue(cut.startswith("A" * 500))
        self.assertTrue(cut.endswith("B" * 500))
        self.assertIn("11000 of 12000 bytes omitted", cut)
        self.assertEqual(truncate_middle("short", 1000), "short")

    def test_compaction_replaces_older_rounds_and_keeps_recent_verbatim(self) -> None:
        transcript = _transcript(6, 4000)  # 6 * 1000 tokens of tool output
        summarizer = CountingSummarizer()
        settings = TranscriptConfig(
            output_cap_bytes=10_000, compact_threshold_tokens=3000, keep_recent_rounds=2
        )
        compacted, source = maybe_compact(transcript, settings, summarizer)
        self.assertIsNotNone(source)
        self.assertEqual(compacted.summary, "summary 1")
        self.assertEqual(compacted.summary_through, 4)
        self.assertEqual([r.index for r in compacted.rounds], [5, 6])
        self.assertEqual(compacted.compactions, 1)
        self.assertIn("Round 4", summarizer.calls[0])
        self.assertNotIn("Round 5", summarizer.calls[0])
        opener = compacted.messages()[1].content
        self.assertIn("Summary of rounds 1 to 4", opener)
        self.assertIn("summary 1", opener)
        # Below the threshold nothing happens; above it with few rounds nothing happens.
        same, none = maybe_compact(_transcript(2, 10), settings, summarizer)
        self.assertIsNone(none)
        self.assertEqual(same.compactions, 0)
        self.assertIn("400 words", COMPACTION_INSTRUCTIONS)

    def test_tool_output_reports_errors_refusals_and_concerns(self) -> None:
        settings = TranscriptConfig()
        with TemporaryDirectory() as directory:
            result = RoundResult(
                "reply", None, "decision rejected (x): why", "doubt", ("rule a",)
            )
            text = tool_output(result, Path(directory), settings)
        self.assertIn("error: decision rejected (x): why", text)
        self.assertIn("finish refused; unmet completion rules:\n- rule a", text)
        self.assertIn("reviewer concern (advisory; may be wrong): doubt", text)
        with self.assertRaises(ValueError):
            tool_output(RoundResult("reply", None, None, None, ()), Path("."), settings)

    def test_estimate_is_characters_over_four(self) -> None:
        self.assertEqual(estimate_tokens((Message("user", "a" * 400),)), 100)


class TranscriptRunTests(unittest.TestCase):
    """The scripted case under both methods: same harness outcome, different model input."""

    def run_both(self, script: Path, name: str, **changes: object) -> tuple[Path, Path]:
        base = Path(self.directory.name) / name
        run_config = config(**changes)
        run_state_context(
            run_config,
            TASK,
            ScriptedModel(script),
            AlwaysAgree(),
            synthetic_client(),
            base / "state",
            "scripted_model",
        )
        run_transcript_context(
            run_config,
            TranscriptConfig(),
            TASK,
            ScriptedTranscriptModel(script),
            HeadSummarizer(2000),
            AlwaysAgree(),
            synthetic_client(),
            base / "transcript",
            "scripted_model",
        )
        return base / "state", base / "transcript"

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_complete_script_gives_identical_states_and_observations(self) -> None:
        state_dir, transcript_dir = self.run_both(
            COMPLETE, "complete", query_budget_locations=2400
        )
        for run_dir in (state_dir, transcript_dir):
            run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["end_reason"], "complete")
        state_steps = sorted((state_dir / "steps").glob("step_*.json"))
        transcript_steps = sorted((transcript_dir / "steps").glob("step_*.json"))
        self.assertEqual(len(state_steps), len(transcript_steps))
        for left, right in zip(state_steps, transcript_steps, strict=True):
            a, b = read_step(left), read_step(right)
            self.assertEqual(a.state_after, b.state_after, left.name)
            self.assertEqual(a.decision, b.decision, left.name)
            self.assertEqual(a.outcome, b.outcome, left.name)
            if a.observation is not None:
                self.assertIsNotNone(b.observation)
        for left in sorted((state_dir / "observations").glob("obs_*_*.json")):
            right = transcript_dir / "observations" / left.name
            self.assertEqual(
                json.loads(left.read_text()), json.loads(right.read_text()), left.name
            )
        # What the model read differs: the transcript is a chat with raw rows.
        first = (transcript_dir / "inputs" / "round_01.txt").read_text(encoding="utf-8")
        self.assertIn("[system]", first)
        self.assertIn("[user]", first)
        self.assertNotIn("Investigation progress:", first)
        second = (transcript_dir / "inputs" / "round_02.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("[assistant]\naction: coverage.query", second)
        self.assertIn("coverage rows", second)
        self.assertIn('"grid_id"', second)
        state_second = (state_dir / "inputs" / "round_02.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Investigation progress:", state_second)
        self.assertNotIn('"grid_id"', state_second)
        # The transcript grows; the state rendering does not grow with rounds.
        transcript_sizes = [
            len(p.read_text(encoding="utf-8"))
            for p in sorted((transcript_dir / "inputs").glob("round_*.txt"))
        ]
        self.assertEqual(transcript_sizes, sorted(transcript_sizes))
        self.assertGreater(transcript_sizes[-1], transcript_sizes[0] * 2)
        messages = json.loads(
            (transcript_dir / "transcript" / "round_02.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [m["role"] for m in messages], ["system", "user", "assistant", "user"]
        )
        self.assertTrue((transcript_dir / "transcript" / "final.json").exists())

    def test_faults_reach_the_model_as_errors_in_the_transcript(self) -> None:
        _, transcript_dir = self.run_both(FAULTS, "faults", rejection_cap=6)
        run = json.loads((transcript_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["end_reason"], "repeated_query")
        inputs = sorted((transcript_dir / "inputs").glob("round_*.txt"))
        texts = [p.read_text(encoding="utf-8") for p in inputs]
        self.assertTrue(any("error: your reply did not parse" in t for t in texts))
        self.assertTrue(any("error: decision rejected (" in t for t in texts))

    def test_compaction_runs_in_a_long_run_and_is_recorded(self) -> None:
        base = Path(self.directory.name) / "compact"
        run_transcript_context(
            config(step_cap=10),
            TranscriptConfig(
                output_cap_bytes=10_000,
                compact_threshold_tokens=4000,
                keep_recent_rounds=2,
            ),
            TASK,
            ScriptedTranscriptModel(RECORDED),
            HeadSummarizer(300),
            AlwaysAgree(),
            synthetic_client(),
            base,
            "scripted_model",
        )
        summary = (base / "transcript" / "summary.txt").read_text(encoding="utf-8")
        self.assertIn("compactions ", summary)
        lines = [
            line for line in summary.splitlines() if line.startswith("compactions")
        ]
        count = int(lines[0].split()[1])
        self.assertGreater(count, 0)
        files = sorted((base / "compactions").glob("before_round_*.txt"))
        self.assertEqual(len(files), count)
        self.assertIn(
            "[deterministic head summary]", files[0].read_text(encoding="utf-8")
        )
        # After a compaction the message list is shorter than the round count implies.
        last = json.loads(
            (base / "transcript" / "final.json").read_text(encoding="utf-8")
        )
        self.assertIn("Summary of rounds 1 to", last[1]["content"])

    def test_observation_text_is_truncated_to_the_byte_cap(self) -> None:
        _, transcript_dir = self.run_both(RECORDED, "cap", step_cap=10)
        obs = read_json(Observation, transcript_dir / "observations" / "obs_03.json")
        self.assertEqual(obs.action, "coverage.query")
        third = (transcript_dir / "inputs" / "round_04.txt").read_text(encoding="utf-8")
        self.assertIn("bytes omitted", third)
        settings = TranscriptConfig()
        self.assertEqual(replace(settings, output_cap_bytes=1).output_cap_bytes, 1)


if __name__ == "__main__":
    unittest.main()
