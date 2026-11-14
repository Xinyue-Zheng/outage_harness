# Baseline: Copilot agent mode with one skill, one MCP server and one prompt (instruction for the Copilot)

This is the full instruction. It replaces every earlier Copilot baseline
instruction, the CLI one included. Build exactly what is here and
nothing more.

The baseline: GitHub Copilot in agent mode in the VS Code chat view gets
a case in one prompt, the domain knowledge in one skill, and the data
through one MCP server. It decides every step by itself and works alone
until it submits a report. Nothing is computed for it before the run.

```
  1 skill    SKILL.md      what is true for every case; prescribes no order of steps
  2 MCP      server `outage-baseline`: the tools the packages already have,
             served to Copilot, with the limits enforced and every call recorded
  3 prompt   PROMPT.md     names the case, nothing else

  The author pastes PROMPT.md once
       v
  Copilot agent --- tool call ---> MCP server ---> the caches, the point API, KPI, the map
       ^                               | charges, rejects past a limit
       +------- compact result --------+ records every call
       | ... no human input ...
       | submit_report
       v
  summary.py: run.json and summary.md from the server records
```

The tools are not designed here. The packages already have an MCP
server with tool definitions. Part 1 finds them, and part 2 changes only
what Copilot needs.

## Rules

- New code goes only into a new package `outage_harness_copilot/`:
  `server.py`, `summary.py`, `SKILL.md`. Import the existing
  packages read-only. Do not copy their code.
- Keep this baseline apart from everything else:
  - Do not edit or move the existing MCP server, its client, or any
    skill text of the existing packages.
  - The new server is named `outage-baseline`. It is registered only in
    the `.vscode/mcp.json` of a run folder's workspace. Never register
    it at user level or in the repository.
  - The skill exists only as `outage_harness_copilot/SKILL.md` and as
    its copy in a run folder's workspace. Never put it in the
    repository's `.github` folder or at user level.
  - Every output goes into the baseline root, a folder outside the
    repository. The server refuses a `--run-dir` inside the repository.
- A run may be in progress. Do not edit any file a run reads per round
  (skill text, templates, configuration, `unit_costs.json`, run
  directories). Do not run `uv sync`. Do not add dependencies.
- Write no test suite and make no data call. The author runs the real
  cases. Check only that the server starts and lists its tools. Run the
  gate on the new package: `uv run ruff format`,
  `uv run ruff check --fix`, `uv run ty check`.
- Point, KPI and map calls go through the caches the harness uses, as a
  harness run does. Do not start a real run while another run is using
  the point API.
- `COPILOT_BASELINE_VERSION` is a string at the top of `server.py`,
  bumped by hand at every change of the tools, the skill or the prompt.

## 1. Check the existing MCP server first

Find every MCP server module and tool definition in the packages
(`mcp_server`, `mcp_client`, the tool declarations). Use the one of
`outage_harness_langgraph` if it has one, else the one of the concat
package. Write this table into the report, one row per existing tool:

| tool name | parameters | what the model receives back | charges the budget | needs the harness State |
|---|---|---|---|---|

Also find, and name in the report: the function that runs a coverage
query for an area and the function that classifies one location from
its samples (coverage may not be an MCP tool today); where the areas of
the map tool are built; the function that computes the KPI windows and
the one that turns hourly rows into the per-hour baseline; and where
the stored harness run keeps the ticket and `run.json.limits`.

Continue with part 2 in the same session. Stop and report only if a
requirement of part 2 cannot be met without editing an existing package.

## 2. The server (`server.py`)

`python -m outage_harness_copilot.server --run-dir <run folder> --harness-run <stored harness run of the case>`

VS Code starts it. It serves over stdio and prints nothing else to
standard output.

**Start from the existing tools.** Serve the existing tools for the site
lookup, the map, coverage and KPI under their existing names, with
their existing parameters and descriptions. Reach them by import, or
through the existing in-process client; do not edit them. Change a tool
only where a requirement below needs it, and list each change in the
report. Add a tool only where the table of part 1 shows none.

**Requirements.** They hold for every tool the model can call.

1. **The agent chooses.** The map tool takes the place and the extent
   the agent asks for; no area is built before the run. The coverage
   tool lets the agent read part of an area: how many locations, nearest
   first, farthest first or evenly spread, and optionally only a range
   of bearings and distances from the down site. If the existing
   coverage tool has parameters that do this, keep them. If one of its
   parameters needs the harness State (a direction bin, an open item),
   leave that parameter out. A coverage call reads at most 50 new
   locations.
