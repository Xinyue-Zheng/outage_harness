"""The append-only context method, as Codex CLI builds it: a transcript of messages.

This is the alternative to `context.render_context` for the context experiment.
The model reads a chat transcript that only grows at the end:

    system:    the stable prefix (skill, task, geography, areas, actions, rules)
    user:      the task opener (and, after compaction, a summary of older rounds)
    assistant: the model's reply of round 1
    user:      the raw tool output of round 1, truncated to a byte cap
    assistant: the model's reply of round 2
    ...

No fact is computed into the transcript. A query returns its rows as the tool
wrote them; a rejected or unparseable decision returns the program's error
text; a refused finish returns the unmet rules. When the transcript grows past
a token threshold, a model call summarizes the older rounds and the summary
replaces them; the last few rounds stay verbatim.

The harness around the model (parse, validate, verifier, execute, State, caps,
completion checks) is unchanged. Only what the deciding model reads differs.
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol, assert_never

from outage_poc.models import (
    CoverageObservation,
    ImpactAnalysis,
    Inspection,
    KPIRows,
    Member,
    MemberError,
    Observation,
    State,
    Task,
)
from outage_poc.persistence import read_json

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class TranscriptConfig:
    # Codex CLI cuts tool output to a byte cap, removing the middle.
    output_cap_bytes: int = 10_000
    # Estimated tokens (characters / 4) of the whole transcript above which the
    # older rounds are summarized.
    compact_threshold_tokens: int = 20_000
    # Rounds kept verbatim after a compaction.
    keep_recent_rounds: int = 3


@dataclass(frozen=True)
class Round:
    index: int
    reply: str
    tool_output: str


@dataclass(frozen=True)
class Transcript:
    system: str
    opener: str
    # Summary of rounds 1..summary_through, present after a compaction.
    summary: str | None
    summary_through: int
    # Rounds after summary_through, verbatim.
    rounds: tuple[Round, ...]
    compactions: int

    def messages(self) -> tuple[Message, ...]:
        opener = self.opener
        if self.summary is not None:
            opener += (
                f"\n\nSummary of rounds 1 to {self.summary_through}, written by the "
                f"model when the transcript was compacted:\n{self.summary}"
            )
        out = [Message("system", self.system), Message("user", opener)]
        for item in self.rounds:
            out.append(Message("assistant", item.reply))
            out.append(Message("user", item.tool_output))
        return tuple(out)

    def flattened(self) -> str:
        """The messages as one readable text, for the Step's context file."""
        return "\n\n".join(
            f"[{message.role}]\n{message.content}" for message in self.messages()
        )


def estimate_tokens(messages: tuple[Message, ...]) -> int:
    return sum(len(message.content) for message in messages) // 4


class Summarizer(Protocol):
    """Writes the compaction summary; a model in live runs, a fixed rule in tests."""

    @property
    def name(self) -> str: ...

    def summarize(self, text: str) -> str: ...


def opener(task: Task) -> str:
    return (
        f"Investigate the outage impact of cell {task.down_cell_id} "
        f"(outage time {task.outage_time}). {task.objective}\n"
        "Each of your replies is one decision in the three-line format of the skill. "
        "After each decision you receive the tool's output, or the program's error, "
        "as the next message. Begin."
    )


def truncate_middle(text: str, cap_bytes: int) -> str:
    """Keep the head and the tail; say how much was removed. Bytes count in UTF-8."""
    data = text.encode("utf-8")
    if len(data) <= cap_bytes:
        return text
    keep = cap_bytes // 2
    head = data[:keep].decode("utf-8", errors="ignore")
    tail = data[-keep:].decode("utf-8", errors="ignore")
    return (
        f"{head}\n[... {len(data) - 2 * keep} of {len(data)} bytes omitted ...]\n{tail}"
    )


def _records_text(kind: str, records: tuple[object, ...]) -> str:
    """One compact JSON object per row, as a tool would print its rows."""
    lines = [json.dumps(record, separators=(",", ":")) for record in records]
    return f"{len(lines)} {kind} rows\n" + "\n".join(lines)


