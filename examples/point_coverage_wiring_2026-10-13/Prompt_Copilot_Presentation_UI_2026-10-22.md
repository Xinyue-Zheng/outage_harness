# Prompt for the Copilot: a picture-led, step-by-step presentation of one completed run

Build one HTML page that presents the completed run
`<RUN_DIR>` (and, side by side, the concat run `<CONCAT_RUN_DIR>` if it
exists) as a step-by-step walk through the investigation, led by maps.
Everything on the page is generated from the run directories by a Python
script you write; nothing is typed in by hand. The page must work as a
single file (inline CSS and JS, images embedded as data URIs or placed in a
`figures/` folder next to it), open from the file system, and be shown on a
projector.

## 1. What to generate

Write `make_presentation.py <RUN_DIR> [<CONCAT_RUN_DIR>] --out <DIR>` that
produces `<DIR>/index.html` and `<DIR>/figures/*.png`. Use matplotlib for
the figures (already installed). Read only these files:

- `state_00.json` and `geography.json` (and `geography_vN.json`): the grid
  frame, the study square, the areas with their grid ids, names and kinds,
  the site position.
- `steps/step_NN/decision.json`, `validation.json`, `tool_result.json`,
  `state_after.json`, `completion_checks.json`, `timing.json`,
  `llm_input.json` (for the input size only).
- `artifacts/expand_NN.json` for expansions (the wedge and the areas added).
- `run_log.md`, `final_report.json`, `final_report.md`,
  `redistribution.json`, `run.json`.

Coordinates: the grid id is `row * columns + column` in the frame; x east,
y north, 100 m per cell; the site is at (`site.x_m`, `site.y_m`). Draw in
kilometres from the site. Never draw latitude and longitude.

## 2. The figures

Draw every figure with the same frame, the same axis limits (the final study
area plus 1 km of margin), the same colours, and the site as a black cross,
so that the eye can follow one place from figure to figure. Light grey grid
background for the active study area; white outside it; a thin dashed line
for the study-area edge.

**F0, the map at State 0.** Every area as a filled shape of its grid cells:
settlements in one hue, road corridors in another, each labelled with its
id and name near its centroid. Legend. Title: "State 0: N areas derived from
OpenStreetMap, 30 km study square".

**F1 to Fn, one figure per step that changed the map.** Start from the
previous figure's content and add only the change, drawn so it stands out:

- Coverage query of an area: fill that area's queried locations by what the
  outage sector did there (covers at or above -110 dBm: red; listed but
  weaker: orange; absent with samples: blue; no sample: hatched grey), and
  draw a thick outline around the area. Earlier queried areas keep their
  fill at reduced opacity. Title: "Step k: queried <id> (<name>), <m>
  locations, outage sector covers <c>".
- Expansion: draw the wedge that was added as a translucent band, the new
  study-area edge as the dashed line, and the new areas with their labels.
  Title: "Step k: expanded <direction> by <d> m; <n> areas added".
- A rejected step or a KPI query: no new map; reuse the previous figure
  with the title "Step k: <what happened>" and a one-line caption from the
  rejection message or the KPI result, so the page still has one figure per
  step.

Also draw on each figure, from `completion_checks.json` of that step, the
checked direction bins as thin radial lines from the site at the bin
borders, and shade each bin's sector: green if closed, red if open, yellow
if open at the edge. This is the completion check made visible; it should
turn green as the run proceeds.

**Ff, the final map.** Every covered location coloured by its class from
`final_report.json` (`locations[grid_id].class`): total loss red; degrade
by signal orange; degrade by capacity yellow; both purple; served by backup
green; unknown cause grey. Area outlines and labels on top. Title: "Final
report: <covered> covered locations; <loss> total loss; <degrade> degrade".
A second final figure, Fb, per backup cell: the locations where it is the
strongest living backup, one colour per backup, with the backup's estimated
PRB in the legend ("CCL06090_aa_1: 41% to 86%, exceeded").

**Fc, the input-size chart**: characters of model input per round, one
line per condition when two runs are given.

## 3. The page

- A header: site, outage window, model, the two conditions in one sentence
  each.
- A step control: Previous and Next buttons, arrow keys, a track of one
  tick per step coloured by what the step was (query, expansion, KPI,
  rejection, end).
- For each step, side by side when two runs are given: the figure for that
  step (large, the main thing on the screen), and under it four short
  blocks in this order: what the model decided (action and parameters,
  then the gap question in one line); what the program said (accepted, or
  the rejection message); what came back (one line from tool_result); the
  completion check after the step (two pills, boundary and backup_load,
  then the open items, at most five lines).
- The final step shows Ff, then Fb, then the final report text in a
  monospace block, then the "what this report does not establish" list.
- A closing slide: Fc, then one table: steps, locations fetched, wall
  time, expansions, KPI queries, end reason, boundary and backup_load
  status, per condition. No sentence that says which condition did better;
  the table says it.

## 4. Rules

- Every number and every word on the page comes from the run files; if a
  file is missing, the page says "not recorded" in that place rather than
  guessing.
- Use the area names from the State (`geography.areas[id].name`) next to
  the ids everywhere.
- Figures at 1600 by 900 pixels, 150 dpi, no title inside the figure larger
  than 14 pt; the page sets the step title above the figure.
- Colours fixed as listed, the same in every figure; one legend per figure.
- Keep the script deterministic: running it twice gives the same files.
- Write `<DIR>/README.md` with the command that produced the page and the
  run directories it read.

## 5. Check

Open `index.html`, step through: the first figure is State 0, every step
has a figure, the direction shading turns from red and yellow to green as
the run closes, the final map's class counts equal the totals in
`final_report.json`, and the closing table matches `run.json`.
