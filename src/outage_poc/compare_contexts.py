"""Run the same case under both context methods and write a comparison.

    uv run python -m outage_poc.compare_contexts --output outputs/compare_01 \\
        --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b-instruct-awq \\
        --verifier-model qwen2.5-32b-instruct-awq [--recent-steps 3] [--script FILE]

Two run directories are written under --output:

    state_context/       the State rendering method (`outage_poc.loop`)
    transcript_context/  the append-only transcript method (`outage_poc.transcript_loop`)

and `comparison.md` with, per method: the end reason, rounds, rejections,
queried locations, the model input size per round, and compactions. Both runs
use the same harness, the same verifier, the same data and the same caps.
"""

import argparse
import json
import sys
from pathlib import Path

from outage_poc.data_tools import synthetic_client
from outage_poc.loop import run as run_state_context
from outage_poc.model import ChatModel, ModelAdapter, ScriptedModel
from outage_poc.models import ExecutionSource, RunConfig, RunResult
from outage_poc.persistence import _field, _object, _string
from outage_poc.run import DECISION_MAX_TOKENS
from outage_poc.run_transcript import (
    add_run_arguments,
    endpoint,
    run_config,
    task,
    transcript_config,
    transcript_model,
    verifier,
)
from outage_poc.transcript_loop import run as run_transcript_context

STATE_DIR = "state_context"
TRANSCRIPT_DIR = "transcript_context"


def state_model(arguments: argparse.Namespace) -> tuple[ModelAdapter, ExecutionSource]:
    if arguments.script is not None:
        return ScriptedModel(arguments.script), "scripted_model"
    return ChatModel(endpoint(arguments, arguments.model, DECISION_MAX_TOKENS)), "llm"


def input_tokens(run_dir: Path) -> list[int]:
    """Estimated tokens (characters / 4) of the exact text sent each round."""
    inputs = sorted((run_dir / "inputs").glob("round_*.txt"))
    return [len(path.read_text(encoding="utf-8")) // 4 for path in inputs]


def steps_summary(run_dir: Path) -> list[str]:
    """One line per Step: round, action, validation, outcome."""
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    lines: list[str] = []
    for step_path in trace["steps"]:
        step = _object(json.loads((run_dir / step_path).read_text(encoding="utf-8")))
        decision = step["decision"]
        action = (
            _string(_field(_object(decision), "action"))
            if decision is not None
            else "(unparsed)"
        )
        lines.append(
            f"| {step['index']} | {action} | {step['validation']} | "
            f"{step['review']} | {step['outcome']} |"
        )
    return lines


def compactions(run_dir: Path) -> int:
    summary = run_dir / "transcript" / "summary.txt"
    if not summary.exists():
        return 0
    for line in summary.read_text(encoding="utf-8").splitlines():
        if line.startswith("compactions "):
            return int(line.split()[1])
    raise ValueError(f"{summary} has no compactions line")


def comparison(
    output: Path, state: RunResult, transcript: RunResult, config: RunConfig
) -> str:
    rows = {
        "state_context": (state, output / STATE_DIR),
        "transcript_context": (transcript, output / TRANSCRIPT_DIR),
    }
    lines = [
        "# Context method comparison",
        "",
        "Same harness, verifier, data, caps and scripts; only what the deciding "
        "model reads differs.",
        "",
        f"Step cap {config.step_cap}; query budget {config.query_budget_locations} "
        f"locations; boundary share {config.boundary_d0_max_share:g}; "
        f"recent steps in state context: "
        f"{config.recent_steps if config.include_recent_steps else 0}.",
        "",
        "| Method | End | Rounds | Retries | Rejections | Queried locations | "
        "Input tokens per round (est.) | Max | Total | Compactions |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, (result, run_dir) in rows.items():
        tokens = input_tokens(run_dir)
        counters = result.counters
        lines.append(
            f"| {name} | {result.end_reason} | {counters.step} | {counters.retries} | "
            f"{counters.rejections} | {counters.queried_locations} | "
            f"{', '.join(str(t) for t in tokens)} | {max(tokens) if tokens else 0} | "
            f"{sum(tokens)} | {compactions(run_dir)} |"
        )
    for name, (_, run_dir) in rows.items():
        lines.extend(
            [
                "",
                f"## {name}: steps",
                "",
                "| Round | Action | Validation | Review | Outcome |",
                "|---|---|---|---|---|",
                *steps_summary(run_dir),
            ]
        )
    lines.extend(
        [
            "",
            "## Where to look",
            "",
            "- `<method>/inputs/round_NN.txt`: the exact text the deciding model read.",
            "- `<method>/outputs/round_NN.txt`: its reply.",
            "- `<method>/steps/step_NN.json`: the Step with the State before and after.",
            "- `<method>/contexts/state_NN.txt`: the State rendering after the step "
            "(written in both methods; sent to the model only in state_context).",
            "- `transcript_context/transcript/round_NN.json`: the messages as sent; "
            "`compactions/`: what each compaction summarized and the summary.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_run_arguments(parser)
    parser.add_argument(
        "--recent-steps",
        type=int,
        default=0,
        help="Recent steps in the state context (0: condition A, 3: condition B)",
    )
    arguments = parser.parse_args()
    output: Path = arguments.output
    if output.exists() and any(output.iterdir()):
        print(f"Output must be a new or empty directory: {output}", file=sys.stderr)
        return 2
    base_config = run_config(arguments)
    state_config = RunConfig(
        data_version=base_config.data_version,
        step_cap=base_config.step_cap,
        query_budget_locations=base_config.query_budget_locations,
        time_cap_s=base_config.time_cap_s,
        boundary_d0_max_share=base_config.boundary_d0_max_share,
        include_recent_steps=arguments.recent_steps > 0,
        recent_steps=arguments.recent_steps,
        write_maps=base_config.write_maps,
    )
    case = task(arguments)
    model, source = state_model(arguments)
    print(f"[1/2] state context -> {output / STATE_DIR}")
    state_result = run_state_context(
        state_config,
        case,
        model,
        verifier(arguments),
        synthetic_client(),
        output / STATE_DIR,
        source,
    )
    print(
        f"      ended {state_result.end_reason} after {state_result.counters.step} rounds"
    )
    t_model, summarizer, t_source = transcript_model(arguments)
    print(f"[2/2] transcript context -> {output / TRANSCRIPT_DIR}")
    transcript_result = run_transcript_context(
        base_config,
        transcript_config(arguments),
        case,
        t_model,
        summarizer,
        verifier(arguments),
        synthetic_client(),
        output / TRANSCRIPT_DIR,
        t_source,
    )
    print(
        f"      ended {transcript_result.end_reason} after "
        f"{transcript_result.counters.step} rounds"
    )
    text = comparison(output, state_result, transcript_result, state_config)
    (output / "comparison.md").write_text(text, encoding="utf-8")
    print(f"Comparison: {output / 'comparison.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
