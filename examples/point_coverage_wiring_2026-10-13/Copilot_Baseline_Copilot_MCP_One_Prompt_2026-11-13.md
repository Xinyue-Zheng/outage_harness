# Baseline: Copilot agent mode with MCP tools and a skill, one prompt, one case (instruction for the Copilot)

Apply to the repository that holds `outage_harness_langgraph`,
`outage_harness_rule_based` and the concat packages. This adds one
baseline: GitHub Copilot in agent mode in the VS Code chat view, with a
frontier model, gets the case in one prompt, the domain knowledge in one
skill, and the data through one MCP server. It works without the
harness and without a person until it submits a report.

This file replaces `Copilot_Baseline_Copilot_CLI_2026-11-11.md`. Do not
apply that file.

```
  prepare.py                                    program, before the session
     | reads the stored harness run: ticket, limits, caches
     | builds the areas and their 100 m locations
     | writes workspace/ (skill, MCP registration) and PROMPT.md
     v
  The author, in VS Code                        by hand, once
     | opens workspace/, selects agent mode and the model,
     | enables only the tools of the `outage` server,
     | pastes PROMPT.md and sends it             <- the one prompt
     v
  Copilot agent  --- tool call --->  MCP server `outage`        program
     ^   one model step per call        | selects unread locations
     |                                  | reads them through the caches
     +------ compact result ------------+ charges, rejects past a limit
     |                                  | records every call and sample
     | ... up to 200 tool calls, no human input ...
     | submit_report  -> checked for format, stored, run over
     v
  The author: exports the session log, reads the credits
  collect.py: audit, usage, run.json, classes and report by the program
  compare.py: this run against the stored harness runs
```

## What one prompt means

The author sends one message. Inside that one turn the agent calls
tools by itself, up to 200 times, and ends with `submit_report`. The
author types nothing else. If the agent stops and asks a question,
nobody answers and the run ends without a report.

Why one prompt. A harness run is unattended, so this run is unattended.
A second message from a person would add that person's judgment to the
result. One prompt is also the cheapest form: every message makes the
model read the whole conversation again.

## What this baseline shares with the harness runs, and what it lacks

| part | harness with LLM policy | this baseline |
|---|---|---|
| case, limits on locations, KPI cell-queries and seconds | from the ticket and the run configuration | the same values, read from the stored harness run |
| data sources and caches | point API, KPI, map | the same clients and the same caches |
| areas and the 100 m grid | built by the program | built by the same builder |
| charge | one per new location, one per cell named | the same |
| class of a read location | computed by the program | computed by the same function, returned with each read |
| domain knowledge | the skill text | the same knowledge in `SKILL.md`, the completion rule included, as prose |
| model | mid-size local model | frontier model in Copilot |
| what the model reads | text rendered from the whole state, each round | the conversation so far: its own replies and the tool results |
| record of what was read so far | the State | none; the agent keeps its own |
| list of open items and valid actions | printed each round | none |
| who decides that the run is complete | the completion check | the agent |
| who writes the numbers of the report | the program | the agent; the program recomputes them afterwards |

The rule for the tools follows from this table: **a tool returns what
one call observed. It never returns what the run has observed so far,
what is still open, which action is valid, or whether the run is
complete.** Those four are what the harness adds, and they are what this
baseline runs without. The budget record is the one exception, because
the limits must be enforceable and visible in every condition.

Why the tools return classes and not raw samples. A competent engineer
who builds an MCP server for this task computes every deterministic
value in code. If the model had to compare RSRP values by eye, a worse
result would show a weak tool, not a missing harness.

Why no terminal. The agent gets no shell and no file tools. Then every
value it sees passes through the server, so the server's record is the
complete record, and no audit of shell commands is needed. The cost is
that this baseline is the tool-calling recipe (skill and MCP), not a
coding agent that writes its own programs. Say so wherever the result is
shown.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory, any file in the
  harness packages, the concat packages or `outage_harness_evolution`.
  The existing MCP server of the concat packages is not edited; import
  from it.
- Do not run `uv sync` and do not add dependencies. Use the MCP library
  that the existing server already uses.
- New code goes into a new package `outage_harness_copilot/` with five
  modules, `tools.py`, `server.py`, `prepare.py`, `collect.py`,
  `compare.py`, two text files, `SKILL.md` and `PROMPT_TEMPLATE.md`, and
  a `tests/` directory. It imports the harness packages read-only. If a
  harness function cannot be called without the harness State, stop and
  report which one. Do not copy harness code.
- Tests write only under `tmp_path`.
- Outputs go to `<results root>/copilot/<case>_<YYYY-MM-DD>/`.
- Point and KPI calls go through the caches the harness uses. A cached
  item is served from the cache; an uncached item is fetched live and
  written to the cache, as a harness run does.
