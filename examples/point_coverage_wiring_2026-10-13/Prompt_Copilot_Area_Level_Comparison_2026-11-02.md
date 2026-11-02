# Prompt for Copilot: area-level comparison of rule and model runs

Paste the text below to Copilot as is, in a fresh session, and fill the
run directories in the first line.

---

Run directories: <rule run 1>, <model run 1>, <rule run 2>, <model run
2>, <rule run 3>, <model run 3>. Each pair is one case. Compute one
comparison from the stored files only: run.json, the final state, the
point records and the geometry of each run. Make no service call, read
no ground truth, change no code. Put the script in a scratch folder
outside the packages with a README that says what it reads and writes.
Run it once per case and report the commands.

Unit of comparison: (site, bin, area), the unit the completion check
reasons in. Points are samples; two runs never query the same points,
so nothing below compares points.

Per run, derive from the point records:

- reached: units with at least one queried location;
- covered: units with at least one queried location where any cell of
  the unit's site is at or above -110 dBm;
- hole: units with at least one covered location where no backup cell
  is at or above -110 dBm. Take the backup list from the location's own
  record.

Per case, one table with the rule and the model as columns:

1. End reason, minutes, points charged, rounds, rejected rounds.
2. Time split in minutes: decision, program, coverage, KPI, OSM, idle,
   if run.json has it; otherwise write "missing: <field>".
3. Units reached, units covered, units with a hole.
4. Exclusive discovery, both directions: units covered by this core and
   not reached by the other core; the same for holes. List those units
   with site, bin, area and the farthest covered distance in them.
5. Shared disagreement: units reached by both, covered in this core and
   not in the other. These are sampling differences; report the count
   only.
6. Reach: farthest covered distance per site; bins closed per site out
   of 12; activity areas reached out of the areas within the case
   geometry.
7. Backup cells observed, backup cells with a fetched baseline, KPI
   executed calls and cell-queries.
8. Cost per finding: points and minutes per covered unit found.

Then one map per case: the activity areas as outlines, units coloured
by which core found them covered (rule only, model only, both), holes
marked, each site with its final active area outline per core. The map
reads the script's output only.

After the tables, write at most eight lines per case: the exclusive
discovery counts in both directions, where the model-only units lie
relative to the rule's final active areas, and whether the rule's
smaller point count in case 3 is explained by the time split. No
recommendations.

If a field is missing from the saved records, name it; do not infer it.
