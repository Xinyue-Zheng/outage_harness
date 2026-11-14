# Baseline: Copilot agent mode with one skill, one MCP server and one prompt (instruction for the Copilot)

This is the full instruction. It replaces every earlier Copilot baseline
instruction, the CLI one included. Build exactly what is here and
nothing more. A log audit and a comparison with the harness runs are not
part of this instruction.

The baseline: GitHub Copilot in agent mode in the VS Code chat view gets
a case in one prompt, the domain knowledge in one skill, and the data
through one MCP server. It works alone until it submits a report. Three
things are built, and one folder per run holds everything:

```
  1 skill    SKILL.md            what is true for every case
  2 MCP      server `outage-baseline`, five tools, enforces the limits
  3 prompt   PROMPT.md           names the case, nothing else

  The author pastes PROMPT.md once
       v
  Copilot agent --- tool call ---> MCP server ---> the caches, the point API, KPI
       ^                               | charges, rejects past a limit
       +------- compact result --------+ records every call
       | ... no human input ...
       | submit_report
       v
  summary.py: run.json and summary.md from the server records
```

## Rules

- New code goes only into a new package `outage_harness_copilot/`:
  `server.py`, `prepare.py`, `summary.py`, `SKILL.md`,
  `PROMPT_TEMPLATE.md`, `tests/`. Import the harness packages read-only.
  If a harness function cannot be called without the harness State,
  stop and report which one. Do not copy harness code.
- Keep this baseline apart from everything else:
  - Do not edit, move or register the existing MCP server, its client,
    or any skill text of the harness and concat packages.
  - The server name is `outage-baseline`. It is registered only in the
    `.vscode/mcp.json` of a run folder's workspace. Never register it at
    user level or in the repository.
  - The skill exists only as `outage_harness_copilot/SKILL.md` and as
    its copy in a run folder's workspace. Never put it in the
    repository's `.github` folder or at user level.
  - Every output goes into the baseline root, a folder outside the
    repository. `prepare.py` refuses an `--out` inside the repository.
- A run may be in progress. Do not edit any file a run reads per round
  (skill text, templates, configuration, `unit_costs.json`, run
  directories). Do not run `uv sync`. Do not add dependencies; use the
  MCP library the existing server uses. Tests write only under
  `tmp_path`.
- Point and KPI calls go through the caches the harness uses, as a
  harness run does. Do not start a real run while another run is using
  the point API.
- `COPILOT_BASELINE_VERSION` is a string at the top of `server.py`,
  bumped by hand at every change of the tools, the skill or the prompt.

Commands:

```
python -m outage_harness_copilot.prepare --harness-run <run dir of a harness run on the case> --out <baseline root> [--dry-run]
python -m outage_harness_copilot.server --run-dir <run folder>          (started by VS Code)
python -m outage_harness_copilot.summary <run folder> [--credits-before <n> --credits-after <n>]
```

One run folder is one run:

```
<baseline root>/<down cell ID>[_dryrun]/
    workspace/                      the folder the author opens in VS Code
        .vscode/mcp.json
        .github/skills/outage-investigation/SKILL.md
    PROMPT.md
    case.json                       ticket and limits, copied from the harness run
    pool.json                       areas and locations
    records/                        written by the server
    session/                        the author saves the exported chat here
    run.json, summary.md            written by summary.py
```

`prepare.py` refuses a run folder that already exists.

## 1. `prepare.py`

1. Read the ticket (down cells, outage interval, supplied prefixes) and
   `run.json.limits` (`max_query_locations`, `max_kpi_cell_queries`,
   `max_time_seconds`) from `--harness-run`. Write them to `case.json`
   with `max_tool_calls: 200`. With `--dry-run`, write these limits
   instead: 60 locations, 10 cell-queries, 900 seconds, 15 tool calls.
2. Sites: map every down cell to its site with the harness lookup. A
   cell without a site or a site without coordinates is a named error.
   Number the sites 1, 2, ... in ticket order.