- Do not start a real run while another run is using the point API.
- The package has a version string `COPILOT_BASELINE_VERSION`, bumped by
  hand at every change of the tools, the skill or the prompt template,
  and written to `run.json`.

Run as

```
python -m outage_harness_copilot.prepare --harness-run <run dir of a harness run on this case> --out <results root>/copilot [--dry-run]
python -m outage_harness_copilot.collect <copilot run dir> --log <exported session log> --chat <exported chat> --credits-before <n> --credits-after <n>
python -m outage_harness_copilot.compare <copilot run dir> <harness run dir> [<harness run dir> ...]
```

VS Code starts the server itself, from the registration that
`prepare.py` writes:

```
python -m outage_harness_copilot.server --run-dir <copilot run dir>
```

Every number written comes from a tool result, a server record, the
exported log, or a number the author typed from the billing page. An
absent value is `not recorded`.

## 0. Report first, from the code and the installed VS Code, before any edit

1. The existing MCP server (`mcp_server.create_mcp_server` in the concat
   package): the library and its version, the tools it registers with
   their parameters, and which transports the library offers. VS Code
   needs a server it can start as a process (stdio).
2. Whether these can be called without a harness State, and their
   signatures: the site lookup, the builder of the activity areas and
   their locations for the whole frame (the same builder
   `Copilot_Baseline_Algorithm_Only_2026-11-13.md`, part 1, names), the
   point fetch helper, the function that classifies one location from
   its samples, the eligibility function for backups, the function that
   computes the KPI windows, the function that turns hourly KPI rows
   into the per-hour baseline, the two KPI clients with their parameter
   checks, and the end-of-run functions (classes, load estimate,
   report).
3. In the installed VS Code and Copilot Chat: the version; how a skill
   is loaded (which folder, which setting, and whether loading needs a
   built-in file tool); whether a custom agent file can restrict the
   tool list; the name and value of the setting that limits requests
   per turn; the default timeout of one MCP tool call; and whether the
   agent debug log can be exported and what it holds (model requests,
   tool calls with input and output, token counts, cached token counts,
   timestamps, model name).
4. Whether any instruction file, memory or other MCP server is active
   at user level and would be loaded in a new window.

## 1. Constants, at the top of `tools.py`

| name | value | meaning |
|---|---|---|
| `LOCATIONS_PER_CALL_MAX` | 50 | locations one `read_coverage` call may return |
| `AREAS_PER_CALL` | 50 | areas one `list_areas` call returns |
| `CELLS_PER_KPI_CALL_MAX` | 20 | cells one `read_kpi` call may name |
| `CELLS_PER_ROW` | 3 | backup cells printed per location row; the rest is a count |
| `MAX_TOOL_CALLS` | 200 | tool calls the server answers in one run, rejected calls included |
| limits | read from `--harness-run` | `max_query_locations`, `max_kpi_cell_queries`, `max_time_seconds` from `run.json.limits`; never retyped |
| the case | read from `--harness-run` | the ticket: down cells, outage interval, supplied prefixes |
| thresholds | imported from `completion_point` | the coverage threshold, the signal margin, the load limit, the count of sampled locations that closes an area, the two reach distances, the width of a direction sector |

`MAX_TOOL_CALLS` protects the credit budget: each tool call is one model
step, and each step reads the whole conversation again. The harness has
no such limit. If a run ends on it, the result table says so.

## 2. The areas and locations (`prepare.py`)

The agent works on the same set of locations as the algorithm baseline:
every location of every activity area, settlement area and road
corridor inside the harness frame, around every site of the case.

- Sites: every configured down cell maps to one site with coordinates,
  through the lookup the harness uses. A cell without a site or a site
  without coordinates is a named error. Sites are numbered 1, 2, ... in
  the order of the ticket.
- Build the areas and their 100 m locations with the harness's own
  builder. Map data comes from the harness's stored copy when it covers
  the frame, else from the harness's own fetch path; count the calls.
- Per location, compute once: grid id, centre, the nearest site, the
  distance and the bearing from it (degrees clockwise from north), and
  the distance and bearing from every other site.
- Per area, compute once: id, kind, name, count of locations, nearest
  site, the range of distances and the range of bearings of its
  locations from that site (`all` when the area surrounds the site), and
  the description of its map features as the harness context prints it,
  cut at 80 characters.
- Write `<run dir>/pool.json` with both tables.

Why the map is not a tool. The raw map of a frame holds tens of
thousands of elements. No model can read that through a tool result.
Every method that has areas gets them from the same builder, so the
areas are an input here, not a result.

## 3. The MCP server (`tools.py`, `server.py`)

`tools.py` holds the logic of each tool as a function of the parameters
and a run object; it has no MCP import and is tested directly.
`server.py` registers the five functions with the MCP library, under the
server name `outage`, and does nothing else.

