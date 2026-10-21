# Ground truth: additions since the version you were given

`Ground_Truth_Process_2026-10-27.md` was handed over once and has changed
since. This file lists only the additions, in the order they were made,
each as a self-contained edit to `make_ground_truth.py` and the shared
modules. For every item, first check whether your copy already has it (the
check line says how); if it does, skip the item. The full current
instruction is the file named above, at the same path; this file does not
replace it.

The repository versions, newest last, so you can tell which you have:
`bb9d2b3` (ten steps), `7c10f3a` (preamble and check), `a5ec7b1`
(wording), `aedcc12` (site ids, 3 to 24 hours, tqdm), `d930c46` (missing
KPI), `1566429` (technology), `38c787f` (NR pattern), `88d6146` (same-site
backups).

---

## A. Wording (`a5ec7b1`)

Check: the preamble says "It is a measurement script: no language model,
no verifier, no decision loop". If not, replace the preamble's second
paragraph with that sentence and read the file's prose with "the
investigation code" where "harness" stood; nothing in the code changes.

## B. Site id to cell ids; the outage must last 3 to 24 hours (`aedcc12`)

Check: the constants table has `DOWN_MAX_HOURS = 24` and step 2 has the
verdicts `site_up` and `long_outage`.

Edits:

1. Constants: add `DOWN_MAX_HOURS = 24`.
2. Step 2 reads: the ticket names a site id; the cells of the site are
   every cell whose id starts with it, taken from the metadata and from
   the heatmap's candidate list. Query the month of KPI for all of them
   and for every other candidate.
3. Step 2 verdicts, per cell, from its zero runs over the month:
   - `down`: a run of at least `DOWN_MIN_HOURS` and at most
     `DOWN_MAX_HOURS` hours that overlaps the ticket interval and is not a
     regular zero;
   - `long_outage`: a zero run longer than `DOWN_MAX_HOURS`, or zero
     through most of the month; excluded from the outage set and from
     the backups (it was not serving before the outage either);
   - `site_up`: a cell of the site with no qualifying run; excluded from
     the outage set (its backup role is item F);
   - `idle`, `regular_zero`, `up` as before.
4. The outage set is the site's cells with a qualifying run plus every
   candidate found down for a qualifying run. A ticket whose site has no
   cell with a qualifying run is dropped, flag `no_short_outage`, no
   directory written.
5. `outage_set.json` carries the verdicts and the flags above.

## C. Progress display (`aedcc12`)

Check: the script imports `tqdm` and the point fetch takes a bar.

Edits: one `tqdm` bar per step, named for the step ("step 5: sampling 37
areas"), advanced per cell (KPI steps), per area (sampling, filling), per
location (every point fetch; the bar is passed into `fetch_area_points` by
the caller so the investigation packages can use it too), per pass (the
fill loop), per figure (step 9). Postfix: the running counts that matter
(hit areas, cache hits, api calls, errors). Bars to stderr; `--quiet`
turns them off.

## D. Missing KPI (`d930c46`)

Check: the constants table has `KPI_MIN_ROW_SHARE = 0.5` and
`BASELINE_MIN_SAMPLES = 2`, and a file `kpi_availability.json` is written.

Edits, as a new step 2b:

1. Row share per cell: the share of the month's hours with a row. Below
   `KPI_MIN_ROW_SHARE`, verdict `no_kpi`: excluded from the outage set,
   `no_data` in every hour as a backup, never treated as zero.
2. Gaps inside a usable month: a missing hour counts as zero only inside a
   run that has explicit zero rows next to it; with populated non-zero
   hours on both sides it is `no_data` for that hour; a run of missing
   hours only is not a down run.
3. The site: every cell `no_kpi` drops the ticket (flag `no_kpi`); some
   `no_kpi` cells are listed and the outage set is built from the others.
4. Baselines (step 8): at least `BASELINE_MIN_SAMPLES` of the four
   same-weekday-hour samples; fewer, use the month's mean at the same
   hour of day, marked `fallback`; none, `no_baseline`, and the RRC gain
   for that hour is `no_data`.
5. Per point (step 8): the two fractions exclude `no_data` backups from
   the denominator and record the excluded count; a point whose reachable
   backups all lack data for an hour is `no_backup_data`, distinct from
   `no_backup`.
6. Report: a section "KPI availability": per cell the row share and
   verdict; per outage hour the share of backups with data; `no_backup_data`
   points per area. Three caveats on the first lines instead of two.
7. Writes `kpi_availability.json`, read by steps 8 and 9.

## E. Technology (`1566429`, `38c787f`)

Check: step 2c exists and `radio.radio_technology` matches
`^[A-Z]{3}\d{5}` for LTE and `^[A-Z]{4}\d{6}` for NR.

Edits:

1. First, verify the two patterns in `radio.radio_technology` of every
   package and in `policy.route_kpi_cells`: three letters and five digits
   is LTE (`CCL06069...`), four letters and six digits is NR
   (`CCSN003553...`). A recent edit may have set NR to five digits, which
   routes every NR cell to the LTE tool. Fix, and add a test with the two
   example ids.
2. The outage set's technologies decide the backups: LTE only, only LTE
   backups; NR only, only NR; both, each handled separately with separate
   fractions and tables. Cells of the other technology seen in coverage
   are recorded as `other_technology`, never fetched for KPI, never
   counted at a point.
3. Apply the rule before any KPI call; route by the same pattern, one
   call per technology per step. Step 1's candidate list carries each
   cell's technology.

## F. A surviving same-site sector is a backup (`88d6146`)

Check: step 2 says a `site_up` cell is "a backup like any other cell of
its technology, flagged `same_site`", and `radio.eligible_backup_cells`
excludes only the confirmed outage set.

Edits:

1. A `site_up` cell is excluded from the outage set but is a backup like
   any other cell of its technology, flagged `same_site` in the backup
   tables.
2. `radio.eligible_backup_cells` in every package excludes only the cells
   of the confirmed outage set (the task's `outage_cell_ids`), not every
   cell matching the site prefix. (You may already have made this change;
   the check line tells.)

---

## Order

A has no code. Apply B, then D, then E, then F; C at any point. After all
of them, the current `Ground_Truth_Process_2026-10-27.md` describes your
copy exactly, and its Check section applies.
