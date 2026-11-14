# Copilot baseline: the server reads the case and the limits only from `case.json` (instruction for the Copilot)

A small change to `outage_harness_copilot/server.py` and, if needed,
`summary.py`. Change nothing else. Write no tests. Make no data call.

Why. The baseline must not point at any other run. The stored harness
run has a different case, and the reference folder is the answer key.
The author writes the case and the limits once, in one file in the run
folder. After this change the server takes one argument, `--run-dir`,
and no directory of a harness run or of the reference appears in
`mcp.json` or in the package.

## 1. The file

The author writes `<run folder>/case.json` before the run:

```json
{
  "down_cells": ["<exact cell ID>", "<exact cell ID>"],
  "outage_start": "<start time>",
  "outage_end": "<end time>",
  "limits": {
    "max_query_locations": 0,
    "max_kpi_cell_queries": 0,
    "max_time_seconds": 0,
    "max_tool_calls": 200
  }
}
```

The two times use the format of the harness task (`start_time`,
`end_time`). The server never writes or changes this file.

## 2. The server

1. At start, read the case and the four limits from
   `<run folder>/case.json` and from nowhere else. If the file is
   missing, a field is missing, a time does not parse, `down_cells` is
   empty, or a limit is not a positive integer, exit with an error that
   names the file and the field. Do not fall back to another source and
   do not use a default limit.
2. Remove the `--harness-run` argument and the reference folder
   argument, and every read of a harness run directory or of the
   reference folder. After the change, a search for "reference" and for
   "harness_run" in the package finds nothing.
3. The caches. The server still reads coverage, KPI and map data
   through the same caches as the harness. Find them the way the
   harness packages find them by default (their own configuration or
   functions), not through a run directory and not through a new
   argument. If the caches can only be found through a run directory,
   stop and report; do not add a path argument.
4. The outage cells are exactly `down_cells`. No prefix is matched. A
   cell of the same site that is not in the list is in service and can
   be a backup. Pass exactly this set to the classification function
   and to the backup eligibility function.
5. The down sites come from the site lookup of the cells in
   `down_cells`, numbered in the order of first appearance. The outage
   hours and the eight KPI windows are computed from the two times with
   the harness functions, as before.
6. `get_case` returns the down cells, the sites, the interval, the
   outage hours, the KPI windows and the limits, all from the above.
7. Bump `COPILOT_BASELINE_VERSION`.

If `summary.py` reads the limits from another place, change it to take
them from `case.json`.

## 3. Report back

The changed lines as file and line. The output of a search for
"reference", "harness_run" and "prefix" in the package after the
change. How the server now finds the caches. Whether the server started
with a `case.json` and listed its tools. The new argument list of the
server, as its help text prints it.