The server keeps no fact in memory that is not in its files. At start it
reads `pool.json`, `server_config.json` and its own records, and
rebuilds the counters from them. VS Code may restart a server; a restart
must not reset the budget. Each start is appended to `starts.jsonl`.

### 3.1 The five tools

The descriptions in quotation marks are the text the model reads. Use
them word for word.

**`lookup_cell`**, free.

"Return the site of a cell: site ID, latitude, longitude, technology,
and the sectors on that site with their azimuths. Free. Use it for a
down cell or for a backup cell whose position you need."

| parameter | description shown to the model |
|---|---|
| `cell_id` | "A cell ID, for example CCL06069 or CCSN016069." |

Returns the fields named in the description, from the harness lookup,
and nothing else.

**`list_areas`**, free.

"List the areas where people are likely, from OpenStreetMap, sorted by
distance from the nearest down site. Each row gives the area ID, its
kind (activity, settlement or road corridor), its name, the number of
100 m locations in it, the nearest down site, the range of distances and
bearings of its locations from that site, and its main map features.
Free. Returns at most 50 areas per call; pass the offset of the response
to get the next 50. The list does not show what you have read."

| parameter | description shown to the model |
|---|---|
| `min_distance_m` | "Keep areas whose nearest location is at least this far from the nearest down site. Use 0 for no lower bound." |
| `max_distance_m` | "Keep areas whose nearest location is at most this far from the nearest down site." |
| `offset` | "0 for the first page; then the `next_offset` of the previous response." |

```json
{"matching": 137, "returned": 50, "next_offset": 50,
 "columns": ["area_id", "kind", "name", "locations", "site",
             "distance_m", "bearing_deg", "features"],
 "rows": [["A01", "activity", "", 412, 1, [0, 1900], "all",
           "building 310, residential 4, shop 6, amenity 9"],
          ["R03", "road corridor", "US 6", 260, 1, [300, 9800], [70, 110],
           "primary"]],
 "budget": {}}
```

**`read_coverage`**, one location per location returned.

"Read stored coverage at locations of one area. The server takes up to
`count` locations of the area that this run has not read yet, in the
order you choose, and returns one row per location: the nearest down
site, the distance and bearing from it, the class of the location, the
outage cells that cover it and the backup cells there. Cost: one
location per row returned. A location is never charged twice. A call
that costs more than the locations left is rejected whole and costs
nothing."

| parameter | description shown to the model |
|---|---|
| `area_id` | "An area ID from list_areas." |
| `count` | "How many unread locations to read, 1 to 50." |
| `order` | "`nearest_first`: nearest to the down site first. `farthest_first`: farthest first. `spread`: evenly spaced by distance over the unread locations." |
| `site` | "Optional. A down site number from the case. The filters below then measure from this site. Without it, each location is measured from its nearest down site." |
| `bearing_from_deg`, `bearing_to_deg` | "Optional, always together. Keep only locations whose bearing from the site lies clockwise from the first value to the second. 0 is north, 90 is east." |
| `min_distance_m`, `max_distance_m` | "Optional. Keep only locations in this distance range from the site." |

Selection, in order: the locations of the area; minus those already
charged in this run, through any area; minus those that returned `error`
in this run; the filters; the order; the first `count`. `spread` sorts
the remaining locations by distance and takes every k-th one, with k the
remaining count divided by `count`, rounded down, at least 1. Ties in
any order are broken by grid id. These three orders are not the
harness's query patterns; those are defined per direction bin and need
the State.

Each selected location is read through the same point fetch helper the
harness uses, at radius 10, with its own retries, and classified by the
harness function:

| class | condition |
|---|---|
| `no_sample` | the read returned no sample |
| `not_covered` | it returned samples, and no outage cell is listed at or above the coverage threshold |
| `covered_backup` | an outage cell is listed at or above the threshold, and at least one eligible backup is listed in the same sample |
| `covered_no_backup` | an outage cell is listed at or above the threshold, and no eligible backup is listed with it |
| `error` | the call failed after the client's retries; not charged, not selected again in this run |

```json
{"area_id": "A01", "area_locations": 412,
 "area_unread_left": 327, "filter_unread_left": 41, "returned": 25,
 "counts": {"covered_backup": 9, "covered_no_backup": 2,
            "not_covered": 5, "no_sample": 9, "error": 0},
 "backup_cells": {"CCL04411": 8, "CCL05102": 3},
 "columns": ["site", "distance_m", "bearing_deg", "class",
             "outage_cells", "backup_cells"],
 "rows": [[1, 1840, 75, "covered_backup", "CCL06069:-101",
           "CCL04411:-96 CCL05102:-103"],
          [1, 1910, 77, "not_covered", "", ""],
          [1, 1985, 78, "no_sample", "", ""]],
 "budget": {}}
```

- `outage_cells`: every outage cell listed at or above the threshold at
  the location, with its best RSRP.