def _member_text(observation: Observation, member: Member, run_dir: Path) -> str:
    header = f"member {member.member_id}: {member.status}"
    path = member.records_path
    match member.status:
        case "timeout":
            return f"{header} (no result within the time limit)"
        case "error":
            if path is None:
                raise ValueError("An error member needs its records file")
            return f"{header}: {read_json(MemberError, run_dir / path).error}"
        case "empty":
            return f"{header} (no rows)"
        case "ok" | "missing":
            if path is None:
                raise ValueError("A result member needs its records file")
            return f"{header}\n{_rows_text(observation.action, run_dir / path)}"
        case _ as unreachable:
            assert_never(unreachable)


def _rows_text(action: str, path: Path) -> str:
    match action:
        case "coverage.query":
            coverage = read_json(CoverageObservation, path)
            rows = tuple(
                {
                    "grid_id": record.grid_id,
                    "status": record.status,
                    "cells": [
                        {
                            "cell_id": signal.cell_id,
                            "rsrp_dbm": signal.rsrp_dbm,
                            "rsrq_db": signal.rsrq_db,
                        }
                        for signal in record.cells
                    ],
                    "down_cell_traffic_mbps": record.down_cell_traffic_mbps,
                }
                for record in coverage.records
            )
            return f"result_status {coverage.result_status}\n" + _records_text(
                "coverage", rows
            )
        case "kpi.query":
            kpis = read_json(KPIRows, path)
            rows = tuple(
                {
                    "cell_id": record.cell_id,
                    "window": record.window,
                    "indicator": record.indicator,
                    "value": record.value,
                    "unit": record.unit,
                }
                for record in kpis.records
            )
            return _records_text("kpi", rows)
        case "impact.estimate":
            impact = read_json(ImpactAnalysis, path)
            summary = {
                "scope_area_id": impact.parameters.scope_area_id,
                "scope_queried": len(impact.scope_queried_ids),
                "excluded_unqueried": len(impact.excluded_unqueried_ids),
                "excluded_missing": len(impact.excluded_missing_ids),
                "target_location_count": impact.target_location_count,
                "total_target_traffic_mbps": impact.total_target_traffic_mbps,
                "unserved_traffic_mbps": impact.unserved_traffic_mbps,
                "selection_rule": impact.parameters.selection_rule,
                "load_formula": impact.parameters.load_formula,
                "limitations": list(impact.limitations),
            }
            loads = tuple(
                {
                    "cell_id": load.cell_id,
                    "assigned_locations": load.assigned_locations,
                    "location_share": load.location_share,
                    "transferred_mbps": load.transferred_mbps,
                    "traffic_share": load.traffic_share,
                    "baseline_prb_percent": load.baseline_prb_percent,
                    "capacity_mbps": load.capacity_mbps,
                    "estimated_prb_percent": load.estimated_prb_percent,
                    "exceeds_capacity": load.exceeds_capacity,
                }
                for load in impact.backup_loads
            )
            assignments = tuple(
                {
                    "grid_id": item.grid_id,
                    "backup_cell_id": item.backup_cell_id,
                    "classification": item.classification,
                    "traffic_mbps": item.traffic_mbps,
                }
                for item in impact.assignments
            )
            return (
                json.dumps(summary, separators=(",", ":"))
                + "\n"
                + _records_text("backup_load", loads)
                + "\n"
                + _records_text("assignment", assignments)
            )
        case "inspect_observation":
            inspection = read_json(Inspection, path)
            rows = tuple(
                {
                    "grid_id": record.grid_id,
                    "status": record.status,
                    "cells": [
                        {
                            "cell_id": signal.cell_id,
                            "rsrp_dbm": signal.rsrp_dbm,
                            "rsrq_db": signal.rsrq_db,
                        }
                        for signal in record.cells
                    ],
                    "down_cell_traffic_mbps": record.down_cell_traffic_mbps,
                }
                for record in inspection.records
            )
            return (
                f"rows {inspection.first_row} to "
                f"{inspection.first_row + len(inspection.records) - 1} of "
                f"{inspection.total_rows} in {inspection.observation_id}\n"
                + _records_text("coverage", rows)
            )
        case _:
            raise ValueError(f"No raw output format for action {action!r}")


