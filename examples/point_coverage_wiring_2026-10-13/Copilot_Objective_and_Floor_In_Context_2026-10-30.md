# Objective, cost floor and load item in the context

Apply to `outage_harness_langgraph` only; the rule runner shares the
state and the check but does not read rendered text, so it changes only
where part 1 names it. Synthetic fixtures and tests; no real cases.
Report every change as file and line. Builds on the completion check v3
and on the budget block of `Copilot_Budget_In_Context_2026-10-28.md`.

Why: with a loose round cap the model queries more, batches less and
leaves the KPI baselines unqueried; with a tight cap it converged. The
cap was the only pressure it could see. This change renders the pressure
as computed facts every round: the objective, the minimum work left, the
time budget, and the load item at the same rank as the coverage items.
Nothing in it says which action to take.

## 1. Cost floor in the state

After every step, the program writes `state["floor"]`:

```json
"floor": {
  "items": 3, "actions": 1,
  "locations": 71,
  "kpi_calls": 1,
  "rounds": 3,
  "decision_seconds": 90,
  "service_seconds": 118,
  "assumes": "every sampled location returns a sample; no new coverage found"
}
```

Computed from the open items of the completion check:

| open item | smallest legal action | counted cost |
|---|---|---|
| inside (bin, area) | every unqueried interior location | `inside_unqueried` locations |
| beyond (bin, area), unresolved | a sample beyond F in that bin | `N_MIN_SAMPLED` locations (fewer if fewer remain, then all of them) |
| open at edge | one expansion | 1 call; 0 locations |
| backup_load | one KPI call per technology among required cells | that number of calls |
| finish | one round | 1 round |

`actions` = ceil(coverage items / `MAX_REQUESTS_PER_ACTION`).
`rounds` = `actions` + `kpi_calls` + 1 (finish), minus 1 when both
coverage and KPI items are 0 (finish only). `decision_seconds` = `rounds`
times `decision_s_per_call` from the unit-costs file; `service_seconds`
from the same file's per-location and per-call costs. When no unit-costs
file exists both are null and the rendered line omits the times.

The floor is a lower bound. It never uses the observed sample rate and
never predicts expansion contents. `run.json` records the floor at every
step (`floor_by_step`) and at the end, so a run's spending above the
floor can be read off afterwards. The rules runner writes the same
record; its selector does not read it.

## 2. Objective sentence in the cached prefix

Add to the investigation skill, as the last sentence of the task
statement:

"A run is scored on the locations queried and the time used, and it
counts only when the completion checks pass. Finish as soon as they
pass."

No other sentence is added to the skill.

## 3. Floor line in the progress block

Directly under the completion-progress lines, one block, fixed wording:

```
To finish from here (if nothing new is found): 3 open items fit in 1 action, at least 71 locations;
  backup_load needs 1 KPI call; then finish. At least 3 rounds, about 90 s of decision time and 118 s of service time.
```

With no unit-costs file, the second sentence ends after "3 rounds". When
the only open item is finish: `To finish from here: every check passes;
finish is legal now.`

## 4. Load item at the same rank as coverage items

The `backup_load` requirement is rendered as an open item in the open
items block, in the position its bin-less kind gets: after the inside
items and before the beyond items. Fixed form:

```
Open (load): 5 required cells without baselines (3 outage sectors, B1, B2). Legal now: query_kpi LTE (1 call, about 25 s). Required before finish.
```

With two technologies, two lines, one per technology. The phrase "Legal
now" is literal: the validator already accepts a KPI call at any round;
this change makes that visible. When every required cell has a baseline
or is recorded missing after a successful call, the item is absent.

## 5. Time budget rendered as used and left

The budget block's time line becomes
`time          410 s of 1800 s used, 1390 left`, in the same form as the
locations line. `max_time_seconds` is set per case from the launch script
and recorded in `run.json`; the round cap stays as a guard and is not
rendered with a "left" value.

## 6. Tests

1. Floor arithmetic: a fixture with 2 inside items (41 and 30
   locations), 1 unresolved beyond item, 1 KPI technology gives
   `locations 81`, `actions 1`, `kpi_calls 1`, `rounds 3`; with a
   unit-costs file of 1.3 s per location, 25 s per KPI call and 20 s per
   decision, `service_seconds 130` and `decision_seconds 60`.
2. The same fixture renders the floor block of part 3 character for
   character; without a unit-costs file the time sentence is omitted.
3. A fixture where every check passes renders the finish-only line.
4. The load item appears between inside and beyond items, with the cell
   counts and the call count; two technologies give two lines; it is
   absent once baselines are complete.
5. The time line shows used, limit and left.
6. `run.json` holds `floor_by_step` with one entry per step and the
   objective sentence is present in the rendered prefix.

## Question to answer with the report

The current position of the KPI requirement in the rendered open items
(file and line), so the change log states where it moved from.
