# Changes of 2026-10-20: the KPI requirement covers the outage sectors and every outage hour; one set of thresholds; same-sample co-observation in the redistribution

All three packages. Shared file `completion_point.py`, plus the skill text
and `redistribution.py`. Every step starts with why, then the edit.

---

## 1. Why

The first redistribution on a real run produced no load estimate: the
outage sectors had no RRC baseline, so the demand to move was unknown. The
`backup_load` check only required the backup candidates' baselines, while
the redistribution scales demand by the outage sectors' own RRC. The skill
already tells the model to query the outage cells; the check did not hold
it to that. A second gap: the adapter requires the exact weekday-and-hour
slot for every outage hour, so a baseline whose window missed an hour is
unusable for that hour, and the check did not look at slots at all.

The fix makes the check say exactly what the redistribution needs: for
every outage sector and every backup candidate, a baseline slot for every
hour of the outage interval, for both metrics. Queried-but-empty stays
"missing, reported, does not block"; never queried blocks; queried but with
some outage hour absent from the slots blocks, and the open item names the
cell and the hours, so the model can query the window that covers them.

---

## 2. `completion_point.py`: `backup_load_status`

Find the whole function `def backup_load_status(` and replace it with:

```python
def outage_hours(task: dict[str, Any]) -> list[tuple[int, int]]:
    """(weekday, hour) of every UTC hour bin overlapping [start_time, end_time)."""
    from datetime import datetime, timedelta, timezone

    def parse(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

    start, end = parse(task["start_time"]), parse(task["end_time"])
    current = start.replace(minute=0, second=0, microsecond=0)
    slots: list[tuple[int, int]] = []
    while current < end:
        slots.append((current.weekday(), current.hour))
        current += timedelta(hours=1)
    return slots or [(start.weekday(), start.hour)]


def _baseline_gaps(metrics: dict[str, Any], hours: list[tuple[int, int]]) -> list[str]:
    """The outage hours (as slot names) for which a cell's baseline lacks a mean of RRC or PRB."""
    from .redistribution import PRB_METRIC as PRB, RRC_METRIC as RRC

    gaps: list[str] = []
    for weekday, hour in hours:
        slot = f"weekday_{weekday}_hour_{hour:02d}"
        for metric in (RRC, PRB):
            by_slot = ((metrics or {}).get(metric) or {}).get("by_weekday_hour") or {}
            if (by_slot.get(slot) or {}).get("mean") is None:
                gaps.append(f"{slot} {metric}")
    return gaps


def backup_load_status(state: dict[str, Any]) -> dict[str, Any]:
    """Required: every outage sector and every backup candidate has a KPI baseline slot for
    every outage hour, for RRC and PRB. Queried with no rows is missing (reported, does not
    block); never queried blocks; queried but with an outage hour absent blocks and names it."""
    outage = sorted(state.get("outage_cells") or [])
    candidates = sorted(state.get("backup_candidates") or [])
    required = outage + [c for c in candidates if c not in outage]
    baselines = ((state.get("kpi_baselines") or {}).get("cells") or {})
    queried = kpi_queried_cells(state)
    hours = outage_hours(state["task"])
    complete, missing, not_queried, partial = [], [], [], {}
    for cell in required:
        metrics = baselines.get(cell)
        if metrics:
            gaps = _baseline_gaps(metrics, hours)
            if gaps:
                partial[cell] = gaps
            else:
                complete.append(cell)
        elif cell in queried:
            missing.append(cell)
        else:
            not_queried.append(cell)
    if not required:
        status, reason = "unknown", "No outage sector or backup candidate has been observed yet"
    elif not_queried:
        status, reason = "unknown", f"KPI baseline not yet queried for: {', '.join(not_queried)}"
    elif partial:
        named = "; ".join(f"{cell} lacks {len(gaps)} slot values, first {gaps[0]}" for cell, gaps in partial.items())
        status, reason = "unknown", f"KPI baseline does not cover every outage hour for: {named}; query a window that covers them"
    elif missing:
        status, reason = "complete", f"Every required cell was queried; no KPI rows for: {', '.join(missing)} (reported as missing)"
    else:
        status, reason = "complete", "Every outage sector and backup candidate has a KPI baseline for every outage hour"
    return {"status": status, "required": True, "reason": reason, "outage_cells": outage, "candidates": candidates,
            "with_baseline": complete, "missing": missing, "not_queried": not_queried,
            "partial": partial, "outage_hours": [f"weekday_{w}_hour_{h:02d}" for w, h in hours],
            "transfer_estimate": "present" if state.get("impact") else "absent"}
```

`kpi_queried_cells` is unchanged. The progress line for `backup_load`
already prints `reason`, so the open item now names the cells and the
first missing slot. In `progress_lines`, find the redistribution line
added on 2026-10-19:

```python
    missing = load.get("missing") or []
```

Replace with:

```python
    missing = [*(load.get("missing") or []), *(load.get("not_queried") or []), *(load.get("partial") or {})]
```

---

## 3. The skill text (all three)

Find, in the KPI baseline paragraph:

```
Query the outage cells and the backup candidates.
```

Replace with:

```
Query the outage cells and the backup candidates, in windows that cover every hour of the outage interval on the same weekday: the redistribution needs each outage sector's RRC and each backup's RRC and PRB for every outage hour, and a cell whose baseline lacks an outage hour is reported as not covered until a window that holds that hour is queried.
```

---

## 4. One set of thresholds

Why: the copied engineering model classifies with its own constants
(-105 dBm signal, 75% PRB) while the report classifies with the harness
constants (-110 dBm service, 10 dB margin, 80% PRB). Two numbers for one
idea cannot be explained in a paper. The report's classes are the ones
published, so the model takes the harness values.

In `redistribution.py`, after the imports, add:

```python
from . import traffic_redistribution_estimate as _engine
from .completion_point import LOAD_LIMIT_PERCENT, SERVICE_RSRP_DBM

# One set of thresholds: the engineering model uses the harness values the report uses.
_engine.RSRP_THRESHOLD_DBM = SERVICE_RSRP_DBM
_engine.PRB_CAPACITY_THRESHOLD = LOAD_LIMIT_PERCENT / 100.0
```

Check `completion_point.py` does not import `redistribution` at module
level (it imports it inside `_baseline_gaps` and `end_run`), so there is
no import cycle.

---

## 5. `redistribution.py`: same-sample co-observation

Why: a grid location is 100 m by 100 m and one point call returns every
sample inside the radius; each sample is one measurement listing the
serving sector and up to five neighbours. The completion check and the
report count a backup at a location only when some sample lists both the
outage sector (at or above the coverage threshold) and the backup: one
device, one moment. The adapter fed the engineering model one RSRP per cell
per location, the maximum over all samples, so a backup seen only in a
sample without the outage sector counted as available, and the estimate
saw more backup coverage than the report. With the 4 m and 10 m radii most
locations hold one sample and the two agree; at 100 m they diverge. The
fix feeds the model the same fact the report uses.

In `redistribution.py`, `StateRedistributionModel.load_from_state`, find:

```python
            coverage = [{"antenna_id": cell, "rsrp": float(stats["rsrp_max_dbm"])}
                        for cell, stats in entry["cells"].items()]
            self.coverage_data[grid_id] = {"latitude": lat, "longitude": lon, "coverage": coverage}
```

Replace with:

```python
            # Only samples in which an outage sector is listed at or above the coverage threshold
            # count: the outage sector's RSRP and every backup's RSRP are the best over those samples.
            # A backup seen only in a sample without the outage sector is not a backup here.
            best: dict[str, float] = {}
            for sample in entry.get("samples") or []:
                cells = sample.get("cells") or {}
                if not any(self._is_outage(c) and r >= COVERAGE_RSRP_DBM for c, r in cells.items()):
                    continue
                for c, r in cells.items():
                    best[c] = max(best.get(c, -1e9), float(r))
            if not best:
                continue
            coverage = [{"antenna_id": cell, "rsrp": rsrp} for cell, rsrp in sorted(best.items())]
            self.coverage_data[grid_id] = {"latitude": lat, "longitude": lon, "coverage": coverage}
```

Add the outage predicate to the class. Find:

```python
    def __init__(self, state: dict[str, Any], geometry: dict[str, Any]) -> None:
        super().__init__()
        self._state = state
```

Replace with:

```python
    def __init__(self, state: dict[str, Any], geometry: dict[str, Any]) -> None:
        super().__init__()
        self._state = state
        from .radio import is_outage_cell

        task = state["task"]
        self._is_outage = lambda cell: is_outage_cell(cell, task)
```

and add `COVERAGE_RSRP_DBM` to the import from `point_coverage`:

```python
from .point_coverage import COVERAGE_RSRP_DBM, read_geometry
```

`redistribution.json` gains one line of provenance. In `run_redistribution`,
find:

```python
            "demand_rule": "population density x OSM weight x exp((RSRP + 120) / 10); softmax over backups by RSRP / 10"}
```

Replace with:

```python
            "demand_rule": "population density x OSM weight x exp((RSRP + 120) / 10); softmax over backups by RSRP / 10",
            "coverage_rule": f"per location, the best RSRP per cell over the samples that list an outage sector at or "
                             f"above {COVERAGE_RSRP_DBM:g} dBm; backups outside those samples are not counted"}
```

Check: on a State where one location has two samples, one listing the
outage sector with backup A and one listing backup B alone, the adapter's
`coverage_data` for that location holds the outage sector and A, not B.
The report's "with backup" count and the estimate's backup set then agree
for every location.

## 6. Check

1. On the `ARL02850` State that produced zero load estimates, the progress
   block's `backup_load` line now lists the eight outage sectors under "not
   yet queried" (or "does not cover every outage hour"), and the run cannot
   finish until they are queried.
2. After a KPI query that covers the outage hours for the outage sectors
   and the candidates, `redistribution.json` has one `backup_loads` entry
   per candidate with a baseline, and the report's per-backup lines show
   estimated PRB with the worst hour.
3. `redistribution.json` reports the thresholds the engine used; they equal
   the report's, and its `coverage_rule` line states the same-sample rule.