3. Build the activity areas, settlement areas and road corridors and
   their 100 m locations for the harness frame with the harness's own
   builder. Per location store: grid id, centre, nearest site, distance
   and bearing from it (degrees clockwise from north). Per area store:
   id, kind, name, count of locations, nearest site, the range of
   distances and of bearings of its locations (`all` when the area
   surrounds the site), and the feature description the harness context
   prints, cut at 80 characters. Write `pool.json`.
4. Write the workspace: the skill copy, and `.vscode/mcp.json`:

   ```json
   {"servers": {"outage-baseline": {
       "type": "stdio",
       "command": "<absolute path of the project environment's python>",
       "args": ["-m", "outage_harness_copilot.server", "--run-dir", "<run folder>"],
       "env": {"PYTHONPATH": "<repository root>",
               "REQUESTS_CA_BUNDLE": "<value from the current environment>",
               "SSL_CERT_FILE": "<value from the current environment>"}}}}
   ```

   VS Code starts the server, so the server does not inherit the
   terminal's variables. Add every other variable the data clients read.
   If one of them is a secret, do not write it into the file; stop and
   report.
5. Write `PROMPT.md` from the template (part 4) with the down cell ID.
6. Print the workspace path and the author's steps of part 5.

## 2. The MCP server (`server.py`)

The server serves over stdio and prints nothing else to standard
output. It keeps no fact in memory that is not in its files: at start
it reads `case.json`, `pool.json` and `records/`, and rebuilds its
counters, so that a restart by VS Code does not reset the budget.

Rule for every tool: **it returns what this one call observed.** It
never returns what the run has read so far, what is still open, which
call would be valid, or whether the investigation is complete. The two
exceptions are the budget record and the unread counts of
`read_coverage`.

Constants at the top of the file: `LOCATIONS_PER_CALL_MAX = 50`,
`AREAS_PER_CALL = 50`, `CELLS_PER_KPI_CALL_MAX = 20`,
`CELLS_PER_ROW = 3`, `SKILL_VERSION = "outage-skill-1"`. The coverage
threshold and the other thresholds are imported from
`completion_point`.

The text in quotation marks is the tool description the model reads.
Use it word for word.

**`get_case(skill_version)`**, free. "Return the case: the down cells,
the down sites with their positions, the planned outage interval, the
outage hours, the eight KPI baseline windows and the limits of this
run. Call it first. Pass the skill version that the
outage-investigation skill gives."

A `skill_version` other than `SKILL_VERSION` is rejected with "Load the
outage-investigation skill first." This is the check that the skill was
loaded. The KPI windows come from the harness function that computes
them.

**`list_areas(min_distance_m, max_distance_m, offset)`**, free. "List
the areas where people are likely, from OpenStreetMap, sorted by
distance from the nearest down site. Each row gives the area ID, its
kind (activity, settlement or road corridor), its name, the number of
100 m locations in it, the nearest down site, the range of distances
and bearings of its locations from that site, and its main map
features. Returns at most 50 areas per call; pass `next_offset` to get
the next 50. The list does not show what you have read."

```json
{"matching": 137, "returned": 50, "next_offset": 50,
 "columns": ["area_id", "kind", "name", "locations", "site", "distance_m", "bearing_deg", "features"],
 "rows": [["A01", "activity", "", 412, 1, [0, 1900], "all", "building 310, shop 6, amenity 9"]],
 "budget": {}}
```

**`read_coverage(area_id, count, order, bearing_from_deg, bearing_to_deg, min_distance_m, max_distance_m)`**,
one location per row returned. "Read stored coverage at locations of
one area. The server takes up to `count` (1 to 50) locations of the
area that this run has not read yet and returns one row per location:
the nearest down site, the distance and bearing from it, the class, the
outage cells that cover it and the backup cells there. `order` is
`nearest_first`, `farthest_first`, or `spread` (evenly spaced by
distance). The bearing pair and the distance pair are optional filters:
bearings run clockwise from the first value to the second, 0 is north.
Cost: one location per row. A location is never charged twice. A call
that costs more than the locations left is rejected whole and costs
nothing."