2. **The result is what this one call observed, as text the model can
   read.** The agent has no file tools, so a file path is not a result.
   - Map: one row per area: id, kind, name, count of 100 m locations,
     distance range and bearing range from the nearest down site, main
     map features. Not the raw map elements. At most 50 rows per call,
     with a way to get the next rows.
   - Coverage: the count per class, the complete list of backup cells of
     this call with their counts, and one row per location: distance and
     bearing from the nearest down site, class, the outage cells that
     cover it, the strongest backups. The class comes from the harness
     classification function: `no_sample`, `not_covered`,
     `covered_backup`, `covered_no_backup`. Rows carry no grid id.
   - KPI: per cell and outage hour, the mean RRC and the mean PRB over
     the weeks in the span, from the harness baseline function. Not the
     hourly rows.
3. **No tool returns the state of the run.** Not what was read so far,
   not what is still open, not which call would be valid, not whether
   the investigation is complete. Those are what the harness adds, and
   this baseline runs without them. The only running values are the
   budget record and, in a coverage result, the count of locations of
   that area not yet read.
4. **The limits are those of the stored harness run**, read from
   `--harness-run` and never retyped: locations, KPI cell-queries,
   seconds. Charging is as in the harness: one per new location, cached
   or live, never twice; one per cell named in a KPI call; the map is
   free. A call that costs more than is left is rejected whole and
   charges nothing. The clock starts at the first tool call. A fourth
   limit, 200 tool calls, protects the credit budget; the harness has
   none. After the seconds limit or the tool-call limit, only
   `submit_report` is accepted. Every response carries the budget
   record:

   ```json
   "budget": {"locations_used": 640, "locations_limit": 1500,
              "kpi_cell_queries_used": 12, "kpi_cell_queries_limit": 200,
              "seconds_elapsed": 412, "seconds_limit": 12000,
              "tool_calls_used": 31, "tool_calls_limit": 200}
   ```
5. **A failure is not an empty result.** A location whose call fails
   after the client's retries is `error`: not charged, not read again. A
   KPI cell is `rows`, `no_rows` (the query succeeded and found no data)
   or `failed` (the query did not succeed). `failed` is never returned
   or stored as zero rows.
6. **A rejection names its reason**: the budget that is short with the
   cost and what is left, or the parameter that is wrong with the
   allowed values. The server never repairs or guesses a parameter. A
   rejected call counts as a tool call.
7. **The server keeps no fact only in memory.** At start it rebuilds its
   counters from the run folder, so that a restart by VS Code does not
   reset the budget.

**Two new tools.** The text in quotation marks is the description the
model reads.

- `get_case(skill_version)`, free. "Return the case: the down cells, the
  down sites with their positions, the planned outage interval, the
  outage hours, the eight KPI baseline windows and the limits of this
  run. Pass the skill version that the outage-investigation skill
  gives." It reads the ticket from `--harness-run` and computes the
  windows with the harness function. A `skill_version` other than
  `outage-skill-1` is rejected with "Load the outage-investigation skill
  first." That is the check that the skill was loaded. If an existing
  tool already returns the site of a cell, keep that tool as well.
- `submit_report(outage_cells, areas, extent, backups, unknown, summary)`,
  free. "Submit the final report. Call it once: when the investigation
  is complete, or when the limits leave nothing more to do. `areas`: one
  entry per area in which you read a location, with `area_id`,
  `locations_read`, `covered_backup`, `covered_no_backup`,
  `not_covered`, `no_sample`, and `read_in_full`. `extent`: one entry
  per down site and per 30 degree sector in which you read a location,
  with `site`, `bearing_from_deg`, `farthest_covered_m` (null when no
  covered location was found) and `edge` (`established` or
  `not_established`). `backups`: one entry per backup cell found, with
  `cell_id`, `kpi_status` (`rows`, `no_rows`, `failed`, `not_queried`)
  and `peak_prb_mean_percent` (only with `rows`). `unknown`: what the
  evidence leaves unknown, at most 1500 characters. `summary`: the
  result in plain words, at most 2000 characters. If the format is
  wrong, the response names the field; correct it and call again. After
  a report is accepted, no tool answers." Format checks only: field
  names and types; the four class counts add up to `locations_read`;
  every `area_id` has at least one charged location in this run.

**Records**, in `<run folder>/records/`: `calls.jsonl` (per call: index,
tool, time, seconds, parameters, rejection, charge, and the response as
returned), `reads.jsonl` (per charged location, in order: index, call
index, grid id, centre, area id, class, `cached`, seconds),
`samples.jsonl` (every sample of every location read, by grid id),
`kpi.json` (per call: cells, status per cell, rows, seconds),
`areas.jsonl` (every area a map call returned, with its locations),
`report.json`. At its first start in a run folder the server writes
`case.json`: the ticket and the limits it uses.

## 3. The skill (`SKILL.md`)

Use this text. Fill the one placeholder, under "Tools", from the final
tool list. The numbers in the text must equal the constants of
`completion_point`; check them once. If a number, a statement about the
data or a completion rule differs from `completion_point` or from the
current harness skill text, do not change either; list the difference
in the report.

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

The coverage tool gives each location one class. Use it as given.

