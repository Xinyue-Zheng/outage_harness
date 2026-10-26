# Prompt for the Copilot: a "Takeaways and next steps" page

Add one page to the presentation system, reachable from the top navigation
as the last entry, "Takeaways and next steps". Same single-file rules as
the other pages (inline CSS and JS, opens from the file system, projector
friendly). The numbers on this page come from the run directories through
the existing scripts; the text is given below verbatim and is typed into
the page as content, not generated.

The page is read in one scroll, in three blocks. Each block is one figure
or table with one sentence under it; no bullet lists on screen.

## Block 1. What the three conditions did

A table, full width, three rows and three columns, with the condition
name in the first column set in bold and the row for the rendered state
given a light accent background so the eye lands on it last.

| condition | what happened in the runs | consequence in the report |
|---|---|---|
| Codex-style state (concat) | calls finish early, often before every area is queried and before the KPI window is fetched | areas missing from the report; backup load unknown; classes rest on signal only |
| Concat with completion check | runs to completion because the program refuses the early finish | many more rounds; repeated invalid actions, such as queries for areas that do not exist, each caught by the validator |
| Rendered state | completes within the cap with valid actions | all areas and the KPI window in the report |

Sentence under it: "The completion check decides whether the investigation
finishes; the state organization decides how many rounds and how many
invalid actions it takes to get there."

Directly below, a second, smaller table generated from the runs, one row
per case and condition: rounds, invalid actions (validator rejections),
areas queried of areas known, KPI window fetched (yes or no), finished
(complete, cap, program stop). Read these from `run.json`, `steps/*/
validation.json`, `completion_checks.json` and `calls.json`; leave a cell
"–" when a run does not exist. Caption: "Numbers from the runs shown on
the earlier pages."

One line in smaller type under both tables: "Not shown yet: whether the
finished report is right. That is what the ground truth comparison is
for, and why only three cases carry it."

## Block 2. What evolves and what stays fixed

A two-column figure. Left column, headed "Stays fixed": four boxes in a
column, the model weights, the validator code, the completion check code,
the classification rule. Right column, headed "Evolves, each with its own
score": five boxes, each with its name, its representation in one line,
and what drives it in one line:

| box | representation | driven by |
|---|---|---|
| Playbook | scoped text items (terrain, technology, phase) | rejections, wasted rounds, areas left open, verifier flags |
| Case memory | per-case records: terrain, outage set, areas that mattered, backups that carried load; selected by the program by terrain and technology | the scored run of each case |
| Fitted tools | the redistribution model's parameters; the KPI window rule; the direction-bin constants | observed KPI against estimates, across cases |
| Guarantee table | thresholds, required checks, which open items block completion, probe radii | extent misses and early stops from the truth; rounds and rejections from the traces |
| Verifier checklist | the consistency checks applied before a stop is accepted | cases where validator and model passed and the truth disagreed |

Draw a thin arrow from a single box at the bottom, "Ground-truth scorer
(area recall, degraded and congested shares, class distance, cost)", up
into each of the five boxes on the right. Two of the right-hand boxes,
Fitted tools and Guarantee table, get a small tag "by fitting"; the other
three get "by reflection".

Sentence under it: "The model stays frozen and the code stays fixed; what
evolves is the advice, the memory, the fitted tools, the guarantee
parameters, and the verifier's checks, each with its own score."

## Block 3. Next steps

A six-row table, numbered because the order is the plan. Rows 1 to 3 in
the normal text colour, rows 4 to 6 with a thin left border in the accent
colour to mark the self-evolving part.

| step | what is done | what it produces |
|---|---|---|
| 1. Refine the ground truth | recompute the per-point record from stored samples and observed KPI, with the sample count kept and no-sample points apart; impact truth at the agent's own points; the scan kept for extent only; next cases scanned over the areas plus one band | a truth reproducible from stored data, dense where the agent looked, cheaper for new cases |
| 2. Score the existing runs | the area-level scorer and the per-area figures on the three cases; no new calls | area recall, degraded and congested shares, class distance, cost, per condition |
| 3. Rule policy as the floor | the five-rule policy on the same cases under the same program | the line every model condition must beat |
| 4. Evolve by fitting | the redistribution parameters on observed load; the guarantee table under the recall-against-rounds score | a calibrated load model; the tightness trade-off that was tuned by hand so far |
| 5. Evolve by reflection | playbook items and case memory from scored traces; held-out terrain decides acceptance | a playbook and a memory with provenance per item, and the before-and-after curve |
| 6. Verifier checklist | from the cases where everything passed and the truth still disagreed | the checks applied before a stop is accepted, and the share of those cases they catch |

Sentence under it: "Steps 1 to 3 need no new design; steps 4 to 6 are the
self-evolving part, each with a before-and-after number from the same
scorer."

Last line of the page, set apart with space above it: "The limit today is
three cases with a ground truth. The ask is cases."

## Layout notes

- Headings in sentence case; the three block headings are the three
  sentences "What the three conditions did", "What evolves and what stays
  fixed", "Next steps".
- Tables use the page's existing table style; the first column no wider
  than a quarter of the width; cells wrap.
- The figure of block 2 is drawn in SVG inline, boxes with the page's
  border colour, the accent colour only for the arrows and the two tags.
- Nothing on this page needs the real coverage pictures, so this page may
  be exported and shared on its own; give it its own file
  `takeaways.html` as well as the navigation entry.
