# Baseline: GitHub Copilot CLI as the whole agent, one case, end to end (instruction for the Copilot)

**Replaced on 2026-11-13 by `Copilot_Baseline_Copilot_MCP_One_Prompt_2026-11-13.md`. Do not apply this file.** It assumes billing per prompt; Copilot is billed by tokens since June 2026. The new design uses agent mode in the VS Code chat view with MCP tools and a skill, and one prompt.

Apply to the repository that holds `outage_harness_langgraph`,
`outage_harness_rule_based` and `outage_harness_evolution`. This adds one
baseline condition: a frontier coding agent (GitHub Copilot CLI) given the
same stored data, the same raw tools, the same budget and the same case as
a harness run, with no harness. It gets no rendered state, no validator
beyond parameter checks and the budget, no completion check and no skill
text. It gets a task description, a tool client and a working directory,
and it may write and run its own code. The outputs are a tool-call trace
with every point query, a token and premium-request report, the wall time,
the final classification, and a comparison against the harness run on the
same case and against the reference of
`Copilot_Reference_Full_Scan_2026-11-10.md`.

Why. The comparison "mid-size local model plus harness" against
"frontier agent without harness" is the one the evaluation needs most and
the one no explanation replaces. The condition is run once, on one case,
with a hard cap on prompts, because every prompt costs a premium request.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory, any file in the
  three harness packages (`outage_harness_langgraph`,
  `outage_harness_rule_based`, the concat packages),
  `outage_harness_evolution`.
- Do not run `uv sync` and do not add dependencies. The server uses
  `http.server` from the standard library; the client uses `urllib`.
- New code goes into a new package `outage_harness_copilot/` with four
  modules: `server.py`, `client.py`, `runner.py`, `compare.py`, and a
  `tests/` directory. It imports the harness packages read-only: the
  point client behind `query_point_coverage`, `point_coverage.grid_center`
  and the grid construction, `query_osm_landuse`, the two KPI clients,
  `query_basic_information`, and the constants of `completion_point`.
  If a function cannot be called without the harness state, stop and
  report which one; do not copy harness code.
- Tests write only under `tmp_path`.
- Outputs go to `<results root>/copilot/<case>_<YYYY-MM-DD>/`.
- Point and KPI calls go through the same caches the harness uses
  (`point_cache.jsonl` keyed `grid_id|radius_m|epoch`, the KPI cache). A
  cached item is served from the cache; an uncached item is fetched live
  and written to the cache, exactly as a harness run does. Nothing else
  writes to the caches.

Run as

```
python -m outage_harness_copilot.runner --harness-run <run dir of the harness run on this case> --out <results root>/copilot [--dry-run] [--max-prompts 5]
python -m outage_harness_copilot.compare <copilot run dir> <harness run dir> [--reference <reference dir>]
```

Every number written comes from a tool result, a server record, a file
Copilot CLI wrote, or a number the author pasted from the GitHub usage
page. An absent number is `not recorded`, never an estimate.

## 0. Constants, all at the top of `runner.py`

| name | value | meaning |
|---|---|---|
| `GRID_M` | 100 | the harness grid; every charged location is one grid cell |
| `SCAN_RADIUS_M` | 10 | the only radius the point tool serves |
| `MAX_POINTS_PER_CALL` | 500 | coordinates one point call may carry |
| `MAX_PROMPTS` | 5 | prompts sent to Copilot CLI in one run, the first one included; the CLI flag `--max-prompts` overrides |
| `SERVER_HOST`, `SERVER_PORT` | `127.0.0.1`, 8765 | the tool server; `--port` overrides |
| `COPILOT_BIN` | `copilot` | the CLI; environment variable `COPILOT_BIN` overrides |
| `COPILOT_MODEL` | unset | passed to the CLI model flag when set; recorded either way |
| limits | read from the harness run | `max_query_locations`, `max_kpi_cell_queries`, `max_time_seconds` from `run.json.limits` of `--harness-run`; the same three values, never retyped |
| the case | read from the harness run | the ticket (down cell, outage interval, supplied prefixes) from the harness run's task record |
| thresholds | imported from `completion_point` | `COVERAGE_RSRP_DBM`, `SIGNAL_MARGIN_DB`, `LOAD_LIMIT_PERCENT`, `SERVICE_RSRP_DBM` |