| class | meaning |
|---|---|
| `covered_backup` | an outage cell covers the location, and a backup is listed with it |
| `covered_no_backup` | an outage cell covers the location, and no backup is listed with it |
| `not_covered` | the location has samples, and no outage cell covers it |
| `no_sample` | unknown |

## Tools

{one line per tool of the server: its name, what it is for, its cost}

The tools report what one call returned. They keep no record of your
investigation. Keep that record yourself: what you read in each area
and each direction, and what it showed. You choose which tool to call,
in which order, and when to stop.

## Where to look

- The map tool shows the areas around a place, as far out as you ask.
  You choose where and how far to look, and you can look farther later.
- Work outward from the down site. An area near the site matters more
  than an area of the same kind farther away.
- Activity areas are groups of mapped buildings, shops and amenities.
  More features mean more users.
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
5. If the boundary lies at the edge of the map you looked at, look
   farther out. A sector is not established while its boundary lies at
   that edge.

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
- A cell named in two KPI calls is charged twice.
- Keep enough tool calls to submit the report.

## Report

Report only what your tool results support. Every count in `areas` is
the sum of the classes that the coverage tool returned to you for that
area. `unknown` names what you did not establish. An honest "not
established" is a correct result; a claim without evidence is an
error. Do not invent a cell ID, an area ID, a count or a measurement.

## Conduct

This is one unattended run. Nobody answers a question. Do not ask for
confirmation and do not stop to present a plan. Use only the tools of
the outage-baseline server. Work until `submit_report` is accepted.
```

## 4. The prompts

The prompt names the case and prescribes no step. The case details come
from `get_case`, so nothing is typed by hand.

```markdown
Use the outage-investigation skill and the tools of the
`outage-baseline` MCP server.

Case: the planned outage of cell WTL03023. The tool `get_case` returns
the details of the case and the limits of this run.

Investigate the case as the skill describes, and submit the report.

This run is unattended. Do not ask a question and do not wait for an
answer. Before each tool call, write one line: what you want to learn,
and why this call answers it. After the report is accepted, reply with
your summary and stop.
```

The prompt of the second case is the same text with `FSL00169`.

## 5. The run folders

Create these two folders by hand, in a baseline root outside the
repository. No script does this.

```
<baseline root>/WTL03023/
<baseline root>/FSL00169/
    each:
    workspace/                        the folder the author opens in VS Code
        .vscode/mcp.json
        .github/skills/outage-investigation/SKILL.md     (or where the installed VS Code loads skills)
    PROMPT.md
    records/                          written by the server
    session/                          empty; the author saves the exported chat here
    case.json, run.json, summary.md   written by the server and by summary.py
```

`.vscode/mcp.json`:

```json
{"servers": {"outage-baseline": {
    "type": "stdio",
    "command": "<absolute path of the project environment's python>",
    "args": ["-m", "outage_harness_copilot.server",
             "--run-dir", "<this run folder>",
             "--harness-run", "<stored harness run of this case>"],
    "env": {"PYTHONPATH": "<repository root>",
            "REQUESTS_CA_BUNDLE": "<value from the current environment>",
            "SSL_CERT_FILE": "<value from the current environment>"}}}}
```

VS Code starts the server, so the server does not inherit the
terminal's variables. Add every other variable the data clients read.
If one of them is a secret, do not write it into the file; stop and
report. If a case has no stored harness run, do not create its folder
and do not type a ticket or a limit; report it.

One run folder is one run. The server refuses to start in a folder
whose `records/` already holds an accepted report.

## 6. `summary.py`

`python -m outage_harness_copilot.summary <run folder> [--credits-before <n> --credits-after <n>]`

From `case.json` and `records/` only:

- `run.json`: `end_reason` (`report` when a report was accepted, else
  `no_report`), the limits that were hit, the limits, the final budget
  record, `COPILOT_BASELINE_VERSION`, and the resources: locations
  charged (cached, live, no sample, error), covered locations found, map
  calls, KPI calls and cell-queries, tool calls, rejected calls, seconds
  in tools, seconds total, credits before and after or `not recorded`.
- `summary.md`: the resources as a table; the tool calls in order, one
  line each (tool, main parameters, charge); the count per class over
  the read locations; then the report against the records: per area,
  each reported count next to the count from `reads.jsonl`, and the
  number of counts that differ; per `extent` entry, the reported
  `farthest_covered_m` next to the value from `reads.jsonl`; the backups
  in the records that the report does not name. With no report, it says
  so.

`reads.jsonl`, `samples.jsonl` and `kpi.json` use the layout of part 5
of `Copilot_Baseline_Algorithm_Only_2026-11-13.md`, so that a later
comparison with the harness runs needs no new run.

## 7. Report back

The table of part 1. The change list as file and line. Per tool of the
new server: kept as it was, changed (what and for which requirement),
or new. The paths of the two run folders. Then, briefly: where the
installed VS Code loads a skill from; each difference between the skill
text and `completion_point` or the current harness skill text; and
anything that could not be done as written. State it; do not work
around it silently.
