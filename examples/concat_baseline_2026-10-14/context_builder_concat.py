"""Model input for the concatenation baseline.

Same `Rendered(prefix, variable)` contract as the rendered builder, so the
runner's render, write and call code does not change:

- prefix: the skill text, the task, the areas the tools accept, and the tool
  declarations. Fixed for the run, like a Codex system prompt plus AGENTS.md.
- variable: the transcript so far, flattened to one user string. Every tool
  output ever returned is in it, raw and truncated, in order. No counts, no
  summaries, no unknowns, no budget, no feedback section: the model has to
  read those from the raw outputs and its own earlier replies.

The areas list is part of the task input, not evidence: the model needs the
area ids to call query_area_coverage at all, as a Codex user lists the files
to work on.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transcript import Transcript

SKILL_PATH = Path(__file__).resolve().parent / "investigation_skill_concat.txt"


@dataclass(frozen=True)
class Rendered:
    prefix: str
    variable: str

    @property
    def messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.prefix}, {"role": "user", "content": self.variable}]

    @property
    def text(self) -> str:
        return self.prefix + "\n\n" + self.variable


def load_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _task_lines(state: Mapping[str, Any]) -> list[str]:
    task = state.get("task", {}) or {}
    lines = ["Task:", json.dumps({k: v for k, v in task.items()}, indent=1)]
    return lines


def _area_lines(state: Mapping[str, Any]) -> list[str]:
    areas = (state.get("geography") or {}).get("areas") or {}
    lines = ["Areas the coverage tool accepts (id: kind, description, analysis grid locations):"]
    for area_id, area in areas.items():
        lines.append(f"- {area_id}: {area.get('kind', 'area')}, {area.get('description', '')} "
                     f"{area.get('locations', area.get('grid_count', '?'))} locations.")
    return lines


def _declaration_lines(tools: Iterable[Any]) -> list[str]:
    declarations = [
        {key: tool[key] if isinstance(tool, Mapping) else getattr(tool, key)
         for key in ("name", "description", "input_schema")}
        for tool in tools
    ]
    declarations.append({"name": "finish", "description": "End the investigation.",
                         "input_schema": {"type": "object", "properties": {}}})
    return ["Tools:", json.dumps(sorted(declarations, key=lambda d: d["name"]), indent=1)]


def build_prefix(state: Mapping[str, Any], tools: Iterable[Any]) -> str:
    """The system message: skill, task, areas, tool declarations."""
    blocks = [[load_skill().rstrip()], _task_lines(state), _area_lines(state), _declaration_lines(tools)]
    return "\n\n".join("\n".join(block) for block in blocks)


def initial_user_message() -> str:
    return ("Investigate the outage with the tools. Each tool output is appended below as "
            "returned. Reply with one JSON decision per turn.")


def new_transcript(state: Mapping[str, Any], tools: Iterable[Any]) -> Transcript:
    transcript = Transcript(system=build_prefix(state, tools))
    transcript.user(initial_user_message())
    return transcript


def build_context(transcript: Transcript) -> Rendered:
    """The two messages for a (system, user) client."""
    return Rendered(prefix=transcript.system, variable=transcript.as_user_text())