- `backup_cells` in a row: the `CELLS_PER_ROW` strongest reachable
  backups with their best RSRP in a sample that also lists the outage
  cell; then `+n` when there are more.
- `backup_cells` in the header: every reachable backup of this call,
  with the count of locations of this call where it is reachable. This
  list is complete.
- `area_unread_left` and `filter_unread_left` are the position of the
  server in the area after this call. They are the only values in any
  response that depend on earlier calls, apart from the budget.
- Rows carry no grid id and no coordinates. The agent reasons in
  distance and bearing from a site; the server records the grid ids.

**`read_kpi`**, one cell-query per cell named.

"Read hourly KPI (RRC connected users and PRB use) of cells for a time
span, and return the baseline for the outage hours: for each cell and
each hour of the planned outage, the mean over the weeks in the span on
the same weekday and hour. Cost: one cell-query per cell named, each
time it is named. LTE and NR cells may be mixed. A cell comes back as
`rows`, as `no_rows` (the query succeeded and the cell has no data in
the span) or as `failed` (the query did not succeed, and nothing is
known about the cell)."

| parameter | description shown to the model |
|---|---|
| `cell_ids` | "1 to 20 cell IDs." |
| `start_time`, `end_time` | "The span, in the time format of the case. Take the start of one baseline window of the case and the end of the same or a later one." |

The server sends each cell to the LTE or the NR client by its ID, with
the parameter checks those harness tools apply, and computes the
baseline with the harness function.

```json
{"cells": [{"cell_id": "CCL04411", "status": "rows", "weeks_with_rows": 4,
            "hours": [["02:00", 41.2, 37.5], ["03:00", 38.0, 35.1]]},
           {"cell_id": "CCL05102", "status": "no_rows"},
           {"cell_id": "CCL07730", "status": "failed",
            "error": "the error name"}],
 "columns_of_hours": ["hour", "rrc_mean", "prb_mean_percent"],
 "budget": {}}
```

A call that raised is `failed`. It is never returned or stored as zero
rows. A failed cell is charged as the harness charges it; say in the
report which rule that is.

**`submit_report`**, free, ends the run.

"Submit the final report. Free. Call it once: when the investigation is
complete, or when the limits leave nothing more to do. If the report has
a format error, the response names the field; correct it and call again.
After a report is accepted the run is over and no tool answers."

| field | description shown to the model |
|---|---|
| `outage_cells` | "The cell IDs you treated as outage cells." |
| `areas` | "One entry per area in which you read at least one location: `area_id`, `locations_read`, `covered_backup`, `covered_no_backup`, `not_covered`, `no_sample` (the four counts add up to `locations_read`), and `read_in_full` (true or false)." |
| `extent` | "One entry per down site and per direction sector of the skill in which you read at least one location: `site`, `bearing_from_deg` (the bearing at which the sector starts), `farthest_covered_m` (the distance of the farthest location where an outage cell covers, or null when you found none), and `edge` (`established` when the completion rules of the skill hold in this sector, else `not_established`)." |
| `backups` | "One entry per backup cell you found: `cell_id`, `kpi_status` (`rows`, `no_rows`, `failed` or `not_queried`), and `peak_prb_mean_percent` (the highest hourly baseline over the outage hours; only with `rows`)." |
| `unknown` | "What the evidence leaves unknown: areas not read or partly read, sectors with no sample, cells without KPI. At most 1500 characters." |
| `summary` | "The result in plain words. At most 2000 characters." |

The server checks the format only: the field names and types, the class
counts adding up, every `area_id` being an area with at least one
charged location in this run, every `bearing_from_deg` being the start
of a sector, every `cell_id` having appeared in a response of this run,
and `peak_prb_mean_percent` being present exactly with `rows`. It does not check that a number is right. That is the
comparison of part 8.

### 3.2 The budget record and the rejections

Every response carries the budget record:

```json
"budget": {"locations_used": 640, "locations_limit": 1500,
           "kpi_cell_queries_used": 12, "kpi_cell_queries_limit": 200,
           "seconds_elapsed": 412, "seconds_limit": 12000,
           "tool_calls_used": 31, "tool_calls_limit": 200}
```

The clock starts at the first tool call the server receives.

| rejection | when | effect |
|---|---|---|
| `query_budget` | a `read_coverage` call would return more locations than are left; the response gives the cost and the locations left | nothing read, nothing charged |
| `kpi_budget` | a `read_kpi` call names more cells than cell-queries are left | nothing queried, nothing charged |
| `invalid_parameter` | an unknown area, an order that is not one of the three, a count outside 1 to 50, one bearing without the other, a time the KPI checks refuse; the response names the parameter and the allowed values | nothing done |
| `time_limit` | the seconds limit is reached | every tool but `submit_report` is rejected from then on |
| `tool_call_limit` | `MAX_TOOL_CALLS` is reached | every tool but `submit_report` is rejected from then on |
| `report_submitted` | a report was accepted | every tool is rejected |

