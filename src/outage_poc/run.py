"""Run or resume an investigation: the decision model and the verifier model on a
chat endpoint, the four data actions in the synthetic tool library.

Run:    uv run python -m outage_poc --output outputs/run_live \\
            --base-url http://127.0.0.1:8011/v1 --model qwen2.5-7b-instruct \\
            --verifier-model qwen2.5-7b-instruct
Resume: add --resume <run dir> --from-step <k> --state <corrected State JSON>
Replay: add --script <file> to replace the decision model with recorded replies.
"""

import argparse
import sys
from pathlib import Path

from outage_poc.checkpoint import resume
from outage_poc.data_tools import synthetic_client
from outage_poc.loop import run
from outage_poc.model import ChatEndpoint, ChatModel, ModelAdapter, ScriptedModel
from outage_poc.models import (
    CellId,
    ExecutionSource,
    RunConfig,
    RunResult,
    TaskInput,
)
from outage_poc.verifier import ChatVerifier

# Deterministic replies; the decision is three lines and the review two.
TEMPERATURE = 0.0
DECISION_MAX_TOKENS = 512
REVIEW_MAX_TOKENS = 256
MODEL_TIMEOUT_S = 300.0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    parser.add_argument("--recent-steps", type=int, default=0, help="0: condition A")
    parser.add_argument("--down-cell", default="D0")
    parser.add_argument("--outage-time", default="2026-01-15T09:00:00Z")
    parser.add_argument(
        "--objective",
        default=(
            "Investigate the outage impact of cell D0 using synthetic pre-outage "
            "coverage and explicit synthetic demand."
        ),
    )
    parser.add_argument("--resume", type=Path, help="Run directory to resume from")
    parser.add_argument("--from-step", type=int, help="Step to resume after")
    parser.add_argument("--state", type=Path, help="Corrected State for that step")
    return parser.parse_args()


def _endpoint(
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


def _report(result: RunResult, output: Path) -> None:
    counters = result.counters
    print(f"Run {result.run_id} ended: {result.end_reason}")
    print(
        f"Rounds {counters.step}; retries {counters.retries}; rejections "
        f"{counters.rejections}; queried locations {counters.queried_locations}; "
        f"elapsed {counters.elapsed_s:.1f} s"
    )
    print(f"Trace: {output / result.trace}")


def main() -> int:
    arguments = _arguments()
    resume_parts = (arguments.resume, arguments.from_step, arguments.state)
    if any(part is not None for part in resume_parts) and None in resume_parts:
        print("--resume, --from-step and --state go together", file=sys.stderr)
        return 2
    model: ModelAdapter
    source: ExecutionSource
    if arguments.script is not None:
        model, source = ScriptedModel(arguments.script), "scripted_model"
    else:
        model = ChatModel(_endpoint(arguments, arguments.model, DECISION_MAX_TOKENS))
        source = "llm"
    verifier = ChatVerifier(
        _endpoint(arguments, arguments.verifier_model, REVIEW_MAX_TOKENS)
    )
    client = synthetic_client()
    if arguments.resume is not None:
        result = resume(
            arguments.resume,
            arguments.from_step,
            arguments.state,
            model,
            verifier,
            client,
            arguments.output,
            source,
        )
    else:
        config = RunConfig(
            data_version=None,
            step_cap=arguments.step_cap,
            query_budget_locations=arguments.query_budget,
            time_cap_s=arguments.time_cap,
            boundary_d0_max_share=arguments.boundary_share,
            include_recent_steps=arguments.recent_steps > 0,
            recent_steps=arguments.recent_steps,
            write_maps=arguments.maps,
        )
        task = TaskInput(
            CellId(arguments.down_cell), arguments.outage_time, arguments.objective
        )
        result = run(config, task, model, verifier, client, arguments.output, source)
    _report(result, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
