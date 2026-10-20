# Change of 2026-10-26: the rule policy, a model-free way to run the rendered package

Sections 1 to 5 apply to `outage_harness_langgraph` only (new file
`rule_policy.py`; edits in `langgraph_runner.py`, `run_case.py`,
`completion_point.py`). Section 6, the per-hour report, applies to all
three packages. Every step
starts with why, then the edit with the code pasted.

The policy produces the reference investigation (the extent against which
every run is scored) and is also the no-model condition of the comparison.
It takes the model's seat and nothing else: initialization, the probe,
validation, execution, the State update, the completion check, the
expansion, the redistribution and the report are the package's own code.

---

## 1. Why a policy object, not a new runner

`llm_call_node` calls `model.complete_json(system, user, schema)` and
expects a decision dict. A policy that implements the same method and
ignores the two strings is a drop-in: the runner, the graph and every file
a run writes stay the same, so a rules run and a model run are compared
file for file. The policy reads the completion check from the State, which
`update_state_node` stores after every round; it never reads the rendered
text.

---

## 2. `rule_policy.py` (new)

```python
"""The rule policy: the model's seat filled by five rules over the completion check.

Applied in order, the first rule whose condition holds gives the round's decision:
1. backup_load names cells            -> one KPI call per technology, the window the check computed
2. a direction is open with an area   -> fetch the nearest such area to the site
3. a direction is open at the edge    -> expand it by EXPAND_STEP_M
4. a bin is unobserved with activity  -> fetch the nearest activity area in that bin
5. nothing open                       -> the verification pass, then finish

Rule 5 fetches, once per closed direction, the next activity area beyond the closing area;
a sector covering there reopens the direction and rules 2 and 3 take over. When every
direction is confirmed, the policy proposes finish, which the program accepts because the
checks pass. The policy never splits a KPI call and never reads the rendered context.
"""

from __future__ import annotations

import math
from typing import Any

from .completion_point import BIN_DEGREES, COVERAGE_RSRP_DBM
from .point_coverage import read_geometry

EXPAND_STEP_M = 2_000.0
VERIFY_DEPTH = 1        # extra areas beyond each closing area that rule 5 fetches


class RulePolicy:
    """Implements DecisionModel.complete_json; reads the State the runner passes in."""

    model = "rule_policy"
    max_tokens = 0

    def __init__(self, state_ref: dict[str, Any]) -> None:
        # The runner keeps the current State in this dict under "state" and the run directory
        # under "output_dir" (see section 3); the policy reads them at call time.
        self._ref = state_ref
        self._verified: set[tuple[str, int]] = set()     # (sector, bin) confirmed by rule 5
        self._verify_pending: list[tuple[str, int, str]] = []   # (sector, bin, area) still to fetch

    # -- the interface the runner calls ------------------------------------------------
    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        state = self._ref["state"]
        checks = state.get("completion_checks") or {}
        boundary = checks.get("boundary") or {}
        load = checks.get("backup_load") or {}
        decision = (self._rule1(load) or self._rule2(state, boundary) or self._rule3(state, boundary)
                    or self._rule4(state, boundary) or self._rule5(state, boundary))
        return decision

    # -- helpers --------------------------------------------------------------------
    @staticmethod
    def _decision(rule: int, question: str, targets: list[str], function: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return {"purpose": f"rule {rule}", "information_gaps": [question],
                "gap": {"targets": targets, "question": question},
                "action": {"function": function, "parameters": parameters}}

    def _areas_by_distance(self, state: dict[str, Any], ids: list[str]) -> list[str]:
        meta = state["geography"]["areas"]
        return sorted(ids, key=lambda a: (meta[a].get("nearest_distance_from_site_m", math.inf), a))

    def _unfetched(self, state: dict[str, Any], area_id: str) -> int:
        s = (state.get("summaries") or {}).get(area_id) or {}
        return int(s.get("unqueried") or 0)

    # -- rules ------------------------------------------------------------------------
    def _rule1(self, load: dict[str, Any]) -> dict[str, Any] | None:
        for call in load.get("next_calls") or []:
            if call["cell_ids"]:
                return self._decision(1, "KPI baseline for every cell the redistribution needs", list(call["cell_ids"]),
                                      call["function"], {"cell_ids": list(call["cell_ids"]),
                                                         "start_time": call["start_time"], "end_time": call["end_time"]})
        return None

    def _rule2(self, state: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any] | None:
        named: list[str] = []
        for sector in (boundary.get("sectors") or {}).values():
            for r in sector["bins"].values():
                if r["status"] == "open":
                    named.extend(a for a in (r.get("areas_to_fetch") or []) if self._unfetched(state, a))
        if not named:
            return None
        area = self._areas_by_distance(state, sorted(set(named)))[0]
        return self._decision(2, f"coverage of {area}, the nearest open area", [area],
                              "query_area_coverage", {"area_id": area, "resolution": 10})

    def _rule3(self, state: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any] | None:
        best: tuple[float, str, str] | None = None
        for cell, sector in (boundary.get("sectors") or {}).items():
            for r in sector["bins"].values():
                if r["status"] != "open_at_edge":
                    continue
                strength = r.get("strip_rsrp_max_dbm")
                key = (strength if strength is not None else -1e9, r["label"], cell)
                if best is None or key > best:
                    best = key
        if best is None:
            return None
        _, label, cell = best
        return self._decision(3, f"activity beyond the study-area edge in {label}", [label],
                              "expand_study_area", {"direction": label, "distance_m": EXPAND_STEP_M})

    def _rule4(self, state: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any] | None:
        geometry = read_geometry(state, self._ref["output_dir"])
        meta = state["geography"]["areas"]
        candidates: list[str] = []
        for u in boundary.get("unobserved_directions") or []:
            if not u.get("activity_inside"):
                continue
            b = int(u["bin"])
            for area_id, area in geometry["areas"].items():
                if meta.get(area_id, {}).get("kind") not in ("settlement", "road_corridor") or not self._unfetched(state, area_id):
                    continue
                if any(self._bin_of(geometry, g) == b for g in area["grid_ids"]):
                    candidates.append(area_id)
        if not candidates:
            return None
        area = self._areas_by_distance(state, sorted(set(candidates)))[0]
        return self._decision(4, f"first observation of an unobserved direction through {area}", [area],
                              "query_area_coverage", {"area_id": area, "resolution": 10})

    def _rule5(self, state: dict[str, Any], boundary: dict[str, Any]) -> dict[str, Any]:
        geometry = read_geometry(state, self._ref["output_dir"])
        # Queue one more area beyond each closing area of each closed direction, once per (sector, bin).
        for cell, sector in (boundary.get("sectors") or {}).items():
            for b, r in sector["bins"].items():
                key = (cell, int(b))
                if r["status"] != "closed" or key in self._verified:
                    continue
                self._verified.add(key)
                beyond = self._next_area_beyond(state, geometry, int(b), r.get("closing_area"))
                for area in beyond[:VERIFY_DEPTH]:
                    if self._unfetched(state, area):
                        self._verify_pending.append((cell, int(b), area))
        while self._verify_pending:
            cell, b, area = self._verify_pending.pop(0)
            if self._unfetched(state, area):
                return self._decision(5, f"verification beyond the closing area of {cell} in bin {b}", [area],
                                      "query_area_coverage", {"area_id": area, "resolution": 10})
        return self._decision(5, "every direction confirmed; the checks pass", [], "finish", {})

    # -- geometry -----------------------------------------------------------------------
    @staticmethod
    def _bin_of(geometry: dict[str, Any], grid_id: str) -> int:
        grid, site = geometry["grid"], geometry["site"]
        columns, spacing = int(grid["columns"]), float(grid["spacing_m"])
        row, column = divmod(int(grid_id), columns)
        dx, dy = (column + 0.5) * spacing - float(site["x_m"]), (row + 0.5) * spacing - float(site["y_m"])
        return int(((math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0) // BIN_DEGREES)

    def _next_area_beyond(self, state: dict[str, Any], geometry: dict[str, Any], b: int, closing: str | None) -> list[str]:
        """Activity areas with locations in bin b farther from the site than the closing area's
        nearest location, nearest first."""
        meta = state["geography"]["areas"]
        base = float(meta.get(closing, {}).get("nearest_distance_from_site_m") or 0.0) if closing else 0.0
        found: list[tuple[float, str]] = []
        for area_id, area in geometry["areas"].items():
            if area_id == closing or meta.get(area_id, {}).get("kind") not in ("settlement", "road_corridor"):
                continue
            if not any(self._bin_of(geometry, g) == b for g in area["grid_ids"]):
                continue
            distance = float(meta.get(area_id, {}).get("nearest_distance_from_site_m") or 0.0)
            if distance > base:
                found.append((distance, area_id))
        return [a for _, a in sorted(found)]
```

