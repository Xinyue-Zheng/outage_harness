# Checklist: the rules the harness enforces

Fill in every row of every table for the internal copy of
`outage_harness_langgraph`, and note in the last column whether the two
concat packages hold the same value. Report values from the code, with
file and line; do not run anything and do not attach run outputs. Where
the code differs from the expected column, say so; do not change the
code. Rows marked (report) ask for a behaviour, not a value: answer in
one sentence.

## A. Initialization

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| A1 | settlement disc radii by place type | city 3 000 m, town 2 000 m, village 1 000 m, hamlet 500 m | | | |
| A2 | corridor strip half-width | per the strip rule in build_state0 | | | |
| A3 | frame | FRAME_HALF_WIDTH_M = 30 000, 100 m cells, study square 30 km | | | |
| A4 | ring probe radii | PROBE_RING_RADII_M = (500, 1 000), one point per bin per radius | | | |
| A5 | probe radius | PROBE_RESOLUTION_M = 10 | | | |
| A6 | concat initialization message carries the same facts as rendered state 0 (report) | yes | | | |

## B. Coverage facts

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| B1 | covered location threshold | COVERAGE_RSRP_DBM = -110, serving or not | | | |
| B2 | reachable backup | same sample as an outage sector; not in the outage set; same technology | | | |
| B3 | eligible_backup_cells excludes | only the confirmed outage set, not the site prefix | | | |
| B4 | no-sample location status | `missing`, counted as unknown in every summary | | | |
| B5 | technology patterns | `^[A-Z]{3}\d{5}` LTE, `^[A-Z]{4}\d{6}` NR | | | |
| B6 | query radius offered | AREA_RESOLUTIONS = (10,), schema enum [10] | | | |

## C. Validation

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| C1 | unknown function or area id or parameter outside enum | rejected, reason recorded, round counted | | | |
| C2 | fully queried area | rejected | | | |
| C3 | expansion of a bin that is not edge-open | rejected, message names the right action | | | |
| C4 | KPI call with no named cells | rejected | | | |
| C5 | max_identical_queries | None (cap dropped) | | | |
| C6 | max_consecutive_rejections | 3, end_reason `rejections` | | | |
| C7 | max_tool_calls | 20 | | | |
| C8 | max_time_seconds | 3 600 | | | |
| C9 | max_query_locations default | 1 500 | | | |
| C10 | max_steps default in run_case | (report the value) | | | |

## D. Direction state and boundary

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| D1 | BIN_DEGREES | 30 | | | |
| D2 | MARGIN_BINS | 1 | | | |
| D3 | EDGE_STRIP_M (or EDGE_STRIP_CELLS) | 300 (or 3) | | | |
| D4 | ACCEPT_EDGE_OPEN | False | | | |
| D5 | OBSERVED_RADIUS_M | 2 000 | | | |
| D6 | ACTIVITY_KINDS | {settlement, road_corridor} | | | |
| D7 | closed bin definition (report) | farthest covered location has fetched, sampled, uncovered activity locations beyond it | | | |
| D8 | a bin whose fetched locations all returned no sample (report) | stays unobserved, not closed | | | |
| D9 | each open item names one function and its parameters (report) | yes | | | |

## E. Backup load

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| E1 | REQUIRED_CHECKS | ("boundary", "backup_load") in rendered and concat_checked; backup_load not required in plain concat | | | |
| E2 | cells required | outage sectors plus every co-observed backup | | | |
| E3 | hours required | every outage hour | | | |
| E4 | baseline key written by apply_kpi | `kpi_baselines` | | | |
| E5 | PRB_METRIC, RRC_METRIC | MEAN_PRB_USED, AVG_RRC_USERS | | | |
| E6 | window | kpi_window_for: outage interval plus baseline weeks; one call per technology for all named cells | | | |
| E7 | a cell with no rows after a call (report) | marked missing, listed, not re-required without end | | | |
| E8 | how a run ends when KPI stays missing (report) | cap, auto-stop or program stop: which | | | |

## F. Completion and end of run

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| F1 | finish accepted only when every required check passes | yes | | | |
| F2 | AUTO_STOP_FROM_ROUND | 5 | | | |
| F3 | auto-stop offer placed in the variable part, not the cached prefix | yes | | | |
| F4 | end order | completion, redistribution once, report | | | |
| F5 | report written at cap with end reason | yes | | | |
| F6 | end reasons recorded in run.json | complete, cap (which), rejections, program stop | | | |

## G. Expansion

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| G1 | wedge angle | bin ±15° | | | |
| G2 | distance bounds | 500 to 5 000 m from the current edge | | | |
| G3 | edge_distance_m composes across wedges | yes | | | |
| G4 | OSM for the wedge cached by bounding box; payload copied into the run | yes | | | |
| G5 | expansion offered only for edge-open bins | yes | | | |
| G6 | gap target for expansion | the direction label | | | |

## H. End-of-run computation

| id | rule | expected | actual | file:line | concat same? |
|---|---|---|---|---|---|
| H1 | redistribution | TrafficRedistributionModel, once, in end_run | | | |
| H2 | SIGNAL_MARGIN_DB | 10 | | | |
| H3 | SERVICE_RSRP_DBM | -110 | | | |
| H4 | LOAD_LIMIT_PERCENT | 80 | | | |
| H5 | classes | total_loss, degrade_signal, degrade_capacity, degrade_both, served_by_backup, degrade_unknown | | | |
| H6 | run_log.md has one line per step including step 0 | yes | | | |

## I. The rule policy, and the two decision cores

| id | item | expected | actual | file:line |
|---|---|---|---|---|
| I1 | rule order | KPI, open direction with area, edge-open, unobserved, verify then finish | | |
| I2 | area choice in rule 2 | nearest to the site by centroid distance; tie-break (report) | | |
| I3 | which areas rule 2 considers pending (report) | all activity areas in open bins, or only those the check names | | |
| I4 | EXPAND_STEP_M | 2 000 | | |
| I5 | edge-open bin chosen when several (report) | strongest recorded edge RSRP | | |
| I6 | VERIFY_DEPTH | 1 | | |
| I7 | verification area with no usable evidence (report) | next area beyond, or verified, or terminal: which | | |
| I8 | no farther area in a closed direction (report) | terminal, no expansion | | |
| I9 | KPI retry limit | two proposals per unchanged fingerprint | | |
| I10 | rule policy reads only the state and completion checks, never the rendered text | yes | | |
| I11 | rule decisions pass through the same validator and caps as the model's | yes | | |
| I12 | actions available to the model and not to the rules, or the reverse (report) | none; in particular no "leave area" action on either side | | |
| I13 | each rules step records which rule fired in decision.json | yes | | |
| I14 | a rules run is deterministic: same inputs, same decisions (report) | yes | | |
