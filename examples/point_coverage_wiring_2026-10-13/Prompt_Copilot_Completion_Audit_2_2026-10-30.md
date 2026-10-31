# Prompt for Copilot: finish the completion audit with an offline script

Paste the text below to Copilot as is. It follows
`Prompt_Copilot_Completion_Audit_2026-10-30.md`.

---

Your audit stopped because the ground-truth JSON is too large to open in
the editor. You may finish it with one script, under these rules:

- The script reads local files only: the ground-truth files, the run
  directories (steps, completion check records, geometry, run.json). It
  calls no service and makes no network request.
- It changes nothing in the packages. Put it in a scratch folder outside
  them, with its own README that says what it reads and what it writes.
- It writes one CSV per run with one row per ground-truth covered location
  the run never queried, and one summary table. Show me the summary and at
  most ten example rows per cause. Do not paste the CSVs.
- Run it once per run and report the command you ran.

Definitions to use:

- Covered: ground-truth RSRP at or above -110 dBm for any down cell, the
  same rule the check uses. Report separately how many locations change
  class if the rule is strictly above -110, so the two populations are
  distinguished.
- Coverage hole: the ground-truth record lists no backup at or above
  -110 dBm. Take it from the record's own backup list, not from any
  plotting manifest.
- In activity area: the location's grid id belongs to a settlement or
  corridor in the run's saved geometry. Report locations outside every
  activity area as their own group; the check cannot reach them by design
  and I need their count.

For each unqueried covered location, the CSV row carries: grid id, down
cell(s) covering it, strongest RSRP, hole yes or no, in-activity-area yes
or no with the area id, the down site whose cell covers it, the bin from
that site, the bin from WTL03023 (the origin the check used), distance
from each, and the cause letter from the first prompt (a to g), with the
counts the check read for that bin and area at the closing round.

Then answer, from the CSVs:

1. Totals per cause letter, per run, split by hole and not hole, and by in
   or outside activity area.
2. How many of the missed locations are covered by WTL05870 cells, and in
   how many of those the bin from WTL03023 differs from the bin from
   WTL05870. This measures the single-origin problem.
3. For bins that closed with zero sampled locations beyond the boundary
   (reason "all activity areas within boundary reach evaluated"): how
   many such bins per run, and how many missed locations lie in them
   beyond the boundary.
4. For each run, the first round at which each affected bin was declared
   closed, from the step records.

If a field is missing from the saved records, name the field; do not
infer it.
