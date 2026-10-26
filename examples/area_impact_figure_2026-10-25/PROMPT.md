# Prompt: draw the area impact figure for every case

Give Copilot three files with this prompt: `area_impact_reference.py`,
`area_impact.png` and `area_impact_prb_hours.png`. Paste the text below as it is.

---

Draw the area impact figure for every case: ground truth against the agent run, per area, from stored data only. No API call, no model, no rerun.

**Use `area_impact_reference.py` as the drawing code.** It already draws the agreed figure from one input JSON. `area_impact.png` is what the output must look like, and `area_impact_prb_hours.png` is the hour strip. Do not redesign the figure and do not change the drawing functions, the colours, the point rule, or the paragraph wording in the script. Your work is the adapter: build the input JSON for each case from `ground_truth.json`, the run's `score.json` and its last state file, then run the script. To see a sample input, run `python area_impact_reference.py --synthetic <dir>`; it writes `area_impact_input.json` there.

Input shape:

- `site`, `outage_start`, `hours` (the outage hours as "HH:00").
- `areas[]`: `id`, `name`, `kind`, `polygon_km` (the area outline as a list of [x, y] in km east and north of the site; build it from the area's grid ids as their convex hull or, for a settlement disc, 40 points on the circle), and `extent_recall` from `score.json` (null when the area is not compared).
- `points.truth[]` and `points.agent[]`, one record per queried location: `x_km`, `y_km`, `area_ids` (every area whose grid ids contain the location), `status` one of `covered`, `no_backup`, `uncovered`, `no_sample`; for `covered` points `n_backups` (reachable backups: in the same sample as an outage sector at -110 dBm or better, eligible), `n_degraded` (of those, more than 10 dB below the outage sector or below -110 dBm), and `hours[h] = {with_data, congested}` (backups with a KPI row for h, and of those with PRB above 80 %). For the agent side, `congested` uses the estimated PRB from `redistribution.json`; for the truth, the PRB observed in that hour.

The script computes everything else with one rule on both sides: a point is signal-degraded when at least half of its backups are degraded, congested at h when at least half of its backups with data are congested; area shares are shares of covered points. Check that the per-area shares it prints equal `f_rsrp_ge_half`, `f_prb_ge_half[h]` and `no_backup_share` in `score.json` for the same area and side; a difference is a bug in the adapter or in `score_run.py`, to fix before any figure is used.

Run it per case and condition: `python area_impact_reference.py <input.json> <run dir>/figures`. Outputs: `area_impact.png` and `.svg` (signal row, capacity row at the worst truth hour, one panel per area), `area_impact_prb_<HH00>.png` for every hour, `area_impact_prb_hours.png` (all hours as a strip), `area_impact.md` (one paragraph per area).

If a case has areas the script cannot place (no grid ids), list them in the run's README and leave them out of the figure.
