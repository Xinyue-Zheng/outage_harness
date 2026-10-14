"""Append-only transcript: the model input of the concatenation baseline.

This is what Codex CLI and the other coding agents send to the model: a fixed
system message, then every message of the run in order, with each tool result
appended as the tool's raw output. Nothing is parsed, summarized or recomputed
for the model. Large outputs are truncated the way Codex truncates shell
output: keep the head and the tail, drop the middle, say how much was dropped.

The program still runs the same tools and still keeps its State for
evaluation. The State is never shown to the model in this condition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Codex CLI defaults for shell output shown to the model: 10 KiB and 256 lines.
OUTPUT_CAP_BYTES = 10 * 1024
OUTPUT_CAP_LINES = 256


def truncate(text: str, cap_bytes: int = OUTPUT_CAP_BYTES, cap_lines: int = OUTPUT_CAP_LINES) -> str:
    """Keep the head and the tail of a long output; mark what was dropped."""
    lines = text.splitlines()
    encoded = text.encode("utf-8")
    if len(encoded) <= cap_bytes and len(lines) <= cap_lines:
        return text
    if len(lines) > cap_lines:
        head_n, tail_n = cap_lines // 2, cap_lines - cap_lines // 2
        dropped = len(lines) - head_n - tail_n
        head, tail = lines[:head_n], lines[-tail_n:]
        text = "\n".join([*head, f"[... {dropped} lines truncated ...]", *tail])
        encoded = text.encode("utf-8")
    if len(encoded) > cap_bytes:
        half = cap_bytes // 2
        head = encoded[:half].decode("utf-8", errors="ignore")
        tail = encoded[-half:].decode("utf-8", errors="ignore")
        text = f"{head}\n[... {len(encoded) - 2 * half} bytes truncated ...]\n{tail}"
    return text


@dataclass
class Transcript:
    """The messages of one run, in order. Only `append` adds; nothing edits."""

    system: str
    messages: list[dict[str, str]] = field(default_factory=list)

    def user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def tool(self, name: str, text: str) -> None:
        # OpenAI-compatible endpoints without function calling accept tool output as a
        # user message labelled with the tool name; that is also what the flat text shows.
        self.messages.append({"role": "user", "content": f"[tool {name} output]\n{text}"})

    def as_messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system}, *self.messages]

    def as_user_text(self) -> str:
        """The whole transcript as one user string, for a client that takes (system, user)."""
        parts = []
        for message in self.messages:
            label = {"user": "USER", "assistant": "ASSISTANT"}[message["role"]]
            parts.append(f"----- {label} -----\n{message['content']}")
        return "\n\n".join(parts)

    def chars(self) -> int:
        return len(self.system) + sum(len(m["content"]) for m in self.messages)


def format_tool_output(action: str, result: dict[str, Any], run_dir: str | Path) -> str:
    """The raw text a tool call produced, as the model would see it in Codex.

    - query_area_coverage: the artifact file content (one JSON document with
      every point and its samples), truncated.
    - inspect_observation: the rows, truncated.
    - a failed call: the error text.
    """
    if result.get("status") != "success":
        return f"error: {result.get('error_type', 'ToolFailure')}: {result.get('error', 'no detail')}"
    if action == "query_area_coverage":
        path = Path(result["output_file"])
        if not path.is_absolute():
            path = Path(run_dir) / path
        return truncate(path.read_text(encoding="utf-8"))
    if action == "inspect_observation":
        return truncate(json.dumps(result.get("details", {}).get("rows", []), indent=1))
    return truncate(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=1))


def format_rejection(error: str) -> str:
    """What a rejected decision looks like to the model: the error, as a tool result."""
    return f"error: {error}"