- Selection, in order: the area's locations; minus those charged in
  this run through any area; minus those that returned `error`; the
  filters; the order; the first `count`. `spread` takes every k-th
  location by distance, k = remaining count divided by `count`, rounded
  down, at least 1. Ties by grid id.
- Read each location with the harness point fetch helper at radius 10,
  and classify it with the harness classification function:
  `no_sample`, `not_covered`, `covered_backup`, `covered_no_backup`. A
  location whose call fails after the client's retries is `error`: not
  charged, not selected again.

```json
{"area_id": "A01", "area_locations": 412, "area_unread_left": 327, "filter_unread_left": 41, "returned": 25,
 "counts": {"covered_backup": 9, "covered_no_backup": 2, "not_covered": 5, "no_sample": 9, "error": 0},
 "backup_cells": {"WTL04411": 8, "WTL05102": 3},
 "columns": ["site", "distance_m", "bearing_deg", "class", "outage_cells", "backup_cells"],
 "rows": [[1, 1840, 75, "covered_backup", "WTL03023:-101", "WTL04411:-96 WTL05102:-103"],
          [1, 1910, 77, "not_covered", "", ""],
          [1, 1985, 78, "no_sample", "", ""]],
 "budget": {}}
```

  A row prints the `CELLS_PER_ROW` strongest reachable backups and then
  `+n`. The header list `backup_cells` is complete: every reachable
  backup of this call with its count of locations. Rows carry no grid
  id.

**`read_kpi(cell_ids, start_time, end_time)`**, one cell-query per cell
named. "Read hourly KPI of 1 to 20 cells for a time span and return the
baseline for the outage hours: per cell and outage hour, the mean RRC
connected users and the mean PRB use over the weeks in the span on the
same weekday and hour. Take the start of one baseline window of the
case and the end of the same or a later one. Cost: one cell-query per
cell named, each time it is named. A cell comes back as `rows`, as
`no_rows` (the query succeeded and found no data) or as `failed` (the
query did not succeed; nothing is known about the cell)."

Send each cell to the LTE or NR client by its ID, with the parameter
checks of the harness KPI tools, and compute the baseline with the
harness function. A call that raised is `failed`; never return or store
it as zero rows. Charge a failed cell as the harness does.

```json
{"cells": [{"cell_id": "WTL04411", "status": "rows", "weeks_with_rows": 4,
            "hours": [["02:00", 41.2, 37.5]]},
           {"cell_id": "WTL05102", "status": "no_rows"},
           {"cell_id": "WTL07730", "status": "failed", "error": "<error name>"}],
 "columns_of_hours": ["hour", "rrc_mean", "prb_mean_percent"], "budget": {}}
```

**`submit_report(outage_cells, areas, extent, backups, unknown, summary)`**,
free. "Submit the final report. Call it once: when the investigation is
complete, or when the limits leave nothing more to do. `areas`: one
entry per area in which you read a location, with `area_id`,
`locations_read`, `covered_backup`, `covered_no_backup`, `not_covered`,
`no_sample`, and `read_in_full`. `extent`: one entry per down site and
per 30 degree sector in which you read a location, with `site`,
`bearing_from_deg`, `farthest_covered_m` (null when no covered location
was found) and `edge` (`established` or `not_established`). `backups`:
one entry per backup cell found, with `cell_id`, `kpi_status` (`rows`,
`no_rows`, `failed`, `not_queried`) and `peak_prb_mean_percent` (only
with `rows`). `unknown`: what the evidence leaves unknown, at most 1500
characters. `summary`: the result in plain words, at most 2000
characters. If the format is wrong, the response names the field;
correct it and call again. After a report is accepted, no tool
answers."