## 1. Data confinement

Copilot CLI has a shell. The baseline is valid only if every stored
sample it sees came through the tool server, so that `calls.json` is the
complete record of what it read.

1. The working directory `<run dir>/workspace/` holds only `TASK.md`
   (part 3), `tool.py` (the client, part 2) and what Copilot writes.
   The stored data, the caches, the harness packages and the harness run
   directories are outside it.
2. The server runs as a separate process started by the runner, holds
   the data paths, and listens on localhost. The client never receives a
   data path.
3. The CLI is launched with permission flags that allow the shell only
   for `python tool.py` and `python <files in the working directory>`,
   allow file writes only inside the working directory, and deny every
   other tool. Read the installed CLI's `--help` for the exact flag names
   (`--allow-tool`, `--deny-tool` and their pattern syntax at the time of
   writing). If the installed version cannot express this, stop and
   report what it can express; do not run with `--allow-all-tools`.
4. After the run, `runner.py` audits the session transcript (part 5):
   every shell command Copilot ran is listed in `audit.json`. A command
   that is not `python tool.py ...` and not a Python file inside the
   working directory marks the run `audit: failed` with the command, and
   `compare.py` refuses to score it. The run is reported as void, not
   repaired.

Point 3 is policy and point 4 is the check on it. Together they are the
confinement; nothing else is.

## 2. The tool server and the client

`server.py` exposes the raw tools of the harness executor, one route
each, JSON in and JSON out. It does not know areas, bins, wedges or
completion; those are harness constructs. It knows the budget.

| route | parameters | returns | charge |
|---|---|---|---|
| `basic_information` | `cell_id` | what `query_basic_information` returns | none |
| `osm_landuse` | `south, west, north, east` (degrees) | what `query_osm_landuse` returns for that box, from the cache when the box lies inside a cached window, else live; the raw elements with their tags, not areas | none; `osm_calls` counted |
| `point_coverage` | `points: [{lat, lon}]`, at most `MAX_POINTS_PER_CALL` | per point: `grid_id`, the grid centre actually fetched, the samples the point API returned at `SCAN_RADIUS_M` (serving sector and neighbours with RSRP, unchanged), `cached: true/false` | one location per grid id not charged before in this run; a repeated grid id is free, as in the harness |
| `lte_rrc_prb`, `nr_rrc_prb` | `cell_ids, start_time, end_time` | hourly rows as the harness KPI tools return them | one cell-query per cell named, as in the harness |
| `budget` | none | the budget record below | none |
| `final_report` | the report body (part 4) | `{"accepted": true}` or the schema errors | none |

A point whose call fails after the client's own retries is returned as
`error` and is not charged, as in the harness.

Every request snaps each coordinate to the nearest grid centre with the
harness grid function and fetches that centre; the response says which
grid id and centre were used so Copilot can see the snapping. A radius
is not a parameter. A request past the location or cell-query limit is
rejected whole with `{"rejected": "query_budget", "cost": n, "left": m}`
and charged nothing. A parameter the schema does not know, a malformed
coordinate, a cell id of the wrong technology for the route, or an
unknown route is rejected with the reason; the server never guesses.

The budget record, returned by every route next to its result:

```json
"budget": {"locations_used": 640, "locations_limit": 1500,
           "kpi_cell_queries_used": 12, "kpi_cell_queries_limit": 200,
           "seconds_elapsed": 412, "seconds_limit": 12000}
```

The server appends one entry per request to `<run dir>/calls.json`:
`index`, `route`, `received_at`, `seconds`, the parameters as received,
`grid_ids_charged`, `grid_ids_free`, `cached`, `live`, `cell_queries`,
`rows`, `rejected` with reason, `response_bytes`. It also appends every
sample it returned to `<run dir>/samples.jsonl`, keyed by grid id, so the
classification of part 6 is recomputed by the program from what Copilot
was shown, not from what Copilot wrote.

`client.py` is the file placed in the workspace as `tool.py`:

```
python tool.py <route> '<json parameters>'
```

It posts to the server and prints the JSON response. About forty lines,
standard library only, no data path, no logic.

## 3. The task description

