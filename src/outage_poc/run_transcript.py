"""Run an investigation with the transcript (append-only) context method.

Live:   uv run python -m outage_poc.run_transcript --output outputs/run_transcript \\
            --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b-instruct-awq \\
            --verifier-model qwen2.5-32b-instruct-awq
Replay: add --script <file> to replace the decision model with recorded replies;
        the verifier then agrees with every decision and compaction uses a
        deterministic head summary, so no model is called.

The harness is the one `outage_poc.run` uses; only what the deciding model
reads differs. Resume is not supported with this method.
"""

import argparse
import sys
from pathlib import Path

from outage_poc.data_tools import synthetic_client
from outage_poc.model import ChatEndpoint
from outage_poc.models import (
    CellId,
    ExecutionSource,
    RunConfig,
    RunResult,
    TaskInput,
)
from outage_poc.run import (
    DECISION_MAX_TOKENS,
    MODEL_TIMEOUT_S,
    REVIEW_MAX_TOKENS,
    TEMPERATURE,
)
from outage_poc.transcript import Summarizer, TranscriptConfig
from outage_poc.transcript_loop import run
from outage_poc.transcript_model import (
    ChatSummarizer,
    HeadSummarizer,
    ScriptedTranscriptModel,
    TranscriptChatModel,
    TranscriptModelAdapter,
)
from outage_poc.verifier import ChatVerifier

SUMMARY_MAX_TOKENS = 1024
HEAD_SUMMARY_CHARS = 2000


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    """The run arguments shared with `outage_poc.run`, plus the transcript settings."""
    parser.add_argument("--output", required=True, type=Path, help="New run directory")
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible /v1 URL")
    parser.add_argument("--model", required=True, help="Decision model name")
    parser.add_argument("--verifier-model", required=True, help="Verifier model name")
    parser.add_argument("--api-key-env", help="Variable that holds the API key")
    parser.add_argument("--script", type=Path, help="Replay these decisions instead")
    parser.add_argument("--maps", action="store_true", help="Write maps and index.html")
    parser.add_argument("--step-cap", type=int, default=20)
    parser.add_argument("--query-budget", type=int, default=1600)
    parser.add_argument("--time-cap", type=float, default=1800.0)
    parser.add_argument("--boundary-share", type=float, default=0.0)
    parser.add_argument("--down-cell", default="D0")
    parser.add_argument("--outage-time", default="2026-01-15T09:00:00Z")
    parser.add_argument(
        "--objective",
        default=(
            "Investigate the outage impact of cell D0 using synthetic pre-outage "
            "coverage and explicit synthetic demand."
        ),
    )
    parser.add_argument("--output-cap-bytes", type=int, default=10_000)
    parser.add_argument("--compact-threshold-tokens", type=int, default=20_000)
    parser.add_argument("--keep-recent-rounds", type=int, default=3)


def run_config(arguments: argparse.Namespace) -> RunConfig:
    return RunConfig(
        data_version=None,
        step_cap=arguments.step_cap,
        query_budget_locations=arguments.query_budget,
        time_cap_s=arguments.time_cap,
        boundary_d0_max_share=arguments.boundary_share,
        include_recent_steps=False,
        recent_steps=0,
        write_maps=arguments.maps,
    )


def transcript_config(arguments: argparse.Namespace) -> TranscriptConfig:
    return TranscriptConfig(
        output_cap_bytes=arguments.output_cap_bytes,
        compact_threshold_tokens=arguments.compact_threshold_tokens,
        keep_recent_rounds=arguments.keep_recent_rounds,
    )


def task(arguments: argparse.Namespace) -> TaskInput:
    return TaskInput(
        CellId(arguments.down_cell), arguments.outage_time, arguments.objective
    )


def endpoint(
    arguments: argparse.Namespace, model: str, max_tokens: int
) -> ChatEndpoint:
    return ChatEndpoint(
        arguments.base_url,
        model,
        arguments.api_key_env,
        TEMPERATURE,
        max_tokens,
        MODEL_TIMEOUT_S,
    )


def transcript_model(
    arguments: argparse.Namespace,
) -> tuple[TranscriptModelAdapter, Summarizer, ExecutionSource]:
    if arguments.script is not None:
        return (
            ScriptedTranscriptModel(arguments.script),
            HeadSummarizer(HEAD_SUMMARY_CHARS),
            "scripted_model",
        )
    decision = endpoint(arguments, arguments.model, DECISION_MAX_TOKENS)
    return (
        TranscriptChatModel(decision),
        ChatSummarizer(endpoint(arguments, arguments.model, SUMMARY_MAX_TOKENS)),
        "llm",
    )


def verifier(arguments: argparse.Namespace) -> ChatVerifier:
    return ChatVerifier(
        endpoint(arguments, arguments.verifier_model, REVIEW_MAX_TOKENS)
    )


def report(result: RunResult, output: Path) -> None:
    counters = result.counters
    print(f"Run {result.run_id} ended: {result.end_reason}")
    print(
        f"Rounds {counters.step}; retries {counters.retries}; rejections "
        f"{counters.rejections}; queried locations {counters.queried_locations}; "
        f"elapsed {counters.elapsed_s:.1f} s"
    )
    print(f"Trace: {output / result.trace}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_run_arguments(parser)
    arguments = parser.parse_args()
    model, summarizer, source = transcript_model(arguments)
    try:
        result = run(
            run_config(arguments),
            transcript_config(arguments),
            task(arguments),
            model,
            summarizer,
            verifier(arguments),
            synthetic_client(),
            arguments.output,
            source,
        )
    except ValueError as error:
        print(f"Run failed: {error}", file=sys.stderr)
        return 1
    report(result, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