Format checks only: field names and types; the four class counts add up
to `locations_read`; every `area_id` has at least one charged location
in this run. The server does not check that a number is right.

**Budget and rejections.** Every response carries

```json
"budget": {"locations_used": 640, "locations_limit": 1500,
           "kpi_cell_queries_used": 12, "kpi_cell_queries_limit": 200,
           "seconds_elapsed": 412, "seconds_limit": 12000,
           "tool_calls_used": 31, "tool_calls_limit": 200}
```

The clock starts at the first tool call. Rejections, each with its
reason in the response, each counted as a tool call, none charged:
`query_budget` and `kpi_budget` (the call costs more than is left; the
response gives the cost and what is left), `invalid_parameter` (names
the parameter and the allowed values), `time_limit` and
`tool_call_limit` (from then on only `submit_report` is accepted),
`report_submitted` (every tool is rejected). The server never repairs
or guesses a parameter.

The tool-call limit protects the credit budget; the harness has none.
`summary.md` says so when a run ends on it.

**Records**, in `records/`: `calls.jsonl` (per call: index, tool, time,
seconds, parameters, rejection, charge, and the response as returned),
`reads.jsonl` (per charged location, in order: index, call index, grid
id, centre, area id, class, `cached`, seconds), `samples.jsonl` (every
sample of every location read, by grid id), `kpi.json` (per call:
cells, status per cell, rows, seconds), `report.json`. `reads.jsonl`,
`samples.jsonl` and `kpi.json` use the layout of part 5 of
`Copilot_Baseline_Algorithm_Only_2026-11-13.md`, so that its comparison
script can read this run later.

## 3. The skill (`SKILL.md`)

Use this text. The numbers in it must equal the constants of
`completion_point`; test 9 checks that. If a statement about the data
or a completion rule differs from the current harness skill text, do
not change either; list the difference in the report.