A rejected call counts as a tool call. The server never repairs a
parameter and never guesses a missing one.

### 3.3 Records

| file | content |
|---|---|
| `calls.jsonl` | one line per tool call, in order: index, tool, time received, seconds, the parameters as received, the rejection if any, the locations charged, the cell-queries charged, and the response exactly as returned |
| `reads.jsonl` | one line per charged location, in order: index, call index, grid id, centre, area id, class, `cached`, seconds |
| `samples.jsonl` | every sample of every location read, keyed by grid id, in full |
| `kpi.json` | per call: the cells named, the status per cell, the rows, the query id and the seconds |
| `report.json` | the accepted report; `report_rejected.jsonl` holds each report that failed the format check, with the errors |

`reads.jsonl`, `samples.jsonl` and `kpi.json` have the layout of part 5
of `Copilot_Baseline_Algorithm_Only_2026-11-13.md`, without the fields
`p`, `s`, score and round, so that one comparison script reads both
baselines.

## 4. The skill (`SKILL.md`)

The skill holds what is true for every case: what the data means, what
each tool is for, where people are, when the investigation is complete,
and what the report must contain. It holds no fact about one case.

Its content is the domain knowledge of the harness skill text, the
completion rule included. Why the completion rule is in it: without it,
a worse result would show a missing paragraph. With it, the comparison
shows the difference between a rule that the agent reads and a rule
that a program enforces.

`prepare.py` copies the file below into the workspace, at the place
where the installed VS Code loads skills (part 0, question 3), and
replaces each name in braces with the constant imported from
`completion_point`. Before the first run, compare each statement about
the data and each rule of the completion section with the current
harness skill text and with `completion_point`. If one differs, stop and
report it; do not change either side.