`completion_checks.json` must carry `next_calls` (2026-10-24),
`areas_to_fetch` (2026-10-21), `unobserved_directions` with `bin` and
`activity_inside` (2026-10-24), `closing_area` and `strip_rsrp_max_dbm`
(2026-10-19) on each bin; all are in place after those changes.

---

## 3. `langgraph_runner.py`: the policy reads the current State

Why: the policy has no context; it needs the State the runner holds. The
runner keeps it in `InvestigationState["state"]`; the policy gets a
reference dict the runner updates.

In `build_investigation_graph`, after `guard = RunGuard(...)`, add:

```python
    policy_ref: dict[str, Any] = {"state": {}, "output_dir": ""}
    if hasattr(model, "_ref"):
        model._ref = policy_ref
```

In `render_context_node`, as its first statement, add:

```python
        policy_ref["state"] = state["state"]
        policy_ref["output_dir"] = state["output_dir"]
```

Nothing else: `llm_call_node` calls `model.complete_json` as before and the
policy's answer goes through `parse_node`, `validate_node` and the rest.
The verifier is off (`run_case.py` passes `verifier=None` for the policy).

---

## 4. `run_case.py`: the option

Add:

```python
    parser.add_argument("--policy", choices=("model", "rules"), default="model",
                        help="rules: the rule policy takes the model's seat (no model, no verifier)")
```

