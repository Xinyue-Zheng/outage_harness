# Prompt for Copilot: exclusive extension within shared units

Paste the text below to Copilot as is. It adds one computation to the
script of `Prompt_Copilot_Area_Level_Comparison_2026-11-02.md`.

---

Add to the area-level comparison script one more computation, exclusive
extension, and one row to each case table. Same rules: stored files
only, no service call, no ground truth, no code change in the packages.

Why: a unit (site, bin, area) counts as reached after one query. When
the rule queried the near end of a road and the model found coverage
2 km farther along the same road, the unit is shared and the model's
finding is hidden in the shared-disagreement count. It is not sampling
variance: the rule never queried there.

Definitions, for one case with runs A and B:

1. Shared unit: a unit reached by both runs.
2. For each run and shared unit: `farthest_queried_m`, the largest
   distance from the unit's site among the run's queried locations in
   the unit; `farthest_covered_m`, the same among its covered locations
   (null when none).
3. Exclusive extension of A over B in a shared unit: the covered
   locations of A in the unit whose distance from the site is greater
   than B's `farthest_queried_m` in that unit plus `EXTENSION_MARGIN_M`
   = 100. Record for each such location its distance past B's farthest
   queried location.
4. The same for B over A.

Distances are from the unit's site, the same distance the completion
check uses for that site's bins. Use the location record's stored
distance; if the record has none, compute from the stored coordinates
with the same function the check uses and say which.

Per case, add to the table one row per run:

- `exclusive extension: units` — shared units in which this run has at
  least one exclusive-extension location;
- `exclusive extension: covered locations` — the count of those
  locations;
- `exclusive extension: holes` — those with no backup at or above
  -110 dBm;
- `max extension (km)` — the largest distance past the other run's
  farthest queried location.

List the units with site, bin, area, this run's farthest covered, the
other run's farthest queried, and the count of extension locations, in
descending order of extension distance; at most ten per run.

Add the extension locations to the per-case map as a distinct marker
(for example a ring around the covered marker), in the colour of the run
that found them.

Report `EXTENSION_MARGIN_M` in the output. Rerun the script on the three
cases and give the three tables with the new rows and the lists.