```markdown
---
name: outage-investigation
description: Investigate where a planned cell site outage removes service, which neighbouring cells can take over, and how loaded those cells are, with the tools of the outage MCP server. Use it for every case that gives down cell IDs and a planned outage interval.
---

# Outage investigation

## Purpose

A cell site is planned to go down. From stored measurements, find:

1. where the down cells cover places that people use;
2. at which of those places another cell can take over, and at which
   places no cell can;
3. how loaded each of those other cells normally is in the outage hours.

The outage interval is a plan. It does not show that an outage happened.
Keep three kinds of statement apart: mapped geography, measured
historical coverage, and historical KPI baselines. You have no model
that predicts the load during the outage. Do not present a prediction
as a result.

## What the data means

- You read coverage per location. A location is one cell of a 100 m
  grid. One read returns the stored measurement samples within 10 m of
  the centre of that cell.
- Many locations return no sample. Such a location is unknown. It is
  not covered and it is not uncovered. Never use it as evidence that
  coverage is absent.
- A sample lists its serving sector and a few strongest neighbour
  cells, each with RSRP. The cells of one sample were measured together.
  A cell that a sample does not list is not shown to be absent there.
- An outage cell covers a location when a sample there lists it at or
  above {COVERAGE_RSRP_DBM} dBm, as the serving sector or as a
  neighbour.
- Coverage shows where a cell can be received. It does not show that
  the cell carries traffic there.
- A cell ID with three letters and five digits is LTE. A cell ID with
  four letters and six digits is NR. Every observed cell that matches a
  supplied outage prefix is an outage cell. An outage cell is never a
  backup. An LTE outage cell has LTE backups only, and an NR outage cell
  has NR backups only. If the case supplies both technologies, assess
  each one separately.
- A backup at a location is an eligible cell that is listed in the same
  sample as an outage cell that covers the location. This shows that
  the backup can be received there. It does not show that the backup
  has capacity.
- The areas come from OpenStreetMap. They show where people are likely.
  They do not measure demand. Areas overlap: a location in two areas is
  one location and is charged once, so counts of overlapping areas do
  not add up.

## The class of a location

`read_coverage` returns one class per location. Use it as given.

| class | meaning |
|---|---|
| `covered_backup` | an outage cell covers the location, and a backup is listed with it |
| `covered_no_backup` | an outage cell covers the location, and no backup is listed with it |
| `not_covered` | the location has samples, and no outage cell covers it |
| `no_sample` | unknown |

## The tools

- `lookup_cell`: the position of a cell and the sectors of its site.
  Free.
- `list_areas`: the areas, nearest first, with their size, distance and
  bearing from the down site. Free. It does not show what you have
  read.
- `read_coverage`: reads locations of one area that you have not read
  yet. You choose the area, the count, the order, and optionally a
  range of bearings and distances. Cost: one location per row returned.
- `read_kpi`: the KPI baseline of cells for the outage hours. Cost: one
  cell-query per cell named, each time you name it.
- `submit_report`: the final report. It ends the run.

The tools report what one call returned. They do not keep a record of
your investigation. Keep that record yourself: what you read in each
area and each direction, and what it showed.

## Where to look

An outage matters where people use the network.

- Work outward from the down site. Distance comes first: an area near
  the site matters more than an area of the same kind farther away.
- Activity areas are groups of mapped buildings, shops, amenities and
  residential, commercial or industrial land. More features mean more
  users. Start with the activity area that contains the down site or
  lies nearest to it.
- Settlement areas are discs around mapped place names. They show that
  a settlement exists, not where its users are. Where an activity area
  overlaps a settlement, the activity area locates the users.
- Road corridors carry travellers. A corridor that passes within a few
  kilometres of the site is as important as a settlement near the site.
  Read it directly.
- Farmland, forest and water are not offered as areas.

## When the investigation is complete

Judge each down site and each direction from it separately. Use sectors
of {BIN_DEG} degrees, counted clockwise from north, the first one
starting at 0.

In one sector, the boundary is the farthest location that an outage
cell covers.

1. Inside the boundary: read every location of every area that is
   nearer than the boundary. These locations are the result.
2. Beyond the boundary: every area that starts within {BEYOND_REACH_M} m
   beyond the boundary needs {N_MIN_SAMPLED} locations that returned
   samples and that no outage cell covers, or a full read. A `no_sample`
   location does not count.
3. If a location beyond the boundary is covered, the boundary moves out
   to it, and rules 1 and 2 apply again.
4. A sector in which no location has returned a sample is not finished.
   Read the nearest area within {UNOBSERVED_REACH_M} m of the site in
   that sector first.
5. If the boundary of a sector reaches the outermost areas of the list,
   the edge of that sector is not established. Report it so.

KPI: the investigation needs the baseline of every outage cell and of
every backup that you found.

If the limits end before these rules are met, stop reading, and report
which sectors and which cells are not established.

## KPI baseline

Estimate the normal load of each outage hour from the same weekday and
hours in earlier weeks. The case lists eight baseline windows, W1 to W8:
the outage interval moved back one to eight weeks. One window is not a
baseline; use several, for example W1 to W4. A span from the start of
one window to the end of a later one covers the windows between them in
one query. Query the outage cells and the backups. A cell that comes
back as `no_rows` has no data in the span; do not query the same span
again. A cell that comes back as `failed` is unknown; it is not a cell
without data. Do not read KPI rows of the planned interval as
measurements of the outage.

## Working within the limits

- The case gives four limits: locations, KPI cell-queries, seconds and
  tool calls. Every response shows what is used and what is left.
- A call that does not fit the limit is rejected whole and costs
  nothing. Read the rejection, and send a call that fits.
- Use as few locations as the completion rules allow. To learn whether
  coverage continues in a direction, a small count is enough. Read an
  area in full only where the rules require it.
- A cell named in two KPI calls is charged twice. Collect the backups
  first, then query them.
- Keep enough tool calls to submit the report.

## The report

Call `submit_report` once, at the end. Report only what your tool
results support.

- Every count in `areas` is the sum of the classes that `read_coverage`
  returned to you for that area.
- `extent` gives, per site and sector, the farthest covered location you
  found, and whether the completion rules hold there.
- `unknown` names what you did not establish. An honest "not
  established" is a correct result. A claim without evidence is an
  error.
- Do not invent a cell ID, an area ID, a count or a measurement.

## Conduct

This is one unattended run. Nobody reads your messages while you work,
and nobody answers a question. Do not ask for confirmation and do not
stop to present a plan. Use only the tools of the outage server. Work
until `submit_report` is accepted.
```

## 5. The prompt (`PROMPT_TEMPLATE.md` to `PROMPT.md`)

The prompt holds the case and nothing else: which cells, when, which
limits, what to deliver. It holds no advice on what to read. All advice
is in the skill, so that the same skill serves every case and the prompt
of a new case needs no writing.

`prepare.py` fills the template from the stored harness run and from the
site lookup. Nothing in it is typed by hand. The KPI windows come from
the harness function that computes them, as the harness context lists
them. The run directory keeps `PROMPT.md` as sent.

```markdown
Use the outage-investigation skill and the tools of the `outage` MCP
server to investigate this case.

## Case

- Down cells: {down cell IDs}
- Outage prefixes supplied: {prefixes, with LTE or NR for each}
- Down sites:
  - site 1: {site ID}, latitude {lat}, longitude {lon}, down cells {IDs}
  - site 2: ...
- Planned outage interval: {start} to {end} ({weekday}, {time zone})
- Outage hours: {the hours of the interval}
- KPI baseline windows, same weekday and hours:
  - W1: {start} to {end}
  - ...
  - W8: {start} to {end}

## Limits of this run

- Coverage: {max_query_locations} locations.
- KPI: {max_kpi_cell_queries} cell-queries.
- Time: {max_time_seconds} seconds from your first tool call.
- Tool calls: {MAX_TOOL_CALLS}.

## What to deliver

Find where the outage cells cover places that people use, where a
backup cell is available and where none is, and the KPI baseline of the
outage cells and the backups. Follow the completion rules of the skill.
Then call `submit_report`.

## How to work

- This run is unattended. Do not ask a question and do not wait for an
  answer.
- Before each tool call, write one line: what you want to learn, and
  why this call answers it.
- After `submit_report` is accepted, reply with your summary and stop.
```

