# Changes of 2026-10-19: the redistribution runs at the end of every run; a step log next to the report

Both packages (and the third). Every step starts with why, then the edit,
with the code pasted. Package placeholder: `<pkg>`.

---

## 1. Why, and where the redistribution runs

The redistribution (`TrafficRedistributionModel`) is never called today,
because no completion check requires it and it is not a tool the model can
call. It should be neither. It is a computation over facts the State already
holds: the coverage table (every sample's cells with RSRP per location) and
the KPI baselines (per cell, per weekday and hour). So the program runs it
once, in `end_run`, before the report, for every way a run ends. A run that
ends by a cap still gets it where the inputs exist. The model never acts on
it; the progress block says so in one line.

What changes against the standalone script: the model's inputs come from
State instead of files. `load_coordinates`, `load_coverage_data`,
`load_historical_metrics` and `load_population_density` read a data
directory, a CSV and a GeoTIFF; in the harness those are replaced by an
adapter that fills the same attributes from `state["coverage"]`, the
geometry file and `state["kpi_baselines"]`. The four estimation steps
(`estimate_demand_distribution`, `redistribute_traffic`,
`estimate_prb_increase`, `classify_all_coordinates`) are called unchanged.

---

## 2. `redistribution.py` (new module, both packages)

Why: one function, `run_redistribution(state, run_dir) -> dict`, that
returns what the report reads under `state["impact"]`. It subclasses the
existing model so the engineering steps stay in one place.

Create `<pkg>/redistribution.py`:

```python
"""Run the traffic redistribution over State at the end of a run.

Inputs come from State, not from files:
- coverage: state["coverage"] (per grid location, every sample's cells with RSRP) and the
  geometry file (grid origin and spacing, to give each location its coordinates);
- outage and backup cells: state["outage_cells"], state["backup_candidates"];
- historical RRC and PRB: state["kpi_baselines"]["cells"][cell][metric]["by_weekday_hour"],
  the per-slot means apply_kpi stores; a cell without a slot mean has no baseline;
- demand weights: the area kind of each location (settlement, road corridor) through
  OSM_WEIGHTS; population density is 1.0 unless POPULATION_DENSITY_TIFF exists.

One estimate per hour of the outage interval; the report takes the worst hour per backup
cell (highest estimated PRB) and the classification of that hour per location.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .point_coverage import read_geometry
from .traffic_redistribution_estimate import TrafficRedistributionModel

RRC_METRIC = "AVG_RRC_USERS"
PRB_METRIC = "MEAN_PRB_USED"      # the KPI column apply_kpi keeps as PRB utilisation, in percent
# Demand weight per area kind; a location in no activity area gets "default".
OSM_WEIGHTS = {"settlement": 1.0, "road_corridor": 0.5, "default": 0.2}


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


class StateRedistributionModel(TrafficRedistributionModel):
    """The engineering model fed from State. Overrides only the loaders and the baseline lookup."""

    def __init__(self, state: dict[str, Any], geometry: dict[str, Any]) -> None:
        super().__init__()
        self._state = state
        self._geometry = geometry
        self._baselines = ((state.get("kpi_baselines") or {}).get("cells") or {})

    def load_from_state(self) -> None:
        grid = self._geometry["grid"]
        columns, spacing = int(grid["columns"]), float(grid["spacing_m"])
        lat0, lon0 = float(grid["origin_lat"]), float(grid["origin_lon"])
        lon_scale = 111_320.0 * math.cos(math.radians(float(self._geometry["site"]["lat"])))
        kinds = {a: (m.get("kind") or "") for a, m in (self._state["geography"].get("areas") or {}).items()}
        for grid_id, entry in (self._state.get("coverage") or {}).items():
            if entry["status"] != "valid" or not entry["cells"]:
                continue
            row, column = divmod(int(grid_id), columns)
            lat = lat0 + (row + 0.5) * spacing / 111_320.0
            lon = lon0 + (column + 0.5) * spacing / lon_scale
            coverage = [{"antenna_id": cell, "rsrp": float(stats["rsrp_max_dbm"])}
                        for cell, stats in entry["cells"].items()]
            self.coverage_data[grid_id] = {"latitude": lat, "longitude": lon, "coverage": coverage}
            area_kinds = [kinds.get(a, "") for a in entry.get("area_ids", [])]
            self.osm_features[grid_id] = ("settlement" if "settlement" in area_kinds else
                                          "road_corridor" if "road_corridor" in area_kinds else "default")
        self.outage_cells = {c.lower() for c in self._state.get("outage_cells") or []}
        self.backup_cells = {c.lower() for c in self._state.get("backup_candidates") or []}
        self.historical_metrics = pd.DataFrame()   # not used: get_historical_metrics_for_cell reads State

    def get_osm_weight(self, point_id: str) -> float:
        return OSM_WEIGHTS[self.osm_features.get(point_id, "default")]

    def get_population_density(self, lat: float, lon: float) -> float:
        return 1.0 if self.population_density is None else super().get_population_density(lat, lon)

    def get_historical_metrics_for_cell(self, cell_id: str, target_datetime: datetime) -> tuple[float, float]:
        """Same weekday and hour from the baseline; (0.0, 0.0) when the cell has no baseline.
        No default of 50% PRB: a missing baseline is reported, not assumed."""
        metrics = next((m for c, m in self._baselines.items() if c.lower() == cell_id.lower()), None)
        if not metrics:
            return 0.0, 0.0
        slot = f"weekday_{target_datetime.weekday()}_hour_{target_datetime.hour:02d}"

        def mean(metric: str) -> float | None:
            by_slot = (metrics.get(metric) or {}).get("by_weekday_hour") or {}
            value = (by_slot.get(slot) or {}).get("mean")
            if value is None:
                value = (metrics.get(metric) or {}).get("mean")
            return None if value is None else float(value)

        rrc, prb = mean(RRC_METRIC), mean(PRB_METRIC)
        if rrc is None or prb is None:
            return 0.0, 0.0
        return rrc, prb


def run_redistribution(state: dict[str, Any], run_dir: str | Path) -> dict[str, Any]:
    """The estimate the report reads as state["impact"]. Runs one estimate per outage hour.

    Returns {"backup_loads": [...], "locations": {...}, "hours": [...], "missing_baselines": [...]}.
    backup_loads: one entry per backup cell with its worst hour:
      cell_id, baseline_prb_percent, estimated_prb_percent, additional_rrc_users, worst_hour.
    locations: grid id -> {"classification", "strongest_backup", "backup_status"} at the worst hour
      of its strongest backup.
    """
    task = state["task"]
    model = StateRedistributionModel(state, read_geometry(state, run_dir))
    model.load_from_state()
    outage = sorted(model.outage_cells)
    missing = sorted(c for c in state.get("backup_candidates") or []
                     if model.get_historical_metrics_for_cell(c, _time(task["start_time"])) == (0.0, 0.0))
    if not model.coverage_data or not outage:
        return {"backup_loads": [], "locations": {}, "hours": [], "missing_baselines": missing,
                "reason": "no valid coverage with an outage sector"}
    demand = model.estimate_demand_distribution(outage)
    if demand.empty:
        return {"backup_loads": [], "locations": {}, "hours": [], "missing_baselines": missing,
                "reason": "no location where an outage sector is listed"}
    redistributed = model.redistribute_traffic(demand, outage)
    start, end = _time(task["start_time"]), _time(task["end_time"])
    hours: list[dict[str, Any]] = []
    worst: dict[str, dict[str, Any]] = {}
    locations: dict[str, dict[str, Any]] = {}
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        total_outage_rrc = sum(model.get_historical_metrics_for_cell(c, current)[0] for c in outage)
        prb = model.estimate_prb_increase(redistributed, current, total_outage_rrc)
        classes = model.classify_all_coordinates(redistributed, prb)
        hours.append({"hour": current.isoformat(), "total_outage_rrc": total_outage_rrc,
                      "prb": prb.to_dict("records"), "classes": classes.to_dict("records")})
        for row in prb.to_dict("records"):
            cell = row["antenna_id"]
            if cell not in worst or row["new_prb"] > worst[cell]["estimated_prb_percent"]:
                worst[cell] = {"cell_id": cell, "baseline_prb_percent": row["historical_prb"],
                               "estimated_prb_percent": row["new_prb"], "additional_rrc_users": row["additional_rrc_users"],
                               "worst_hour": current.isoformat()}
        for row in classes.to_dict("records"):
            strongest = str(row.get("strongest_backup", "")).lower()
            if row["point_id"] not in locations or (strongest in worst and worst[strongest]["worst_hour"] == current.isoformat()):
                locations[row["point_id"]] = {"classification": row["classification"],
                                              "strongest_backup": row["strongest_backup"],
                                              "backup_status": row["backup_status"]}
        current += timedelta(hours=1)
    return {"backup_loads": sorted(worst.values(), key=lambda b: b["cell_id"]), "locations": locations,
            "hours": hours, "missing_baselines": missing, "total_outage_rrc_source": "kpi_baselines",
            "demand_rule": "population density x OSM weight x exp((RSRP + 120) / 10); softmax over backups by RSRP / 10"}
```

Two things to settle in this module before it runs, both one line:

- `PRB_METRIC` and `RRC_METRIC` must be the column names `apply_kpi` kept.
  The standalone script reads `MEAN_PrbUsed` and `AVG_RRC_USERS` from its
  CSV; the harness confirmed `MEAN_PRB_USED`. Set the two constants to what
  `state["kpi_baselines"]["cells"][<cell>]` holds as keys.
- `OSM_WEIGHTS` here replaces the per-point OSM feature weights of the
  standalone script, which the harness does not keep. The three values are
  a starting point; change them in one place.

`traffic_redistribution_estimate.py` must be importable from the package
(`<pkg>/traffic_redistribution_estimate.py`) with its header constants
(`RSRP_THRESHOLD_DBM`, `RSRP_WEAK_MIN_DBM`, `RSRP_WEAK_MAX_DBM`,
`PRB_CAPACITY_THRESHOLD`, `DISCARD_CELL_PATTERN`) present. Its file-reading
loaders are not called.

---

## 3. `completion_point.py`: run it in `end_run`, and one progress line

Why: `end_run` is the single writer every end path goes through, so the
estimate is computed exactly once per run, after the last State update and
before the report.

### 3a. `end_run`

Find, in `end_run`:

```python
    final_state = {**state["state"], "completion_checks": checks, "end_reason": end_reason,
                   "final_report": "final_report.md"}
```

Replace with:

```python
    from .redistribution import run_redistribution

    impact = run_redistribution(state["state"], run_dir)
    write_json(run_dir / "redistribution.json", impact)
    final_state = {**state["state"], "completion_checks": checks, "end_reason": end_reason,
                   "impact": impact, "final_report": "final_report.md"}
```

(`run_dir` is already defined two lines above as `Path(state["output_dir"])`.)

### 3b. The report reads `impact["backup_loads"]`

`classify_locations` and `final_report` already read
`state["impact"]["backup_loads"]` with `cell_id`, `baseline_prb_percent`
and `estimated_prb_percent`; the entries above carry exactly those. No
change. In the report's per-backup section, after the load sentence, add
the worst hour: find

```python
                     f"limit {LOAD_LIMIT_PERCENT:g}%: {'exceeded' if float(b.get('estimated_prb_percent', 0)) > LOAD_LIMIT_PERCENT else 'within limit'}.")
```

and replace with

```python
                     f"limit {LOAD_LIMIT_PERCENT:g}%: {'exceeded' if float(b.get('estimated_prb_percent', 0)) > LOAD_LIMIT_PERCENT else 'within limit'}"
                     f" (worst hour {b.get('worst_hour', 'n/a')}, {b.get('additional_rrc_users', 0):.1f} additional RRC users).")
```

### 3c. The progress line

In `progress_lines`, find:

```python
    unmet = unmet_required(checks)
```

Add directly above it:

```python
    load = checks.get("backup_load") or {}
    missing = load.get("missing") or []
    lines.append("- redistribution: computed by the program at the end of the run from the coverage table and "
                 "the KPI baselines; not an action." + (f" Baselines missing for: {', '.join(missing)}." if missing else ""))
```

---

## 4. The step log: `run_log.md`

Why: the final report says what was found; it does not say how the run got
there. One line per step with its action, its outcome and its time gives
the reader of a run directory the whole trajectory on one page, and gives
the comparison between packages its per-step cost.

### 4a. Record the times

In `langgraph_runner.py`, `render_context_node` is the start of a round and
`update_state_node` or `record_error_node` its end. Add, at the top of
`render_context_node`:

```python
        round_started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_json(step_dir / "timing.json", {"started_at": round_started})
```

(`step_dir` is defined in that node; add `from datetime import datetime, timezone`
to the imports if absent.) In `update_state_node`, where `step.json` is
written, extend the dict:

```python
        _write_json(step_dir / "step.json", {"step": index, "decision": decision, "result": summary,
                                             "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
```

and the same `"ended_at"` entry in the `step` dict of `record_error_node`
and in `finish_step` of `end_run` (`completion_point.py`). The tool
duration is already in `tool_result.json` when the client records it; if
not, wrap the `client.call` and the point fetch in `execute_tool_node` with
`time.monotonic()` and add `"duration_s"` to the summary written there.

### 4b. Write the log

Add to `completion_point.py`, after `end_run`:

```python
def write_run_log(run_dir: Path, run: dict[str, Any]) -> Path:
    """One line per step: when it started, how long it took, what the model asked for, and what
    came of it. Read from the step directories; nothing is recomputed."""
    rows = []
    for step_dir in sorted(run_dir.glob("steps/step_[0-9][0-9]")):
        number = int(step_dir.name[-2:])
        if number == 0:
            continue
        step = json.loads((step_dir / "step.json").read_text(encoding="utf-8")) if (step_dir / "step.json").is_file() else {}
        timing = json.loads((step_dir / "timing.json").read_text(encoding="utf-8")) if (step_dir / "timing.json").is_file() else {}
        decision = step.get("decision") or {}
        action = decision.get("action") or {}
        name = action.get("function") or "?"
        params = action.get("parameters") or {}
        if name == "query_area_coverage":
            what = f"queried coverage of {params.get('area_id')} at {params.get('resolution')} m"
        elif name in ("query_lte_rrc_prb", "query_nr_rrc_prb"):
            what = f"queried KPI of {', '.join(params.get('cell_ids') or [])} from {params.get('start_time')} to {params.get('end_time')}"
        elif name == "expand_study_area":
            what = f"expanded the study area {params.get('direction')} by {params.get('distance_m')} m"
        elif name == "inspect_observation":
            what = f"inspected {params.get('observation_id')} rows {params.get('offset')} to {int(params.get('offset', 0)) + int(params.get('limit', 0)) - 1}"
        elif name == "finish":
            what = "proposed finish"
        else:
            what = name
        result = step.get("result") or {}
        if step.get("status") == "rejected":
            outcome = "rejected: " + str(step.get("error", ""))[:120]
        elif step.get("status") in ("finished", "ended"):
            outcome = f"run ended: {step.get('end_reason', 'complete')}"
        elif result.get("status") == "success":
            details = result.get("details") or {}
            outcome = ("fetched " + str(details.get("fetched")) + " locations" if "fetched" in details else
                       f"{result.get('row_count', '?')} rows")
        else:
            outcome = "failed: " + str(result.get("error", ""))[:120]
        started, ended = timing.get("started_at"), step.get("ended_at")
        seconds = ""
        if started and ended:
            seconds = f"{(datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds():.0f} s"
        rows.append(f"| {number} | {started or ''} | {seconds} | {what} | {outcome} |")
    lines = [f"# Run log: {run_dir.name}", "",
             f"Condition {run.get('condition', '?')}; end reason {run.get('end_reason', '?')}; {run.get('steps', '?')} steps.", "",
             "| step | started (UTC) | duration | action | outcome |", "|---|---|---|---|---|", *rows, ""]
    path = run_dir / "run_log.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
```

Add `from datetime import datetime` to the imports of `completion_point.py`.

### 4c. Call it

In `end_run`, after the `run.json` write and before the final `return`, add:

```python
    write_run_log(run_dir, json.loads((run_dir / "run.json").read_text(encoding="utf-8")))
```

`end_run` is reached by every end path, so every run gets `run_log.md`.

---

## 5. Check

1. `python -c "from <pkg>.redistribution import run_redistribution; print('ok')"` in each package.
2. One run to any end. The run directory has `redistribution.json` with
   `backup_loads` (one per backup cell with a baseline), the report's
   per-backup lines show the estimated PRB and the worst hour, and
   `run_log.md` has one row per step with a duration.
3. A run that ends by a cap before any KPI query: `redistribution.json`
   has empty `backup_loads` and every candidate under `missing_baselines`;
   the report classes those locations as "degrade, unknown cause".
