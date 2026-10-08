"""Model adapters for the transcript method: a chat completion over a message list.

`TranscriptChatModel` sends the transcript as the messages of one chat
completion, which is how Codex CLI sends its history. It also accepts a
`Rendered` context, so it satisfies `ModelAdapter` and the shared run records
can name it. `ScriptedTranscriptModel` replays recorded replies for regression
runs. `ChatSummarizer` writes compaction summaries with the same endpoint;
`HeadSummarizer` is the deterministic summarizer for scripted runs.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from outage_poc.model import ChatEndpoint, ModelCallError, read_script
from outage_poc.models import Rendered
from outage_poc.persistence import _array, _field, _object, _string
from outage_poc.transcript import COMPACTION_INSTRUCTIONS, Message


def chat_messages(endpoint: ChatEndpoint, messages: tuple[Message, ...]) -> str:
    """One chat completion over a full message list; returns the reply text."""
    headers = {"Content-Type": "application/json"}
    if endpoint.api_key_env is not None:
        key = os.environ.get(endpoint.api_key_env)
        if not key:
            raise ModelCallError(
                f"Environment variable {endpoint.api_key_env} is not set"
            )
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps(
        {
            "model": endpoint.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": endpoint.temperature,
            "max_tokens": endpoint.max_tokens,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint.base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=endpoint.timeout_s) as response:
            payload: object = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise ModelCallError(
            f"{endpoint.describe()} returned HTTP {error.code}: {detail}"
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ModelCallError(
            f"{endpoint.describe()} is not reachable: {error}"
        ) from error
    choices = _array(_field(_object(payload), "choices"))
    if len(choices) != 1:
        raise ModelCallError(f"{endpoint.describe()} returned {len(choices)} choices")
    message = _object(_field(_object(choices[0]), "message"))
    return _string(_field(message, "content"))


class TranscriptModelAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def propose(self, rendered: Rendered) -> str: ...

    def propose_from(self, messages: tuple[Message, ...]) -> str: ...


class TranscriptChatModel:
    """The decision model reading the transcript."""

    def __init__(self, endpoint: ChatEndpoint) -> None:
        self._endpoint = endpoint

    @property
    def name(self) -> str:
        return f"{self._endpoint.describe()} (transcript context)"

    def propose(self, rendered: Rendered) -> str:
        return chat_messages(
            self._endpoint,
            (Message("system", rendered.prefix), Message("user", rendered.variable)),
        )

    def propose_from(self, messages: tuple[Message, ...]) -> str:
        return chat_messages(self._endpoint, messages)


class ScriptedTranscriptModel:
    """Replays recorded replies in order, whatever the transcript says."""

    def __init__(self, path: Path) -> None:
        self._replies = read_script(path)
        self._next = 0
        self._source = path

    @property
    def name(self) -> str:
        return f"scripted replies from {self._source} (transcript context)"

    def _reply(self) -> str:
        if self._next >= len(self._replies):
            raise RuntimeError(
                f"Scripted model has no reply for call {self._next + 1}; "
                f"{self._source} has {len(self._replies)}"
            )
        reply = self._replies[self._next]
        self._next += 1
        return reply

    def propose(self, rendered: Rendered) -> str:
        return self._reply()

    def propose_from(self, messages: tuple[Message, ...]) -> str:
        return self._reply()


class ChatSummarizer:
    """The compaction summary written by a model, as Codex CLI does it."""

    def __init__(self, endpoint: ChatEndpoint) -> None:
        self._endpoint = endpoint

    @property
    def name(self) -> str:
        return f"{self._endpoint.describe()} (compaction)"

    def summarize(self, text: str) -> str:
        return chat_messages(
            self._endpoint,
            (Message("system", COMPACTION_INSTRUCTIONS), Message("user", text)),
        )


class HeadSummarizer:
    """A deterministic summarizer for scripted runs: the first `keep_chars` characters."""

    def __init__(self, keep_chars: int) -> None:
        if keep_chars <= 0:
            raise ValueError("keep_chars must be positive")
        self._keep = keep_chars

    @property
    def name(self) -> str:
        return f"head summarizer ({self._keep} characters)"

    def summarize(self, text: str) -> str:
        return f"[deterministic head summary]\n{text[: self._keep]}"
