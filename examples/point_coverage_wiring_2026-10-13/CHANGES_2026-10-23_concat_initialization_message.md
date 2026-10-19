# Change of 2026-10-23: the concat transcript starts with an initialization message

Packages `outage_harness_codex_state` and `outage_harness_concat_checked`.
Files `context_builder_concat.py` and `langgraph_runner.py`. The rendered
package does not change.

## 1. Why

Initialization runs the same way in every package: the metadata query, the
OSM query, State 0. In the concat packages the transcript then starts with
one fixed user line ("Investigate the outage with the tools...") and no
record that either query has run, so the model's first turns re-query the
metadata. Codex CLI does not start empty either: before the first model
turn it injects an environment message (working directory, repository
state, AGENTS.md) that tells the model the state of the world. The analog
here is one user message that reports the two initialization queries and
their outputs, shown the way every tool output is shown in this condition:
as returned, truncated head and tail. After it, both models know the same
facts at round 1, and the first rounds compare the input format alone.

## 2. `context_builder_concat.py`

### 2a. Replace `initial_user_message`

Find:

```python
def initial_user_message() -> str:
    return ("Investigate the outage with the tools. Each tool output is appended below as "
            "returned. Reply with one JSON decision per turn.")
```

Replace with:

```python
def initial_user_message(state: Mapping[str, Any], observations: Iterable[Mapping[str, Any]],
                         run_dir: str | Path) -> str:
    """The environment message: what initialization ran and what it returned, before the
    first model turn. Each output is shown as returned, truncated like every tool output."""
    from .transcript import truncate

    lines = ["Initialization has run before this conversation. Its tool calls and outputs:"]
    for obs in observations:
        action = obs.get("action") or {}
        name = action.get("function") or obs.get("function") or "?"
        params = action.get("parameters") or obs.get("params") or {}
        result = obs.get("result") or {}
        lines.append("")
        lines.append(f"[tool {name}({json.dumps(params, sort_keys=True)}) output]")
        lines.append(_initialization_output(name, result, run_dir, truncate))
    lines.append("")
    lines.append("Investigate the outage with the tools. Each tool output is appended below as "
                 "returned. Reply with one JSON decision per turn.")
    return "\n".join(lines)


def _initialization_output(name: str, result: Mapping[str, Any], run_dir: str | Path, truncate: Any) -> str:
    """The raw text of an initialization tool's output: the metadata CSV, or the OSM payload's
    element count followed by the land-use GeoJSON feature list. A missing file is said so."""
    if result.get("status") != "success":
        return f"error: {result.get('error', 'no detail')}"
    output = result.get("output_file")
    path = Path(str(output)) if output else None
    if path is not None and not path.is_absolute():
        path = Path(run_dir) / path
    if path is None or not path.is_file():
        return "not recorded"
    text = path.read_text(encoding="utf-8")
    if name == "query_osm_landuse":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return truncate(text)
        elements = payload.get("elements")
        if isinstance(elements, list):
            head = {"element_count": len(elements), "bbox_wgs84": payload.get("bbox_wgs84"),
                    "source": result.get("source", "OpenStreetMap Overpass API")}
            return truncate(json.dumps(head, indent=1) + "\n" + json.dumps(elements, indent=1))
    return truncate(text)
```

Add `import json` and `from pathlib import Path` to the module's imports if
they are not there.

### 2b. `new_transcript` takes the observations

Find:

```python
def new_transcript(state: Mapping[str, Any], tools: Iterable[Any]) -> Transcript:
    transcript = Transcript(system=build_prefix(state, tools))
    transcript.user(initial_user_message())
    return transcript
```

Replace with:

```python
def new_transcript(state: Mapping[str, Any], tools: Iterable[Any],
                   observations: Iterable[Mapping[str, Any]] = (), run_dir: str | Path = ".") -> Transcript:
    transcript = Transcript(system=build_prefix(state, tools))
    transcript.user(initial_user_message(state, list(observations), run_dir))
    return transcript
```

## 3. `langgraph_runner.py`, `initialize_node`

Find:

```python
            transcript = concat.new_transcript(case_state, tools)
```

Replace with:

```python
            transcript = concat.new_transcript(case_state, tools, initial_observations, output_dir)
```

`initial_observations` and `output_dir` are both in scope at that point of
`initialize_node` (the list returned by `initialize_state0`, and the run
directory). Nothing else in the runner changes: the message is part of the
transcript from the start, so `render_context_node`, `LLM_input.txt` and
the step files carry it without edits.

## 4. The skill text (concat variants)

In `investigation_skill.txt` of both concat packages, find the "Evidence
and scope" paragraph's first sentence and add directly after it:

```
The conversation opens with the initialization message: the metadata query and the OpenStreetMap query have already run, and their outputs are shown there as returned. Do not query them again unless the message shows an error.
```

## 5. Check

1. `steps/step_01/LLM_input.txt` of a concat run starts, after the system
   message, with a user message that begins "Initialization has run before
   this conversation." and contains two `[tool ... output]` blocks, the
   second showing `"element_count": <N>`.
2. The first model decision of a concat run is not `query_basic_information`
   or `query_osm_landuse` (if it is, the message did not reach the model;
   check that `initial_observations` was non-empty in `initialize_node`).
3. `run_log.md` of the concat run shows the first step as a coverage query.
4. The rendered package's `LLM_input.txt` is unchanged.