and where the decision model is built:

```python
    if arguments.policy == "rules":
        from outage_harness_langgraph.rule_policy import RulePolicy

        decision_model = RulePolicy({"state": {}, "output_dir": ""})
        verifier = None
    else:
        decision_model = _model(arguments, arguments.model)
```

pass `decision_model` to `run_case_langgraph`, and write
`"policy": arguments.policy` into `task.json` next to the condition (in
`run_case_langgraph`, extend `{**task, "condition": condition}` with the
value the script passes; add a `policy: str = "model"` keyword for it).

---

## 5. `completion_point.py`: record every call's latency

Why: the reference's cost is part of the ground truth. `execute_tool_node`
already stores `duration_s` per tool result (2026-10-19). `end_run` adds
one file.

In `end_run`, before `write_run_log`, add:

```python
    calls = []
    for step_dir in sorted(run_dir.glob("steps/step_[0-9][0-9]")):
        result_file = step_dir / "tool_result.json"
        if result_file.is_file():
            r = json.loads(result_file.read_text(encoding="utf-8"))
            calls.append({"step": int(step_dir.name[-2:]), "tool": r.get("tool"), "duration_s": r.get("duration_s"),
                          "locations": (r.get("details") or {}).get("fetched"), "rows": r.get("row_count"),
                          "status": r.get("status")})
    write_json(run_dir / "calls.json", {"calls": calls,
                                        "point_calls": sum(c["locations"] or 0 for c in calls if c["tool"] == "query_area_coverage"),
                                        "tool_calls": len(calls),
                                        "wall_time_s": sum(c["duration_s"] or 0 for c in calls)})
```

Both policies get it, since both go through `end_run`.

---