```markdown
---
name: outage-investigation
description: Investigate where a planned cell site outage removes service, which neighbouring cells can take over, and how loaded those cells are, with the tools of the outage-baseline MCP server. Use it for every case that names a down cell.
---

# Outage investigation

Skill version: outage-skill-1. Pass this value to `get_case`.

## Purpose

A cell site is planned to go down. From stored measurements, find:

1. where the down cells cover places that people use;
2. at which of those places another cell can take over, and at which
   places no cell can;
3. how loaded each of those other cells normally is in the outage hours.

The outage interval is a plan. It does not show that an outage happened.
You have no model that predicts the load during the outage. Do not
present a prediction as a result.

## What the data means

- A location is one cell of a 100 m grid. One read returns the stored
  measurement samples within 10 m of its centre.
- Many locations return no sample. Such a location is unknown. Never
  use it as evidence that coverage is absent.
- A sample lists its serving sector and a few strongest neighbour
  cells. A cell that a sample does not list is not shown to be absent.
- An outage cell covers a location when a sample there lists it at or
  above -110 dBm, as the serving sector or as a neighbour.
- Coverage shows where a cell can be received. It does not show that
  the cell carries traffic there.
- A cell ID with three letters and five digits is LTE; with four
  letters and six digits it is NR. Every observed cell that matches a
  supplied outage prefix is an outage cell and is never a backup. An
  LTE outage cell has LTE backups only; an NR outage cell has NR
  backups only.
- A backup at a location is an eligible cell listed in the same sample
  as an outage cell that covers the location. This shows that the
  backup can be received there, not that it has capacity.
- The areas come from OpenStreetMap. They show where people are likely,
  not how much demand there is. Areas overlap; a location in two areas
  is one location and is charged once.

## Classes

`read_coverage` gives each location one class. Use it as given.

| class | meaning |
|---|---|
| `covered_backup` | an outage cell covers the location, and a backup is listed with it |
| `covered_no_backup` | an outage cell covers the location, and no backup is listed with it |
| `not_covered` | the location has samples, and no outage cell covers it |
| `no_sample` | unknown |

## Tools

- `get_case`: the case and the limits. Call it first. Free.
- `list_areas`: the areas, nearest first. Free.
- `read_coverage`: reads locations of one area that you have not read
  yet. Cost: one location per row.
- `read_kpi`: the KPI baseline of cells. Cost: one cell-query per cell
  named, each time you name it.
- `submit_report`: the final report. It ends the run.

The tools report what one call returned. They keep no record of your
investigation. Keep that record yourself: what you read in each area
and each direction, and what it showed.

## Where to look

- Work outward from the down site. An area near the site matters more
  than an area of the same kind farther away.
- Activity areas are groups of mapped buildings, shops and amenities.
  More features mean more users. Start with the activity area at the
  down site or nearest to it.
- Settlement areas are discs around mapped place names. They show that
  a settlement exists, not where its users are.
- Road corridors carry travellers. A corridor within a few kilometres
  of the site is as important as a settlement near the site.

## When the investigation is complete

Judge each down site and each direction separately, in sectors of 30
degrees clockwise from north, the first one starting at 0. In one
sector, the boundary is the farthest location that an outage cell
covers.

1. Inside the boundary: read every location of every area that is
   nearer than the boundary. These locations are the result.
2. Beyond the boundary: every area that starts within 5000 m beyond it
   needs 10 locations that returned samples and that no outage cell
   covers, or a full read. A `no_sample` location does not count.
3. If a location beyond the boundary is covered, the boundary moves out
   to it, and rules 1 and 2 apply again.
4. A sector in which no location has returned a sample is not finished.
   Read the nearest area within 2000 m of the site in that sector.
5. If the boundary reaches the outermost areas of the list, the edge of
   that sector is not established.

The investigation also needs the KPI baseline of every outage cell and
of every backup that you found.

If the limits end first, stop reading, and report which sectors and
cells are not established.

## KPI baseline

The case lists eight windows, W1 to W8: the outage interval moved back
one to eight weeks. One window is not a baseline; use several, for
example W1 to W4. A span from the start of one window to the end of a
later one covers the windows between them in one query. A cell with
`no_rows` has no data in the span; do not query the same span again. A
cell with `failed` is unknown; it is not a cell without data.

## Limits

- Every response shows what is used and what is left of four limits:
  locations, KPI cell-queries, seconds, tool calls.
- A call that does not fit is rejected whole and costs nothing.
- Use as few locations as the completion rules allow. To learn whether
  coverage continues in a direction, a small count is enough.
- Collect the backups first, then query their KPI once.
- Keep enough tool calls to submit the report.

## Report

Report only what your tool results support. Every count in `areas` is
the sum of the classes that `read_coverage` returned to you for that
area. `unknown` names what you did not establish. An honest "not
established" is a correct result; a claim without evidence is an
error. Do not invent a cell ID, an area ID, a count or a measurement.

## Conduct

This is one unattended run. Nobody answers a question. Do not ask for
confirmation and do not stop to present a plan. Use only the tools of
the outage-baseline server. Work until `submit_report` is accepted.
```

## 4. The prompt (`PROMPT_TEMPLATE.md`)

The prompt names the case and holds no advice. Everything about the
case comes from `get_case`, so nothing is typed by hand and the prompts
of two cases differ in one word.

```markdown
Use the outage-investigation skill and the tools of the
`outage-baseline` MCP server.

Case: the planned outage of cell {down cell ID}.

1. Call `get_case` first. It returns the down cells, the sites, the
   planned outage interval, the KPI baseline windows and the limits.
2. Investigate the case as the skill describes.
3. Call `submit_report`.

This run is unattended. Do not ask a question and do not wait for an
answer. Before each tool call, write one line: what you want to learn,
and why this call answers it. After `submit_report` is accepted, reply
with your summary and stop.
```

