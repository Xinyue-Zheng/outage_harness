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

## Unit

The unit of comparison is (site, bin, area), the unit the completion
check reasons in: one activity area inside one 30 degree bin of one
site. An area crossing two bins is two units. Points are samples; two
runs never query the same points, so nothing below compares points
one to one.

Per run, from the point records:

- reached: units with at least one queried location;
- covered: units with at least one queried location where any cell of
  the unit's site is at or above -110 dBm;
- hole: units with at least one covered location where no backup cell
  is at or above -110 dBm. Take the backup list from the location's own
  record;
- covered locations within reached units: the count of covered
  locations, summed per unit.

Distances are from the unit's site, the same distance the completion
check uses for that site's bins. Use the location record's stored
distance; if the record has none, compute from the stored coordinates
with the same function the check uses and say which.

## Exclusive discovery, both directions

For runs A and B of one case:

- exclusive units of A: units covered by A that B never reached (no
  queried location at all);
- shared unit: a unit reached by both;
- for each run and shared unit: `farthest_queried_m` among the run's
  queried locations in the unit, and `farthest_covered_m` among its
  covered ones (null when none);
- exclusive extension of A over B in a shared unit: the covered
  locations of A in the unit farther from the site than B's
  `farthest_queried_m` plus `EXTENSION_MARGIN_M` = 100. Record each
  location's distance past B's farthest queried location.

The same for B over A. The test in both parts is "the other run never
queried there", so neither is sampling variance.

## Tables

One table per case, two rows (rule, model), the columns below in this
order. Every value names the file and field it comes from; a missing
field is written as "missing: <field>", never estimated.

Resources:

| column | source |
|---|---|
| end reason | run.json `end_reason` |
| time (min) | `resources.seconds.total` |
| decision time (min) | `resources.seconds.decision` |
| program time (min) | `resources.seconds.program` |
| rounds | `budget.round` |
| rejected rounds | count of `rejections` |
| locations charged | `budget.locations_used` |
| KPI executed calls / cell-queries | `resources.kpi.calls`, `.cell_queries` |

Findings:

| column | definition |
|---|---|
| units reached | as above |
| units covered | as above |
| units with a hole | as above |
| covered locations in reached units | as above |
| exclusive units: covered / holes | units covered by this run, never reached by the other |
| exclusive extension: units / locations / holes | within shared units, this run's covered locations past the other run's farthest queried location |
| max extension (km) | the largest distance past the other run's farthest queried location |
| bins closed / total | from the final state, 12 per site |
| farthest covered per site (km) | one value per site |
| backups with a baseline / observed | cells seen in coverage results; of those, with a fetched KPI baseline |
| locations per covered unit | locations charged over units covered |

Below each table:

- the exclusive units of each run, with site, bin, area and farthest
  covered distance; at most ten per run;
- the exclusive-extension units of each run, with this run's farthest
  covered, the other run's farthest queried, and the count of extension
  locations, in descending order of extension; at most ten per run;
- the shared-disagreement count only: shared units covered in one run
  and not the other. Do not list them.

## Map

One map per case: the activity areas as outlines; each site with its
final active area outline per run; every queried location of both runs
in the run's colour; covered locations as filled markers; holes marked;
exclusive-extension locations with a ring marker in the finding run's
colour. The map reads the script's output only.

## Note

After the tables, at most eight lines per case: the exclusive counts in
both directions, where the model-only units and extensions lie relative
to the rule's final active areas, and whether the time split explains
the rule's point count in case 3. Report `EXTENSION_MARGIN_M`. No
recommendations.
