# Copilot baseline: the server reads the case only from `case.json` (instruction for the Copilot)

A small change to `outage_harness_copilot/server.py` and, if needed,
`summary.py`. Change nothing else. Write no tests. Make no data call.

Why. The case of the baseline must not depend on the stored harness run
or on the reference folder. The stored harness run has a different
case, and the reference folder is the answer key. The author writes the
case once, in one file in the run folder.

## 1. The file

The author writes `<run folder>/case.json` before the run:

```json
{
  "down_cells": ["<exact cell ID>", "<exact cell ID>"],
  "outage_start": "<start time>",
  "outage_end": "<end time>"
}
```

The two times use the format of the harness task (`start_time`,
`end_time`). The server never writes or changes this file.

## 2. The server

1. At start, read the case from `<run folder>/case.json` and from
   nowhere else. If the file is missing, a field is missing, a time
   does not parse, or `down_cells` is empty, exit with an error that
   names the file and the field. Do not fall back to another source.
2. Remove the reference folder argument and every read of the reference
   folder from the package. After the change, the word "reference" does
   not occur in `server.py`.
3. `--harness-run` stays, for the limits (`run.json.limits`) and the
   caches only. The server does not read a ticket, a down cell or a
   time from it.
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

If `summary.py` reads the limits from `case.json`, change it to take
them from the last budget record in `records/calls.jsonl`.

## 3. Report back

The changed lines as file and line. The output of a search for
"reference" and for "prefix" in the package after the change. Whether
the server started with a `case.json` and listed its tools. The new
argument list of the server, as its help text prints it.