`TASK.md` is the only prompt. `runner.py` writes it from a template in
the package, filling the ticket, the limits, the tool table of part 2
with one example call per route, the output schema of part 4, and the
rule that the report is written with the `final_report` route before the
agent stops. The semantic text is taken verbatim from the sections
"Purpose", "Evidence and scope", "KPI baseline" (the window rule only,
not the computed windows) and the land-use sentence of the skill text
`investigation_skill_point.txt`, so the baseline reads the same data
semantics the harness model reads. It does not contain the "Area
importance", "Choosing an action", "Inspection and completion" or
"Decision format" sections: those are the harness's policy and are what
the baseline is run without. Add nothing else. In particular, no list of
areas, no bins, no ordering advice, no definition of done beyond the
output schema and the budget.

The template is written once. If the dry run (part 7) shows a mechanical
defect in it (a wrong example call, a schema error), fix that line and
record the change in `prompts.json`; do not tune the wording after the
real run has started. The run directory keeps `TASK.md` as sent.

## 4. The output schema

The `final_report` route accepts one JSON object:

| field | content |
|---|---|
| `outage_sectors` | the cell ids the agent treated as outage sectors |
| `locations` | one entry per grid id the agent classifies: `grid_id`, `class` in `covered_backup`, `covered_no_backup`, `not_covered`, `no_sample`, `backups` (cell ids it holds reachable there) |
| `backups` | per backup cell: `prb_estimate` per outage hour, `rrc_estimate` per outage hour, or `no_data` |
| `summary` | free text, at most 4000 characters |

The server validates the shape, the class names and that every grid id
in `locations` was returned by a point call of this run; a grid id that
was never fetched is a schema error named in the response, and the
report is not accepted until it is removed. It records nothing else about
the content.

## 5. The runner

`runner.py`, in order:

1. Reads the harness run: ticket, limits, the caches' location, the
   epoch. Creates `<run dir>` and `workspace/` with `TASK.md` and
   `tool.py`.
2. Starts the server; waits until `budget` answers.
3. Records `cli_version` (the CLI's version output), `model` (the model
   flag or `not recorded` when the CLI does not print it), `started_at`.
4. Sends prompt 1, non-interactive: the CLI's prompt flag with the text
   "Read TASK.md and carry out the task. Call the final_report route
   before you stop." and the permission flags of part 1. Waits for the
   process to end or for `max_time_seconds` since `started_at`, then
   kills it and records `end_reason: time_cap`.
5. If the process ended, the report was not accepted, the time cap is
   not reached and the prompt count is below `MAX_PROMPTS`: sends the
   next prompt, resuming the same session with the CLI's resume flag:
   "Continue the task. The budget is `<budget record>`. Call the
   final_report route before you stop." A report accepted ends the run
   with `end_reason: report`. The prompt count reaching `MAX_PROMPTS`
   without a report ends it with `prompt_cap`. Every prompt is appended
   to `prompts.json` with its text, time sent, time ended, exit code and
   session id.
6. Stops the server. Copies the session transcript the CLI keeps (find
   its location from the CLI documentation or its state directory and
   record the path used) to `<run dir>/transcript/`. Copies `workspace/`
   as it is, Copilot's scripts included; they are part of the trace.
7. Audits the transcript (part 1, point 4) into `audit.json`.
8. Writes `run.json`: `end_reason`, `limits`, the final budget record,
   `prompts` count, `seconds.total` (wall clock from `started_at` to the
   last process end), `seconds.tools` (the sum of server `seconds`),
   `seconds.other` (the difference: Copilot's own thinking, its own
   script runs and the CLI's overhead; the transcript may allow a finer
   split, and if it carries timestamps per event, record `seconds.agent`
   and `seconds.scripts` from them, else `not recorded`), `cli_version`,
   `model`, `audit`.

Usage. The CLI's usage report (the `/usage` command in a session, or
the usage fields in the transcript, whichever exists) goes into
`usage.md` with the source named: input tokens, output tokens, premium
requests, per prompt where available. The author adds, by hand, the
premium-request count from the GitHub usage page before the dry run,
before the real run and after it, with the time of reading. A number
that no source gives is `not recorded`.

## 6. Comparison

`compare.py <copilot run dir> <harness run dir> [--reference <dir>]`
refuses an audited-failed run and otherwise writes
`<copilot run dir>/compare/`:

1. `resources.md`: one table, columns Copilot and harness, rows:
   locations charged, covered locations found (an outage sector listed
   at or above `COVERAGE_RSRP_DBM` at the grid id, computed by the
   program from `samples.jsonl` and from the harness state), KPI
   cell-queries, OSM calls, tool calls, rejected calls, prompts or
   decision calls, input tokens, output tokens, seconds total, seconds
   tools, seconds other or decision, end reason. The harness values come
   from `run.json` (`budget`, `resources`, `decisions`) and the last
   state.
2. `classes.md`: the program classifies every grid id each run fetched
   with the rules of `Evaluation_From_Stored_Data_2026-10-25.md` section
   1 from the stored samples and stored KPI, the same function for both
   runs. Table per class: count in the Copilot run, count in the harness
   run, count in both, agreement on the grid ids both fetched. With
   `--reference`: per-class precision and recall of each run against the
   reference, the same rows the scorer `evolution score-reference` gives,
   by calling that scorer's functions on the recomputed records if they
   accept a record, else by writing the records in the layout it reads.
3. `claims.md`: Copilot's own `locations` against the program's
   classification of the same grid ids: the count and share of grid ids
   whose reported class differs from what its own samples support, and
   the count of reported backups not listed in any sample at that grid
   id. This is the unsupported-claim rate; the harness run's report is
   scored the same way.
4. `order.geojson`, one per run: every charged grid id as a point with
   `order` (the index of the call that charged it), `covered` and
   `class`. One file each, so the query sequences can be drawn side by
   side in any viewer. `order.md`: the budget spent and the covered
   locations found after each tenth of the location budget, both runs,
   one table.

No picture generation beyond the GeoJSON; the pictures are made by hand
from it for the slides.

## 7. Tests, synthetic only

1. The server charges a grid id once: two calls with the same
   coordinate charge one location; the second response says `cached`.
2. Two coordinates in the same 100 m cell charge one location and
   return the same grid id and centre.
3. A point call that would exceed the location limit is rejected whole
   and charges nothing; `calls.json` holds the rejection with its cost.
4. A KPI call charges one cell-query per cell named; an LTE id on the
   NR route is rejected with the reason.
5. `final_report` rejects a grid id that was never fetched, an unknown
   class name, and a missing field, each with the field named.
6. The audit flags a transcript line with `cat <path outside workspace>`
   and passes one with only `python tool.py` and `python plan.py`.
7. The runner with a fake CLI (a script that prints a transcript and
   exits) records `prompt_cap` after `MAX_PROMPTS` prompts without a
   report, `report` when the fake calls `final_report`, and `time_cap`
   when the fake sleeps past a 2-second limit.
8. `compare.py` on two synthetic run directories produces the four
   outputs and the same class for a grid id present in both.

Run the tests with `uv run pytest outage_harness_copilot/tests` and the
gate `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`
on the new package only.

## 8. Run it

1. Dry run: `--dry-run` points the server at fixture F1 of the
   completion check tests, served through the fake point source those
   tests use, with a location limit of 300 and a time limit of 600
   seconds, and sends at most 2 prompts. This checks the flags, the
   confinement, the transcript location and the usage source. Read
   `audit.json` and `usage.md`. Fix mechanical defects only. Record the
   premium requests it consumed.
2. The real run, once, on the same case the reference of
   `Copilot_Reference_Full_Scan_2026-11-10.md` is being built for, with
   `--harness-run` pointing at the model-core run on that case. Do not
   start it while another run is using the point API, and do not start
   a second real run.
3. `compare.py` against the model-core run, and against the rule-core run
   on the same case if one exists, with `--reference` if the reference
   directory is complete, else without, saying so.

## 9. Report back

Change list as file and line. Then:

1. The exact CLI command line used, with the permission flags, and the
   CLI's `--help` lines that define them.
2. `audit.json`: pass or fail, and every shell command Copilot ran.
3. `usage.md` as written, with sources.
4. `run.json`, `resources.md`, `classes.md`, `claims.md`, `order.md`.
5. The list of files Copilot wrote in `workspace/` with one line each on
   what they do, from reading them.
6. What the transcript does and does not carry: timestamps, token counts,
   model name, so the next run knows what can be recorded.
7. Anything the CLI could not do as specified (a flag missing, a
   transcript not found, a resume that started a new session). State it;
   do not work around it silently.
