# Change of 2026-10-25: backup_load requires the outage sectors and the co-observed backups only

All three packages, `completion_point.py`. Applies on top of the
2026-10-20 (`backup_load_status` with outage hours) and 2026-10-24
(one-call line) changes.

## 1. Why

`backup_load` required a baseline for every backup candidate seen in
coverage. Since the ring probe, every neighbour cell within a kilometre of
the site is seen from round 1, so the requirement covers cells that are
listed at a few probe locations and are never a backup for any outage
traffic. The redistribution only moves traffic to a backup observed in the
same sample as an outage sector at a covered location; a cell observed
elsewhere receives nothing and its baseline is never read. The check now
asks for exactly those cells: the outage sectors, and every eligible backup
observed in the same sample as an outage sector at some location where the
sector covers at or above the threshold. Nothing else is required; other
cells seen in coverage are reported as "seen, not a backup here".

The per-area summaries already count this co-observation per cell as
`with_down_cell`, so the set is the union over the study area's valid
locations, computed from the coverage table.

## 2. `completion_point.py`

### 2a. The co-observed backup set

Add after `kpi_queried_cells`:

```python
def coobserved_backups(state: dict[str, Any], is_outage: IsOutage, eligible_backups: EligibleBackups) -> list[str]:
    """Eligible backup cells observed in the same sample as an outage sector listed at or above
    COVERAGE_RSRP_DBM, at any valid location. These are the cells the redistribution can move
    traffic to, and therefore the cells whose baseline the report needs."""
    found: set[str] = set()
    for entry in (state.get("coverage") or {}).values():
        if entry.get("status") != "valid":
            continue
        for sample in entry.get("samples") or []:
            cells = sample.get("cells") or {}
            if not any(is_outage(c) and r >= COVERAGE_RSRP_DBM for c, r in cells.items()):
                continue
            found.update(c for c in cells if not is_outage(c))
    return sorted(eligible_backups(found))
```

### 2b. `backup_load_status` takes the predicates and requires that set

Find the signature and the first lines:

```python
def backup_load_status(state: dict[str, Any]) -> dict[str, Any]:
    """Required: every outage sector and every backup candidate has a KPI baseline slot for
    every outage hour, for RRC and PRB. Queried with no rows is missing (reported, does not
    block); never queried blocks; queried but with an outage hour absent blocks and names it."""
    outage = sorted(state.get("outage_cells") or [])
    candidates = sorted(state.get("backup_candidates") or [])
    required = outage + [c for c in candidates if c not in outage]
```

Replace with:

```python
def backup_load_status(state: dict[str, Any], is_outage: IsOutage, eligible_backups: EligibleBackups) -> dict[str, Any]:
    """Required: every outage sector, and every eligible backup observed in the same sample as
    an outage sector at a covered location, has a KPI baseline slot for every outage hour, for
    RRC and PRB. Queried with no rows is missing (reported, does not block); never queried
    blocks; queried but with an outage hour absent blocks and names it. Other cells seen in
    coverage are not required: the redistribution never reads their baseline."""
    outage = sorted(state.get("outage_cells") or [])
    candidates = coobserved_backups(state, is_outage, eligible_backups)
    seen_only = sorted(set(state.get("backup_candidates") or []) - set(candidates))
    required = outage + [c for c in candidates if c not in outage]
```

and add to the returned dict:

```python
            "seen_not_required": seen_only,
```

Every caller passes the two predicates. In `completion_evidence_status`,
find `"backup_load": backup_load_status(state)` and replace with
`"backup_load": backup_load_status(state, is_outage, eligible_backups)`;
give `completion_evidence_status` the keyword
`eligible_backups: EligibleBackups` after `is_outage`, and pass it at every
call site (`finish_check`, `program_stop`, `end_run`, `write_cap_node`,
`update_state_node`, the demo and the tests). The runner already builds
both lambdas from `task` next to those calls.

### 2c. The progress line says what is not required

In `progress_lines`, after the `backup_load` lines (and the one-call lines
of 2026-10-24), add:

```python
    seen_only = load.get("seen_not_required") or []
    if seen_only:
        lines.append("  Seen in coverage but never together with an outage sector, no baseline needed: " + ", ".join(seen_only) + ".")
```

### 2d. The report

In `final_report`, section 2 lists cells that are "observed but not an
eligible backup, or never the strongest living backup". Extend that line
with the reason from the check when the cell is in `seen_not_required`:
"observed in coverage, never in the same sample as an outage sector; no
baseline required".

## 3. The skill text (all three)

In the KPI baseline paragraph, replace "Query the outage cells and the
backup candidates" with "Query the outage cells and the backup candidates
the completion progress names: the cells observed together with an outage
sector. Cells seen only elsewhere need no baseline."

## 4. Check

1. After the ring probe, the first `backup_load` line lists the outage
   sectors and only the backups co-observed with them, and a second line
   lists the cells seen but not required.
2. `coobserved_backups` equals the set of cells with `with_down_cell > 0`
   in the study-area summary (same definition, two computations; the test
   asserts equality on the synthetic case).
3. A run collects the baselines in at most two KPI rounds (one per
   technology) when it follows the one-call line.