def observation_text(
    observation: Observation, run_dir: Path, config: TranscriptConfig
) -> str:
    """The tool's output for the model: a header, then every member's rows, truncated."""
    header = (
        f"{observation.action} returned (observation {observation.id}, "
        f"status {observation.status}, {observation.duration_ms} ms):"
    )
    body = "\n".join(
        _member_text(observation, member, run_dir) for member in observation.members
    )
    return header + "\n" + truncate_middle(body, config.output_cap_bytes)


@dataclass(frozen=True)
class RoundResult:
    """What the harness produced in one round, as the transcript reports it."""

    reply: str
    observation: Observation | None
    error: str | None
    concern: str | None
    unmet: tuple[str, ...]
    # Set on the last round: the typed reason the run ended with.
    end_reason: str | None = None


def tool_output(result: RoundResult, run_dir: Path, config: TranscriptConfig) -> str:
    """The user message that follows the model's reply: tool rows or program errors."""
    parts: list[str] = []
    if result.error is not None:
        parts.append(f"error: {result.error}")
    if result.observation is not None:
        parts.append(observation_text(result.observation, run_dir, config))
    if result.unmet:
        parts.append("finish refused; unmet completion rules:")
        parts.extend(f"- {item}" for item in result.unmet)
    if result.concern is not None:
        parts.append(f"reviewer concern (advisory; may be wrong): {result.concern}")
    if result.end_reason is not None:
        parts.append(f"run ended: {result.end_reason}")
    if not parts:
        raise ValueError("A round must produce a tool output, an error or a refusal")
    return "\n".join(parts)


def start(system: str, task: Task) -> Transcript:
    return Transcript(system, opener(task), None, 0, (), 0)


def append(transcript: Transcript, index: int, reply: str, output: str) -> Transcript:
    expected = (
        (transcript.rounds[-1].index + 1)
        if transcript.rounds
        else (transcript.summary_through + 1)
    )
    if index != expected:
        raise ValueError(f"Round {index} appended out of order; expected {expected}")
    return replace(transcript, rounds=(*transcript.rounds, Round(index, reply, output)))


COMPACTION_INSTRUCTIONS = (
    "You compress the transcript of an outage investigation so that the "
    "investigation can continue from the summary alone. Keep every fact that a "
    "later decision needs: which areas and cells were queried and what the rows "
    "showed for the down cell, which decisions were rejected and why, which "
    "completion rules were unmet, and what remains unknown. Write plain text, "
    "no more than 400 words. Do not propose the next action."
)


def compaction_input(transcript: Transcript, through: int) -> str:
    """The text the summarizer compresses: the old summary and the rounds up to `through`."""
    parts: list[str] = []
    if transcript.summary is not None:
        parts.append(
            f"Earlier summary of rounds 1 to {transcript.summary_through}:\n"
            f"{transcript.summary}"
        )
    for item in transcript.rounds:
        if item.index > through:
            break
        parts.append(
            f"Round {item.index}\n[assistant]\n{item.reply}\n[user]\n{item.tool_output}"
        )
    return "\n\n".join(parts)


def maybe_compact(
    transcript: Transcript, config: TranscriptConfig, summarizer: Summarizer
) -> tuple[Transcript, str | None]:
    """Summarize the older rounds when the transcript is too long.

    Returns the transcript and, when a compaction ran, the text that was
    summarized, so the caller can record it.
    """
    if estimate_tokens(transcript.messages()) <= config.compact_threshold_tokens:
        return transcript, None
    if len(transcript.rounds) <= config.keep_recent_rounds:
        return transcript, None
    through = transcript.rounds[-config.keep_recent_rounds - 1].index
    source = compaction_input(transcript, through)
    summary = summarizer.summarize(source)
    if not summary.strip():
        raise ValueError("The summarizer returned an empty summary")
    kept = tuple(item for item in transcript.rounds if item.index > through)
    return (
        replace(
            transcript,
            summary=summary,
            summary_through=through,
            rounds=kept,
            compactions=transcript.compactions + 1,
        ),
        source,
    )


def write_messages(path: Path, messages: tuple[Message, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [{"role": m.role, "content": m.content} for m in messages],
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def notes_text(state: State, round_index: int, kind: str) -> tuple[str, ...]:
    return tuple(
        note.text
        for note in state.notes
        if note.step_index == round_index and note.kind == kind
    )
