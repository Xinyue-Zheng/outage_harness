"""The decision model behind the llm_call node, and the chat client both model nodes use.

The model receives the rendered context: the stable prefix as the system
message and the variable part as the user message. It returns raw text; the
program parses it. Any OpenAI-compatible chat completions endpoint works: the
internal endpoint, or a local vLLM server during development.
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from outage_poc.models import Rendered
from outage_poc.persistence import _array, _field, _object, _string


@dataclass(frozen=True)
class ChatEndpoint:
    # For example http://127.0.0.1:8011/v1
    base_url: str
    model: str
    # The environment variable that holds the API key; None for an endpoint without keys.
    api_key_env: str | None
    temperature: float
    max_tokens: int
    timeout_s: float

    def describe(self) -> str:
        return f"{self.model} at {self.base_url}"


class ModelCallError(RuntimeError):
    pass


def chat(endpoint: ChatEndpoint, system: str, user: str) -> str:
    """One chat completion; returns the reply text. A transport or format error raises."""
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
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
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


class ModelAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def propose(self, rendered: Rendered) -> str: ...


class ChatModel:
    """The decision model: proposes the action, its parameters and the information gap."""

    def __init__(self, endpoint: ChatEndpoint) -> None:
        self._endpoint = endpoint

    @property
    def name(self) -> str:
        return self._endpoint.describe()

    def propose(self, rendered: Rendered) -> str:
        return chat(self._endpoint, rendered.prefix, rendered.variable)


def read_script(path: Path) -> tuple[str, ...]:
    """One reply per block; blocks are separated by blank lines."""
    blocks: list[str] = []
    current: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    if not blocks:
        raise ValueError(f"Script {path} has no replies")
    return tuple(blocks)


class ScriptedModel:
    """Replays recorded replies in order, for regression runs; raises when exhausted."""

    def __init__(self, path: Path) -> None:
        self._replies = read_script(path)
        self._next = 0
        self._source = path

    @property
    def name(self) -> str:
        return f"scripted replies from {self._source}"

    def propose(self, rendered: Rendered) -> str:
        if self._next >= len(self._replies):
            raise RuntimeError(
                f"Scripted model has no reply for call {self._next + 1}; "
                f"{self._source} has {len(self._replies)}"
            )
        reply = self._replies[self._next]
        self._next += 1
        return reply
