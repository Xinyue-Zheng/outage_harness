"""Resume a run from one of its Steps with a corrected State: the human at the boundary.

A Step holds the full State, the counters, the data version, the query cache and
the registry version, so it is the checkpoint. Resume checks both versions,
checks the corrected State against the cached observations, copies rounds 1..k
into a new run directory, and continues the loop from loop_guards with the
corrected State as the State after round k. The original run directory is not
changed.
"""

import shutil
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from outage_poc.context import render_context
from outage_poc.data_client import DataClient
from outage_poc.loop import (
    INITIAL_STATE,
    PREFIX,
    LoopState,
    ResumePoint,
    RunEnv,
    finish_run,
    prepare_run_dir,
    resolve_data_version,
    run_rounds,
    step_path,
)
from outage_poc.model import ModelAdapter
from outage_poc.models import (
    ExecutionSource,
    RunRecord,
    RunResult,
    State,
    Step,
    StepDigest,
    TaskInput,
)
from outage_poc.persistence import (
    load_observations,
    read_json,
    read_state,
    read_step,
    write_json,
    write_text,
)
from outage_poc.registry import build_registry
from outage_poc.state import records_from_state
from outage_poc.verifier import VerifierAdapter


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_rounds(run_dir: Path, out_dir: Path, steps: tuple[Step, ...]) -> None:
    """Copy the files of rounds 1..k unchanged, so they stay byte-identical."""
    paths = [INITIAL_STATE, PREFIX, "contexts/state_00.txt"]
    for step in steps:
        paths.extend(
            [
                step_path(step.index),
                step.context,
                f"outputs/round_{step.index:02d}.txt",
                step.context_after,
            ]
        )
        if step.visualization is not None:
            paths.append(step.visualization)
    for relative in paths:
        _copy(run_dir / relative, out_dir / relative)
    for obs_id in steps[-1].query_cache:
        for source in (run_dir / "observations").glob(f"{obs_id}*.json"):
            if source.stem == obs_id or source.stem.startswith(f"{obs_id}_"):
                _copy(source, out_dir / "observations" / source.name)


def _check_corrected(corrected: State, step: Step, run_dir: Path) -> None:
    """The corrected State must agree with the observations the Step had cached."""
    for link in corrected.observations:
        if not any(
            link.observation_id.startswith(f"{obs_id}_") for obs_id in step.query_cache
        ):
            raise ValueError(
                f"Corrected State links {link.observation_id}, which is not in "
                f"the query cache of {step.id}"
            )
    records_from_state(corrected, load_observations(corrected, run_dir))


def resume(
    run_dir: Path,
    step_index: int,
    corrected_state_path: Path,
    model: ModelAdapter,
    verifier: VerifierAdapter,
    client: DataClient,
    out_dir: Path,
    execution_source: ExecutionSource,
) -> RunResult:
    record = read_json(RunRecord, run_dir / "run.json")
    steps = tuple(
        read_step(run_dir / step_path(index)) for index in range(1, step_index + 1)
    )
    if not steps or steps[-1].index != step_index:
        raise ValueError(f"{run_dir} has no step {step_index}")
    step = steps[-1]
    tools = client.list_tools()
    registry = build_registry(tools)
    if registry.version != step.registry_version:
        raise ValueError(
            f"Registry version mismatch: {step.id} was recorded with "
            f"{step.registry_version}, the tools now give {registry.version}"
        )
    data_version = resolve_data_version(record.config, tools)
    if data_version != step.data_version:
        raise ValueError(
            f"Data version mismatch: {step.id} was recorded with {step.data_version}, "
            f"the tools now report {data_version}"
        )
    corrected = read_state(corrected_state_path)
    _check_corrected(corrected, step, run_dir)
    prepare_run_dir(out_dir)
    started_at = datetime.now(UTC).isoformat()
    _copy_rounds(run_dir, out_dir, steps)
    history = tuple(StepDigest.of(item) for item in steps)
    corrected = replace(corrected, id=f"state_{step_index:02d}_corrected")
    write_json(out_dir / f"states/{corrected.id}.json", corrected)
    write_text(
        out_dir / f"contexts/{corrected.id}.txt",
        render_context(corrected, registry, record.config, history).variable,
    )
    env = RunEnv(
        run_dir=out_dir,
        config=record.config,
        registry=registry,
        model=model,
        verifier=verifier,
        client=client,
        data_version=data_version,
        execution_source=execution_source,
        resume=ResumePoint(step_index + 1),
        elapsed_offset_s=step.counters.elapsed_s,
        started_monotonic=time.monotonic(),
    )
    task = corrected.task
    loop = LoopState(
        task=TaskInput(task.down_cell_id, task.outage_time, task.objective),
        state=corrected,
        counters=step.counters,
        history=history,
        query_cache=step.query_cache,
        round=step_index,
        state_before=None,
        rendered=None,
        raw_output=None,
        decision=None,
        validation=None,
        review=None,
        observation=None,
        end_reason=None,
    )
    final = run_rounds(env, loop, "loop_guards")
    return finish_run(
        env,
        f"run_{uuid.uuid4().hex[:12]}",
        final,
        started_at,
        resumed_from=f"{run_dir}#{step.id}",
    )
