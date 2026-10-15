"""Run one case with the package this file lives in.

    python -m outage_harness_codex_state.run_case \
        --down-cell CCL06069 --start-time 2026-02-10T09:00:00Z --end-time 2026-02-10T12:00:00Z \
        --output runs/case1_concat --max-steps 8 \
        --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b \
        --ca-bundle /path/to/certificate.pem

Place a copy of this file in each package next to langgraph_runner.py and
change PACKAGE below to the package name. The package decides the condition
(its langgraph_runner.CONDITION); this script builds the decision model, the
verifier (used only by a package whose graph has a verifier node), the tool
client, the point query and the caps, and calls run_case_langgraph.

The certificate for the internal endpoints is set with --ca-bundle or with
the environment variables REQUESTS_CA_BUNDLE (requests) and SSL_CERT_FILE
(httpx, urllib) before any client is built.

Two constructions depend on files that are only inside: the LLM client
(llm.OpenAICompatLLM) and the tool client (client.RealToolClient). They are
built in _model and _client below; match their constructors to your llm.py
and client.py. Everything else is fixed.

--fake-point-api replaces the point API with the synthetic one from
synthetic_case.py, so the whole loop can be exercised against the real model
before the first real API call.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import os
from pathlib import Path
from typing import Any

PACKAGE = "outage_harness_codex_state"   # "outage_harness_langgraph" in the rendered package


def _set_certificate(path: str | None) -> None:
    """Point every HTTP client at the internal certificate before any is imported."""
    if path is None:
        return
    if not Path(path).is_file():
        raise SystemExit(f"--ca-bundle {path} is not a file")
    os.environ["REQUESTS_CA_BUNDLE"] = path
    os.environ["SSL_CERT_FILE"] = path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One investigation run with this package.")
    parser.add_argument("--condition", choices=("rendered", "concat"), default="concat",
                        help="rendered: context rendered from State; concat: append-only transcript. "
                             "Passed to run_case_langgraph when the runner has a condition switch; "
                             "otherwise the package's CONDITION decides and this must agree with it")
    parser.add_argument("--ca-bundle", default=None,
                        help="Certificate file for the internal endpoints; sets REQUESTS_CA_BUNDLE and SSL_CERT_FILE")
    parser.add_argument("--down-cell", required=True, help="EnodeB id or sector id of the outage")
    parser.add_argument("--start-time", required=True, help="Planned outage start, ISO 8601 UTC")
    parser.add_argument("--end-time", required=True, help="Planned outage end, ISO 8601 UTC")
    parser.add_argument("--outage-cell-ids", nargs="*", default=None,
                        help="Explicit outage prefixes when the task lists them")
    parser.add_argument("--output", required=True, type=Path, help="New, empty run directory")
    parser.add_argument("--max-steps", type=int, default=8)
    # Model.
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible /v1 URL")
    parser.add_argument("--model", required=True, help="Decision model name")
    parser.add_argument("--verifier-model", default=None,
                        help="Verifier model name; omitted: no verifier. Ignored under concat")
    parser.add_argument("--api-key-env", default=None, help="Variable that holds the API key, if any")
    parser.add_argument("--max-tokens", type=int, default=1200)
    # Caps.
    parser.add_argument("--time-cap", type=float, default=3600.0, help="Seconds for the whole run")
    parser.add_argument("--tool-call-cap", type=int, default=20)
    parser.add_argument("--rejection-cap", type=int, default=3)
    parser.add_argument("--repeat-cap", type=int, default=2)
    parser.add_argument("--query-budget", type=int, default=1500, help="Locations the run may fetch")
    # Point API.
    parser.add_argument("--token-env", default="COVERAGE_API_TOKEN",
                        help="Variable that holds the point API token")
    parser.add_argument("--fake-point-api", action="store_true",
                        help="Use the synthetic point API instead of the real one")
    return parser.parse_args()


def _model(arguments: argparse.Namespace, name: str) -> Any:
    """The chat client. Match the constructor to llm.OpenAICompatLLM."""
    from llm import OpenAICompatLLM

    api_key = os.environ.get(arguments.api_key_env) if arguments.api_key_env else None
    return OpenAICompatLLM(base_url=arguments.base_url, model=name, api_key=api_key,
                           max_tokens=arguments.max_tokens)


def _client() -> Any:
    """The tool client over the tool library. Match the constructor to client.RealToolClient."""
    return importlib.import_module(f"{PACKAGE}.client").RealToolClient()


def _point_query(arguments: argparse.Namespace) -> Any:
    if arguments.fake_point_api:
        fake_point_api = importlib.import_module(f"{PACKAGE}.synthetic_case").fake_point_api
        return lambda lat, lon, r: fake_point_api(lat, lon, r)
    query_point_coverage = importlib.import_module(f"{PACKAGE}.point_by_point_cover").query_point_coverage
    make_point_query = importlib.import_module(f"{PACKAGE}.runner_point_nodes").make_point_query
    token = os.environ.get(arguments.token_env)
    if not token:
        raise SystemExit(f"{arguments.token_env} is not set; export the point API token or use --fake-point-api")
    return make_point_query(query_point_coverage, token)


def main() -> int:
    arguments = _arguments()
    _set_certificate(arguments.ca_bundle)
    runner = importlib.import_module(f"{PACKAGE}.langgraph_runner")
    RunLimits = importlib.import_module(f"{PACKAGE}.policy").RunLimits
    condition = arguments.condition
    package_condition = getattr(runner, "CONDITION", None)
    if package_condition is not None and package_condition != condition:
        raise SystemExit(f"{PACKAGE} is the {package_condition} package; --condition {condition} does not apply")
    switch = "condition" in inspect.signature(runner.run_case_langgraph).parameters
    if arguments.output.exists() and any(arguments.output.iterdir()):
        raise SystemExit(f"Output directory is not empty: {arguments.output}")
    task = {"down_cell_id": arguments.down_cell, "start_time": arguments.start_time,
            "end_time": arguments.end_time}
    if arguments.outage_cell_ids:
        task["outage_cell_ids"] = arguments.outage_cell_ids
    limits = RunLimits(
        max_time_seconds=arguments.time_cap,
        max_tool_calls=arguments.tool_call_cap,
        max_consecutive_rejections=arguments.rejection_cap,
        max_identical_queries=arguments.repeat_cap,
        max_query_locations=arguments.query_budget,
    )
    verifier = None
    if arguments.verifier_model and condition == "rendered":
        verifier = _model(arguments, arguments.verifier_model)
    summary = runner.run_case_langgraph(
        _model(arguments, arguments.model),
        _client(),
        task,
        arguments.output,
        max_steps=arguments.max_steps,
        verifier=verifier,
        limits=limits,
        point_query=_point_query(arguments),
        **({"condition": condition} if switch else {}),
    )
    print(f"{condition}: end_reason {summary.get('end_reason', 'complete' if summary.get('finished') else '?')}, "
          f"steps {summary.get('steps')}, observations {summary.get('observations')}; "
          f"run.json, steps.json, state.json and trace.txt in {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