Why the line before each call. It costs about 30 output tokens per
step, and it gives the trace the reason of each query, which the
harness records as purpose and information gap. Without it the two
traces cannot be read side by side.

The skill and the prompt are written once. If a dry run shows a
mechanical defect (a wrong tool name, a placeholder not filled, a
format error the agent cannot resolve), correct that line, bump
`COPILOT_BASELINE_VERSION`, and list the change in the report. Do not
change the wording after the real run has started, and do not change it
because of a result.

## 6. The workspace and the session

`prepare.py` writes `<run dir>/workspace/` with exactly: the skill, the
MCP registration that starts `server.py` with `--run-dir`, and, if the
installed version supports it, a custom agent file whose tool list names
the five tools of `outage` and nothing else. It writes `PROMPT.md`,
`pool.json` and `server_config.json` in `<run dir>`, outside the
workspace. It prints the workspace path and the steps below.

The author does these steps by hand:

1. Use a VS Code profile with no other MCP server, no user-level
   instruction file and no memory feature active. Why: each of them
   adds tokens to every step, and each of them can carry knowledge of
   the harness into the baseline.
2. Open `workspace/` in a new window. In the chat view, select agent
   mode and the model. The real run uses GPT-6 Sol. Record the model
   and the reasoning effort setting, if the picker shows one.
3. Enable only the tools of `outage`. Disable the terminal, the file
   tools, search, the browser tools and every other tool. If the
   installed version loads a skill through a file tool (part 0), enable
   that one tool; the workspace holds nothing but the skill.
4. Set the limit of requests per turn above `MAX_TOOL_CALLS`, so that
   VS Code does not pause the run. Switch the agent debug log on before
   the run; it does not record backwards.
5. Read the credit count on the billing page and write it down.
6. Start a new chat, paste `PROMPT.md` unchanged, and send it. When
   VS Code asks to allow a tool of `outage`, allow it for the
   workspace. Type nothing.
7. The run is over when the agent replies after an accepted report,
   when it stops for any other reason, or when VS Code pauses and asks
   whether to continue. In the last two cases do not continue.
8. Export the agent debug log and the chat into `<run dir>/session/`.
   Read the credit count again.

## 7. After the session (`collect.py`)

1. Audit, into `audit.json`. From the exported log: the count of user
   messages (must be 1), every tool name called (each must be a tool of
   `outage`, or the one file tool of step 3 with the skill as its only
   target), whether the skill text was in the model input (search for
   its first heading), and the model name. From the server: the count
   of starts. Any failed item marks the run `audit: failed` with the
   item, and `compare.py` refuses the run. A failed run is reported as
   void. It is not repaired.
2. Usage, into `usage.md`, each number with its source: model requests,
   input tokens, cached input tokens, output tokens, from the log where
   it has them; the credits before and after as the author typed them;
   their difference.
3. The classes and the load estimate of this run, computed by the
   harness's own end-of-run functions on `samples.jsonl` and the KPI
   rows, as part 5 of the algorithm baseline defines it. If they need a
   State, build it through the harness's own constructors and list the
   fields they read. If that is not possible, stop and report.
4. `run.json`: `end_reason` (`report` when a report was accepted, else
   `no_report`), `limits_hit` (the rejections of part 3.2 that
   occurred), `limits`, the final budget record, `model`,
   `COPILOT_BASELINE_VERSION`, `audit`, and `resources`: locations
   charged (cached, live, no sample, error), covered locations found,
   KPI calls, cell-queries and rows, tool calls, rejected calls, model
   requests, tokens, credits, and seconds split into `tools` (the sum
   of the server seconds) and `total` (first to last event of the log).

## 8. Comparison (`compare.py`)

`compare.py <run dir> <harness run dir> [...]` takes as its first
argument a run of this package or, later, a run of the algorithm
baseline. It reads `run.json`, `reads.jsonl`, `samples.jsonl` and
`kpi.json` of each run. It refuses a run whose `audit.json` says
failed. It writes `<run dir>/compare/` with the three files that part 6
of `Copilot_Baseline_Algorithm_Only_2026-11-13.md` defines:
`resources.md`, `order.md` with `order.geojson`, and `classes.md`. The
algorithm baseline uses this module; there is no second one.

When the first run has a `report.json`, it adds `claims.md`, which sets
the agent's report against the program's own computation on the agent's
own evidence. A run that ended `no_report` has no `claims.md`, and
`resources.md` says so.