The two cases are `WTL03023` and `FSL00169`. Run `prepare` once per
case, each with the stored harness run of that case. If a case has no
stored harness run, stop and report; do not type a ticket or a limit.

## 5. The author's steps, printed by `prepare.py`

1. Open `workspace/` in a new VS Code window, in a profile with no other
   MCP server and no user-level instruction file.
2. In the chat view select agent mode and the model (GPT-6 Sol).
3. In the tools list enable only `outage-baseline`. Disable the
   terminal, the file tools and every other tool. If the skill does not
   load without a file tool, enable the file read tool only.
4. Write down the credit count from the billing page.
5. Start a new chat, paste `PROMPT.md` unchanged, send. Allow the tools
   of `outage-baseline` when asked. Type nothing else.
6. The run is over when the agent replies after an accepted report, or
   stops for any other reason, or VS Code asks whether to continue. Do
   not continue.
7. Run **Chat: Export Chat** and save the file in `session/`. Write
   down the credit count again. Run `summary.py`.

## 6. `summary.py`

From `case.json`, `pool.json` and `records/` only:

- `run.json`: `end_reason` (`report` when a report was accepted, else
  `no_report`), `limits_hit`, the limits, the final budget record,
  `COPILOT_BASELINE_VERSION`, and the resources: locations charged
  (cached, live, no sample, error), covered locations found, KPI calls
  and cell-queries, tool calls, rejected calls, seconds in tools,
  seconds total, credits before and after or `not recorded`.
- `summary.md`: the resources as a table; the count per class over the
  read locations; then the report against the records: per area, each
  reported count next to the count from `reads.jsonl`, and the number
  of counts that differ; per `extent` entry, the reported
  `farthest_covered_m` next to the value from `reads.jsonl`; the
  backups in the records that the report does not name. With no
  report, it says so.

## 7. Tests, synthetic only, with the fake point source and a fake KPI client

1. A location in two areas is charged once.
2. The three orders, a bearing filter that crosses north and a distance
   filter return the locations computed by hand; one bearing without
   the other is `invalid_parameter`.
3. A call over the location limit is rejected whole, charges nothing
   and counts as a tool call.
4. An `error` location is not charged and not selected again.
5. Each row's class equals the harness classification of the same
   samples; a fourth backup shows as `+1` in the row and in full in the
   header.
6. `read_kpi`: a raised call is `failed` and is not stored as zero
   rows; an empty success is `no_rows`.
7. After the seconds limit and after the tool-call limit only
   `submit_report` is accepted; after an accepted report nothing is;
   `get_case` with a wrong skill version is rejected.
8. `submit_report` names the field for: an area with no charged
   location, counts that do not add up, a missing field.
9. A second server start on the same run folder continues the budget.
   The numbers in `SKILL.md` equal the constants of `completion_point`.
10. `prepare` writes the run folder as drawn above; it refuses an
    `--out` inside the repository and an existing run folder.
11. `summary` on synthetic records with one wrong reported count gives
    that count as different.

Gate on the new package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 8. Run it

1. `prepare --dry-run` for `WTL03023`. The author runs the session. This
   one small run checks that the server starts, the skill loads, the
   agent works without a question and the records are written.
2. Read the credits the dry run used. If credits per tool call times
   200 is above 1500, stop and report.
3. `prepare` and one real run for `WTL03023`. Then the same for
   `FSL00169`. One real run per case.

Before a real run the author confirms that the data policy allows the
coverage classes, cell IDs and KPI baselines of the case to pass
through Copilot's model provider.

## 9. Report back

The change list as file and line. Then, per run: `run.json`,
`summary.md` and `report.json`. Then, briefly: which harness functions
built the areas, classified a location and computed the KPI baseline;
how the installed VS Code loaded the skill; each difference between the
skill text and the current harness skill text; and anything that could
not be done as written. State it; do not work around it silently.
