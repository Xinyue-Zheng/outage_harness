# Change of 2026-10-24: the backup_load open item names one KPI call for every cell

All three packages, `completion_point.py` and the skill text.

## 1. Why

After the ring probe many cells are seen from round 1, and the
`backup_load` line lists them all, in the per-cell form of the slot check
("A lacks 2 slot values, first ...; B lacks ..."). The model reads that as
one task per cell and queries one cell per round, which wastes rounds and
tool calls. The coverage open items name their action ("Next action:
query_area_coverage(area_id=R13)"); the KPI item never did. It now names
one call: every cell that needs a baseline, in one `cell_ids` list, with
the window that covers every outage hour. The checks do not change.

## 2. `completion_point.py`

### 2a. The window that covers the outage hours

Add after `outage_hours`:

```python
def kpi_window_for(task: dict[str, Any], weeks: int = 4) -> tuple[str, str]:
    """start_time and end_time of one KPI query that covers every outage hour on the same
    weekday in the last `weeks` prior weeks: from the outage start moved back `weeks` weeks to
    the outage end moved back one week. Ends strictly before the outage."""
    from datetime import datetime, timedelta, timezone

    def parse(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

    start, end = parse(task["start_time"]), parse(task["end_time"])
    return ((start - timedelta(weeks=weeks)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            (end - timedelta(weeks=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
```

### 2b. `backup_load_status` records what one call must contain

In `backup_load_status`, before the `return`, add:

```python
    to_query = sorted(set(not_queried) | set(partial))
    from .radio import radio_technology

    calls = {}
    for cell in to_query:
        tech = radio_technology(cell)
        calls.setdefault("query_nr_rrc_prb" if tech == "NR" else "query_lte_rrc_prb", []).append(cell)
    window = kpi_window_for(state["task"]) if to_query else None
```

and add to the returned dict:

```python
            "next_calls": [{"function": f, "cell_ids": cells, "start_time": window[0], "end_time": window[1]}
                           for f, cells in sorted(calls.items())],
```

### 2c. The progress line names the call

In `progress_lines`, find the `backup_load` lines:

```python
    if load.get("status") == "complete":
        lines.append("- backup_load: met. " + str(load.get("reason", "")) + ".")
    else:
        lines.append("- backup_load: not met. " + str(load.get("reason", "")) + ".")
```

Replace with:

```python
    if load.get("status") == "complete":
        lines.append("- backup_load: met. " + str(load.get("reason", "")) + ".")
    else:
        lines.append("- backup_load: not met. " + str(load.get("reason", "")) + ".")
        for call in load.get("next_calls") or []:
            lines.append(f"  Next action, one call for all of them: {call['function']}(cell_ids={json.dumps(call['cell_ids'])}, "
                         f"start_time={call['start_time']}, end_time={call['end_time']}). "
                         "Do not query these cells one at a time.")
```

(`json` is imported in the module.) When both technologies are present
there are two lines, one per tool, because the tools are separate.

### 2d. The refusal says the same

In `finish_check`, the refusal builds its message from `unmet`'s
`unresolved` or `reason`. For `backup_load`, append the same call text:
find

```python
                "error": "Completion refused: " + json.dumps({k: v.get("unresolved", v.get("reason")) for k, v in unmet.items()})}
```

and replace with

```python
                "error": "Completion refused: " + json.dumps({k: v.get("unresolved", v.get("reason")) for k, v in unmet.items()})
                         + "".join(f"; next action: {c['function']}(cell_ids={json.dumps(c['cell_ids'])}, start_time={c['start_time']}, end_time={c['end_time']})"
                                   for c in (unmet.get("backup_load") or {}).get("next_calls") or [])}
```

This is the line the concat_checked model reads, since it has no progress
block.

## 3. The skill text (all three)

In the KPI baseline paragraph, after "Query the outage cells and the
backup candidates, in windows that cover every hour of the outage interval
on the same weekday", add:

```
Put every cell that needs a baseline into one cell_ids list per tool; the completion progress names that call. One call per cell wastes rounds and is not needed.
```

## 4. Check

On a State where several cells lack a baseline, the progress block ends the
`backup_load` item with one "Next action, one call for all of them:" line
per tool, listing every cell; a run's `run_log.md` shows the KPI baselines
collected in at most two rounds (LTE and NR).
