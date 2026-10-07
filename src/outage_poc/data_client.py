"""The data seam: a tool library the loop calls by name, and the typed results it returns.

The loop never reads a dataset. It calls the four data actions through a
`DataClient`: a list of declared tools and one `call` method with a timeout.
`LocalClient` serves tools that are Python functions in this process. The
internal environment keeps the same declarations, row shapes and result
semantics over its own data functions, so nothing in the loop changes.
"""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Protocol

Row = dict[str, object]
Arguments = dict[str, object]


@dataclass(frozen=True)
class ToolDeclaration:
    """What a tool publishes about itself: the half of the registry the data side owns."""

    name: str
    description: str
    input_schema: dict[str, object]
    # The version of the data behind the tool.
    data_version: str | None


@dataclass(frozen=True)
class Rows:
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class ToolTimeout:
    timeout_s: float


@dataclass(frozen=True)
class ToolFailure:
    message: str


ToolResult = Rows | ToolTimeout | ToolFailure


class ToolError(Exception):
    """Raised by a tool function for a bad request: unknown id, malformed argument,
    no data for the request. The client returns it as a ToolFailure."""


class DataClient(Protocol):
    def list_tools(self) -> tuple[ToolDeclaration, ...]: ...

    def call(self, name: str, arguments: Arguments, timeout_s: float) -> ToolResult: ...


def tools_data_version(tools: tuple[ToolDeclaration, ...]) -> str:
    """The one data version that every tool reports."""
    reported = [tool.data_version for tool in tools]
    version = reported[0] if reported and len(set(reported)) == 1 else None
    if version is None:
        raise ValueError(f"Tools must report one data version; got {reported}")
    return version


ToolFunction = Callable[[Arguments], list[Row]]


def _row(value: object) -> Row:
    if not isinstance(value, dict):
        raise TypeError(f"A row must be a JSON object, got {type(value).__name__}")
    return {str(key): item for key, item in value.items()}


@dataclass(frozen=True)
class LocalTool:
    declaration: ToolDeclaration
    function: ToolFunction


class LocalClient:
    """Tools as functions in this process.

    Each call runs on its own thread so that a timeout can be applied; a call
    that outlives its timeout is reported as ToolTimeout and its thread is left
    to finish on its own. A ToolError from the function is a ToolFailure. Any
    other exception is a bug in the tool and propagates. Rows pass through JSON
    on the way back, so a local tool returns exactly what a remote one would:
    tuples become lists and only JSON values survive.
    """

    def __init__(self, tools: tuple[LocalTool, ...]) -> None:
        names = [tool.declaration.name for tool in tools]
        if len(set(names)) != len(names):
            raise ValueError(f"Tool names must be unique; got {names}")
        self._tools = {tool.declaration.name: tool for tool in tools}
        self._pool = ThreadPoolExecutor(thread_name_prefix="data-tool")

    def list_tools(self) -> tuple[ToolDeclaration, ...]:
        return tuple(tool.declaration for tool in self._tools.values())

    def call(self, name: str, arguments: Arguments, timeout_s: float) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolFailure(f"unknown tool {name!r}")
        future = self._pool.submit(tool.function, dict(arguments))
        try:
            rows = future.result(timeout=timeout_s)
        except FutureTimeout:
            return ToolTimeout(timeout_s)
        except ToolError as error:
            return ToolFailure(str(error))
        wire: object = json.loads(json.dumps(rows, allow_nan=False))
        if not isinstance(wire, list):
            raise TypeError(f"{name} did not return a list of rows")
        return Rows(tuple(_row(item) for item in wire))

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> "LocalClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