1. Per area of the report: each of the five numbers against the
   program's count over the locations this run read in that area. The
   count and share of numbers that differ, and the largest difference.
2. `read_in_full`: against whether every location of the area was
   charged.
3. Per entry of `extent`: `farthest_covered_m` against the program's
   value from `reads.jsonl`, equal within 100 m or not.
4. Per entry of `extent` with `edge: established`: whether the
   harness completion check, run on the State that part 7 builds from
   this run's evidence, holds that sector closed. The count the agent called established and the check
   holds open is the main number of this file. The reverse count is
   given as well.
5. Per backup of the report: `kpi_status` and `peak_prb_mean_percent`
   against `kpi.json`; and every reachable backup of `samples.jsonl`
   that the report does not name.

The harness run's report is scored by items 1 to 3 and 5 the same way,
so that the table has both columns. No reference is used. No pictures.

## 9. Tests, synthetic only

Tool logic, with the fake point source and a fake KPI client:

1. A location in two areas is charged once: after a full read of the
   first area, a read of the second returns only its other locations.
2. `nearest_first`, `farthest_first` and `spread` on an area of 20
   locations with `count` 5 return the locations computed by hand.
3. A bearing filter that crosses north (330 to 30) and a distance
   filter keep the locations computed by hand; one bearing without the
   other is `invalid_parameter`.
4. A call that costs more than the locations left is rejected whole,
   charges nothing, and counts as a tool call.
5. An `error` location is not charged and is not selected again.
6. The class of each row equals the harness classification of the same
   samples; a fourth backup appears as `+1` in the row and in full in
   the header.
7. `read_kpi`: a raised call is `failed` and is not in the KPI cache as
   zero rows; a successful empty call is `no_rows`; a mixed LTE and NR
   list reaches both clients.
8. After the seconds limit and after `MAX_TOOL_CALLS`, every tool but
   `submit_report` is rejected with the reason; after an accepted
   report every tool is rejected.
9. `submit_report` rejects, each with the field named: an area with no
   charged location, class counts that do not add up, a cell that no
   response returned, a `peak_prb_mean_percent` with `no_rows`.
10. A second server start on the same run directory continues with the
    same budget record and never selects a charged location.
11. No response contains a grid id, a file path or a value that depends
    on earlier calls, apart from the two unread counts and the budget.

Server, prepare, collect, compare:

12. The registered server lists five tools whose descriptions equal the
    text of part 3.1, and each tool answers one call through the MCP
    client the concat package already has.
13. `prepare` on fixture F1 writes a workspace with exactly the files
    of part 6, a `SKILL.md` with no brace left, and a `PROMPT.md` with
    no brace left.
14. `collect` on a synthetic log with two user messages, and on one
    with a terminal tool call, marks the run `audit: failed` and names
    the item.
15. `compare` on a synthetic run of this package and a synthetic
    harness run writes the four outputs; a report with one wrong count
    and one `established` sector that the check holds open gives those
    two numbers in `claims.md`.

Gate on the new package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 10. Run it

1. Dry run A, mechanics. `prepare --dry-run` uses fixture F1 of the
   completion check tests with its fake point source, a location limit
   of 300, a time limit of 600 seconds and 40 tool calls. The author
   runs the session on the cheapest model. Check: the skill loaded, only
   `outage` tools were called, the log exported, the credits read.
2. Dry run B, behaviour. The same fixture, on GPT-6 Sol. Check: the
   agent works to `submit_report` without a question, and the seconds
   of the slowest tool call are below the client timeout. Write down
   the credits per tool call.
3. Before the real run, multiply the credits per tool call of dry run B
   by `MAX_TOOL_CALLS`. If the product is above 1500 credits, stop and
   report; the author decides.
4. The real run, once, on the case that has a stored model run and a
   stored rule run, with `--harness-run` set to the model run. Do not
   start a second real run.
5. `collect`, then `compare` with both stored runs. Stop and report.

Before the real run the author confirms that the data policy allows
coverage classes, cell IDs and KPI baselines of this case to pass
through Copilot's model provider.

## 11. Report back

The answers of part 0 and the change list as file and line. Then:

1. `pool.json` in counts: areas by kind, locations, map calls, seconds.
2. `audit.json` and `usage.md` of each session, the two dry runs
   included.
3. `run.json`, `report.json`, and the four comparison files.
4. From the log: the count of model requests, whether Copilot shortened
   or summarized the conversation during the run and at which step, and
   the largest input of one request in tokens.
5. The one-line reasons the agent wrote before its calls, as a list
   with the call index, so that the sequence can be read against the
   harness run.
6. Each place where the skill text and the current harness skill text
   or `completion_point` differ (part 4).
7. Anything the installed VS Code could not do as written here: a tool
   that could not be disabled, a skill that did not load, a log without
   token counts. State it; do not work around it silently.