## 6. `completion_point.py`: the report is per outage hour (all three packages)

Why: an outage lasts several hours and the estimate is already made per
hour (`run_redistribution` writes one `hours[]` entry per outage hour with
the PRB of every backup and the class of every location). The report then
collapsed it to the worst hour per backup, which hides when a backup is
congested and when it is not, and mixes hours across backups. The report
now shows every hour, and the worst-hour line becomes the summary of the
table under it.

### 6a. Per backup cell, a table of hours

In `final_report`, section 2 ("Why: per backup cell"), find the line that
appends the load sentence for a backup with an estimate:

```python
                     f"limit {LOAD_LIMIT_PERCENT:g}%: {'exceeded' if float(b.get('estimated_prb_percent', 0)) > LOAD_LIMIT_PERCENT else 'within limit'}"
                     f" (worst hour {b.get('worst_hour', 'n/a')}, {b.get('additional_rrc_users', 0):.1f} additional RRC users).")
```

Directly after the `lines.append(text)` that follows it, add:

```python
        hours = (state.get("impact") or {}).get("hours") or []
        rows = []
        for h in hours:
            row = next((p for p in h.get("prb", []) if str(p.get("antenna_id", "")).lower() == backup.lower()), None)
            if row is None:
                continue
            est = float(row.get("new_prb", 0.0))
            rows.append(f"     {h['hour'][11:16]}  baseline {float(row.get('historical_prb', 0.0)):5.1f}%  "
                        f"estimated {est:5.1f}%  +{float(row.get('additional_rrc_users', 0.0)):6.1f} RRC  "
                        f"{'EXCEEDS' if est > LOAD_LIMIT_PERCENT else 'within'}")
        if rows:
            lines.append("     hour   baseline      estimated      moved users   limit")
            lines.extend(rows)
```

`hours[]` holds `hour` as an ISO timestamp; `[11:16]` prints `HH:MM`.

### 6b. The class table per hour

Section 1's table and sentences stay as the worst-hour view, which is
what an operator asks first ("where is it worst"). Below the sentences,
add one line per hour with the class totals of that hour, so the reader
sees how the picture moves through the outage. After the loop that
appends the per-area sentences, add:

```python
    hours = (state.get("impact") or {}).get("hours") or []
    if hours:
        lines.append("")
        lines.append("   Per outage hour (locations by class across all areas):")
        for h in hours:
            counts = {}
            for row in h.get("classes", []):
                counts[row.get("classification", "unknown")] = counts.get(row.get("classification", "unknown"), 0) + 1
            lines.append(f"   {h['hour'][11:16]}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
```

The class names in `hours[].classes` are the engineering model's
(`healthy`, `weak_coverage`, `capacity_limited`, `coverage_hole`); print
them as they are and add one line above the table saying so, because the
harness classes in section 1's table are computed with the harness
thresholds and the two vocabularies differ on purpose.

### 6c. The JSON twin

`final_report.json` already carries `impact` with `hours[]`; nothing to
add. The ground-truth report (to be specified next) uses the same
per-hour table with observed PRB in place of estimated, which is why the
per-hour form goes in now.

### 6d. Check

A completed run's `final_report.md` shows, under each backup with a
baseline, one row per outage hour with baseline, estimated PRB, moved
users and whether the limit is exceeded, and section 1 ends with one
line per hour of class counts. The worst-hour line above the table names
the hour of the highest estimated PRB in it.

---

## 7. Check

1. `python -m outage_harness_langgraph.run_case --policy rules --condition rendered ... --output runs/<site>_rules`
   runs to `end_reason: complete` with no model endpoint configured.
2. `run_log.md`: step 1 is a coverage query of the settlement around the
   site; the KPI baselines are collected in at most two rounds; every
   decision's `purpose` is `rule N`.
3. The last rounds before the finish are rule-5 queries of areas beyond
   the closing areas; `finish` is accepted; `calls.json` exists.
4. On the closed case, the rules run's covered location count is at least
   the rendered run's, and its `calls.json` gives the reference cost.
