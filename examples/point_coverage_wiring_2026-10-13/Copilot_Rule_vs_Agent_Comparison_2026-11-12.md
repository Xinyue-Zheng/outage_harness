# Rule against agent: published selection rules adapted to the harness, and one comparison on shifted conditions (instruction for the Copilot)

Apply to the repository that holds `outage_harness_langgraph`,
`outage_harness_rule_based` and `outage_harness_evolution`. This
instruction does three things, in this order:

1. It adds selection rules taken from the literature, in two forms: two
   scores inside the rule core, which keep the harness's completion check
   and legal requests, and one method that runs without the harness and
   stops by a statistical rule.
2. It adds one status for backup cells, `inactive`: a cell that coverage
   samples list and the KPI data has no row for (part 8).
3. It runs one comparison of every rule and the model core on the same
   case, replayed from the full-read reference of
   `Copilot_Reference_Full_Scan_2026-11-10.md`, under the stored
   conditions and under six shifted conditions.

The Copilot CLI baseline of `Copilot_Baseline_Copilot_CLI_2026-11-11.md`
comes after this instruction and adds one row to the tables through its
own compare script. Do not start it now.

Why. The current rule core takes the open items nearest first with a
fixed pattern and a fixed count. It never reads the budget, the sample
rate or the cost. A comparison against that rule alone does not show
whether a model is needed, because a better rule may close the same gap.
The rules added here are the forms the literature gives for this problem.
The comparison then asks one question: with every selector fixed in
advance, which ones keep working when the conditions change. A rule's
behaviour under a condition nobody wrote a term for is fixed. A model
reads the condition from the rendered state. If a model is needed in the
loop, that is where it shows, and if it does not show there, the tables
say so.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory.
- Do not run `uv sync` and do not add dependencies.
- Harness edits are limited to two: in `outage_harness_rule_based`, one
  new file `scores.py` and one dispatch in rule R1 (part 2); and the
  backup activity function with its call sites in the classification and
  report code (part 8). With `RULE_SCORE=domain`, the default, every
  proposal is the same as today. Neither edit changes the rendered
  context, the skill text, the completion check or any query a run
  sends. Bump `HARNESS_VERSION` by hand, once, and record the old and
  new strings. The concat packages are not edited.
- Everything else is new modules in `outage_harness_evolution`:
  `replay.py`, `freeform.py`, `matrix.py`.
- Tests write only under `tmp_path`.
- Outputs go to `<results root>/rule_vs_agent/<site>/`.
- No point API call is made by anything in this instruction. KPI calls go
  through the existing KPI client and cache, unchanged.

Commands:

```
python -m outage_harness_evolution.matrix --reference <reference dir> --model-run <stored model-core run dir> --rule-run <stored rule-core run dir> --out <results root>/rule_vs_agent --plan
python -m outage_harness_evolution.matrix <same arguments> --run rules
python -m outage_harness_evolution.matrix <same arguments> --run freeform
python -m outage_harness_evolution.matrix <same arguments> --run model [--worlds W0,W1,...] [--repeats 3]
python -m outage_harness_evolution.matrix <same arguments> --tables
```

Every number comes from a run record, the reference, or a file an earlier
step wrote. An absent value is `not recorded`.

## 0. Prerequisite and constants

Prerequisite: ring 1 of the reference is complete (`ring_1.json`
exists). Ring 1 is the 30 km window the runs use. Rings 2 and 3 are used
when present.

Constants, at the top of `matrix.py` unless a module is named:

| name | value | meaning |
|---|---|---|
| limits | read from `--model-run` | `max_query_locations`, `max_kpi_cell_queries`, `max_time_seconds` from `run.json.limits`; never retyped |
| model flags | read from `--model-run` | model name, `RECOVERY`, every launch flag the run record holds; the replayed model runs use the same |
| rule setting | read from `--rule-run` | the setting of rule R1 that run used (`run.json`) |
| `MODEL_REPEATS` | 3 | model runs per world; `--repeats` overrides |
| `SHIFT_SEED` | 20261112 | seed of every random choice in part 4 |
| `RULE_REPLAY_SECONDS` | 900 | time limit of a replayed rule-core run; see part 1 |
| `INACTIVE_MIN_WEEKS` | 4 | baseline weeks a cell must have been queried for, with no row, before it is `inactive` (part 8; defined beside the function) |
| `MIN_OBS` | 20 | observations a stratum needs before its own rate is used (`scores.py`) |
| `BAND_M` | 1000 | width of a distance band from the site (`scores.py`) |
| `FF_BATCH` | 50 | locations the free-form method reads per round (`freeform.py`) |
| `FF_ALPHA` | 0.05 | one minus the confidence of the stopping bound (`freeform.py`) |
| `FF_EPS` | (0.26, 0.10, 0.05) | the bound at which a wedge closes; one run per value (`freeform.py`) |
| `FF_PROBE_SHARE` | (0.0, 0.1) | share of the budget spent on a sparse probe first; one run per value (`freeform.py`) |
| thresholds, `N_MIN_SAMPLED`, `BIN_DEGREES`, `MAX_REQUESTS_PER_ACTION` | imported from the harness modules that define them | one definition |

## 1. Replay

`replay.py` builds a world from the reference directory and serves it
through the same callable signature the runners already pass to
`make_point_query`: `(lat, lon, r) -> list of samples`.

- The callable maps the coordinate to a reference grid cell by the grid
  arithmetic of `window.json` (row and column from local metres). The
  centre of that cell must lie within 1 m of the coordinate, else
  `OutsideReference`. Do not join by comparing rounded coordinate
  strings, and do not use `grid_map.json` here: it covers the 30 km grid
  only, and an expansion leaves it. The callable returns the stored
  samples of the point, unchanged. A `no_sample` point returns an empty
  list. An `error` point raises the same exception the point client
  raises after its retries, so the harness's own failure path handles
  it.
- A location that has no reference record raises `OutsideReference` with
  the key. The matrix runner ends that run with
  `end_reason: outside_reference` and the location. Nothing is fetched.
- A replayed run gets a scratch point cache path inside its own run
  directory. The per-site cache is neither read nor written.
- OpenStreetMap comes from the stored copy of `--model-run` through the
  reuse path the harness already has. If an expansion needs map data the
  copy does not hold, the harness's own path fetches it; count those
  calls in the tables. KPI is not replayed.

Launch seam. Start replayed runs from a launch function in `matrix.py`
that calls the same entry point `run_case.py` calls, with the replay
callable in place of the point client. If either runner builds its point
client internally and takes no callable, stop and report the file and
line. Do not edit the runner to add a parameter without reporting first.

Replay serves a point at once, so the time cap does not bind on point
calls. Record that in every `run.json` under `replay: true`. The tables
compare locations and `calibrated_seconds` (counts times the unit costs,
as `run.json` already records), not wall time.

The harness has no round cap, so a rule that proposes the same failing
query every round would spin until the stored time limit. A replayed
rule run finishes in seconds when it works, so its time limit is
`RULE_REPLAY_SECONDS`. A rule run that ends `time_cap` in replay
therefore repeated itself without progress; the tables show it as that,
and it is a result, not an error to repair. Model runs keep the stored
time limit.

## 2. Two literature scores inside the rule core

Rules R2 (expand), R3 (KPI) and R4 (finish) stay as they are, and so
does the order R1 to R4. Only R1 changes: which open coverage items it
takes and which request it builds for each. `RULE_SCORE`, read once at
run start and written to `run.json`, selects the score:

| `RULE_SCORE` | source | what is taken from it |
|---|---|---|
| `domain` (default) | the current rule | nearest item first, fixed pattern and count |
| `expected_cost` | adaptive greedy for minimum-cost cover (Golovin and Krause, JAIR 2011; Hellerstein et al., Mathematics of Operations Research 2024) | each round, take the request with the largest expected progress toward closing everything, per unit of cost |
| `budget_aware` | cost-effective active search (Jiang, Garnett, Moseley, NeurIPS 2019) | the same, with the remaining budget in the decision: keep closure affordable while it is, and switch to finding covered locations when it is not |

What is replaced, and say so in the module docstring: those papers assume
a known probability model of outcomes and give bounds under it. Here the
two probabilities below are estimated from the run's own queried
locations, so the scoring form is theirs and the bounds do not carry
over.

### 2.1 Two estimates, from the run's own state only

Both are pure functions of the state and the geometry file. They use no
other run, no reference, no training.

- `p_samp(x)`, the probability that location `x` returns a sample. The
  stratum of `x` is one fact: whether `x` lies in any road corridor area
  or not. The estimate is `(1 + sampled) / (2 + queried)` over the
  queried locations of that stratum inside the area of the request being
  scored, when there are at least `MIN_OBS` of them; else over the
  stratum in the whole run; else, when the run has queried no location
  of the stratum, 0.5. The method of part 3 has no request area and uses
  the run-wide stratum.
- `p_cov(x)`, the probability that `x`, if it returns a sample, shows an
  outage sector at or above the coverage threshold. The stratum is (the
  `site/index` bin of `x`, the `BAND_M` distance band of `x` from that
  site). The estimate is `(1 + covered) / (2 + sampled)` over the sampled
  locations of the first of these that has any: the stratum; the nearest
  band toward the site in the same bin; the same band in all bins of
  that site; every sampled location of the run. It is 0.5 only when the
  run has no sampled location at all. The second step assumes that
  coverage does not become more likely with distance; state that in the
  docstring.

`p_cov` is used only by the scarce mode of part 2.3 and by the ordering
of part 3. It is not part of `P_close`. A sampled request that finds
coverage is not wasted: the boundary moves and those locations would
have been read as interior locations anyway. Charging for it would also
make every sampled request score near zero in a band with no
observation yet, and the rule would fall back to reading whole areas.

### 2.2 `expected_cost`

Candidates: for every open coverage item (area, bin) of the completion
check, every template `legal_requests(area_id, bin_key, state)` returns.
For a template with a count range, try every `n` from the range minimum
up to the range maximum or eight times the
samples still needed, whichever is smaller. For each candidate, get the
location set `X` the program's own selector would choose for it. If the
selectors cannot return the set without executing the query, stop and
report.

Per candidate:

- `cost` = the new locations in `X`.
- `P_close`: for an `inside` request or `all`, 1. For a sampled request
  on a beyond item, `P(Binomial(|X|, mean p_samp over X) >= need)`,
  where `need` is `N_MIN_SAMPLED` minus the locations of that (area,
  bin) that already returned a sample, not below 0. It is the chance of
  getting the samples the item still needs.
- `progress` = `P_close` times the cost the floor record counts for that
  item (`inside_unqueried` for an inside item, the item's
  `min_action_locations` for a beyond item).
- `score` = `progress / cost`.

Selection: sort candidates by score, highest first; ties by the area's
distance from the site, then area id. Take the best candidate of the
best item, then of the next item, up to `MAX_REQUESTS_PER_ACTION` items,
and send one action. The rejection rule of
`Copilot_Rejection_Handling_2026-10-31.md` part 3 is unchanged: a
rejected item is skipped for the round.

### 2.3 `budget_aware`

Read `left` (locations left) and the floor's `locations` from the state.

- While the floor is at most `left`: use `expected_cost`, after removing
  every candidate whose cost exceeds `left` minus the floor cost of all
  other open items. If that removes every candidate, keep them all.
- When the floor exceeds `left`: closing everything is not affordable.
  Rank every candidate with `cost <= left` by expected covered locations
  per location, the sum over `X` of `p_samp(x) * p_cov(x)` divided by
  `cost`, and take the best ones as above. `run.json` records the round
  of the switch as `scarce_from_round`. If no candidate fits, R1
  proposes nothing and the existing rules and guards apply.

The step record of every R1 round under either score holds the chosen
candidates with `cost`, `need`, `P_close`, `score` and the mean
`p_samp`, so a reader can recompute the choice. The next step record of
the same item holds the samples the request returned, so predicted and
realized can be compared (part 6).

## 3. One literature method without the harness

`freeform.py` is the method the literature would run in place of the
whole harness: no areas as actions, no completion check, no legal
requests. It reads activity locations of the reference one batch at a
time and stops by a confidence bound. It exists only in replay.

Source and adaptation:

| source | what is taken | what is replaced |
|---|---|---|
| level-set estimation (Gotovos et al., IJCAI 2013) | classify every location against a threshold; sample where the class is undecided; stop a region when a confidence bound decides it | the Gaussian process is replaced by a binomial bound per wedge, because the project has no such library and adds none |
| active search (Garnett et al., UAI 2012; Jiang et al., ICML 2017) | among undecided places, read first where a covered location is most likely | the probability model is the two estimates of part 2.1 |
| global phase before local phase | a sparse probe over the whole window before the outward sweep | optional, `FF_PROBE_SHARE` |

Input: the world, the site position and outage sectors of the case, the
activity locations of every reference ring that is complete, the
location limit of part 0. A wedge is a `BIN_DEGREES` direction bin from
the site, as in the completion check. With more than one outage site,
there is one set of wedges per site, keyed as the completion check keys
them, and a location is covered for a site when it shows a sector of
that site.

Loop:

1. Probe, only when `FF_PROBE_SHARE` is above 0: read
   `FF_PROBE_SHARE` times the limit locations chosen by farthest-point
   sampling over all activity locations, starting from the one nearest
   the site.
2. Per wedge, `F` is the distance of the farthest covered location found
   so far, 0 when none. Candidates of the wedge are its unread locations
   nearer than `F`, and the unread locations beyond `F` while the wedge
   is not closed.
3. A wedge closes when the `m` sampled locations nearest beyond `F`, in
   distance order with no covered one among them, give
   `1 - FF_ALPHA ** (1 / m) <= eps`, or when it has no unread location.
   A location with no sample does not count toward `m`. A covered
   location beyond `F` moves `F` and the count starts again.
4. Read the `FF_BATCH` candidates with the highest
   `p_samp(x) * p_cov(x)` over all wedges; ties nearer first. The
   locations beyond `F` of one wedge enter a batch in distance order: a
   location may be in a batch only if every nearer unread location
   beyond `F` of its wedge is in the same batch. A failed call is
   charged, recorded as `error`, does not count toward `m`, and is not
   retried.
5. Stop when every wedge is closed (`end_reason: closed`) or the limit
   is reached (`query_budget`).

Output per run: the read locations in order with their class, the
closing bound and `m` per wedge, `end_reason`, locations used. With the
three `FF_EPS` values and two `FF_PROBE_SHARE` values, six runs per
world. Record in the summary that `eps = 0.26` is the bound that 10
sampled locations give at 95 percent, the count the completion check
uses.

## 4. Shifted worlds

Each world is the reference with samples removed or calls failed. A
shift only removes; it never adds a location, so every world stays
inside the reference. Every random choice hashes the reference key with
`SHIFT_SEED` and the world id, so a world is the same for every
condition.

| world | change | what it stands for |
|---|---|---|
| `W0` | none | the stored conditions |
| `W1` | every location loses all its samples with probability 0.7 | sparse measurement |
| `W2` | every location outside all road corridor areas loses all its samples with probability 0.9 | measurements along roads only |
| `W3` | the location limit is half the stored limit | tight budget |
| `W4` | the location limit is a quarter of the stored limit | closure not affordable |
| `W5` | every point call for a location of one area fails; the area is taken from the reference `areas.json`: the settlement or corridor with the most locations among those whose nearest location is 3 to 8 km from the site | a data source that does not answer |
| `W6` | every location within 2 km of the site loses all its samples | a measurement gap at the site: no sample is not no coverage |

Nothing tells a selector which world it is in. The model core sees the
world only through the rendered state, the rules only through the state.

Freeze. Parts 2, 3 and 8 are complete before any replayed run. Before
any run on `W1` to `W6`, write `frozen.json`: the `HARNESS_VERSION`, the
skill text file name and length, the rule setting, the constants of
part 0. Change none of them until the tables
are written. If a defect forces a change, discard every run made before
it and say so.

## 5. The run matrix

Conditions:

| id | selector | harness | runs per world |
|---|---|---|---|
| `R-domain` | current rule, stored setting | yes | 1 |
| `R-cost` | `expected_cost` | yes | 1 |
| `R-budget` | `budget_aware` | yes | 1 |
| `FF` | free-form method | no | 6 |
| `M` | model core, stored flags | yes | `MODEL_REPEATS` |

`--plan` runs nothing. It writes `plan.md` with:

- the rings present, and the count of locations of the harness's areas
  for this case that have no reference record, per area. If the count is
  not zero, stop here and report the areas;
- the launch seam found for each runner (part 1);
- the number of runs per condition and world;
- the projected hours of the model runs, from the rounds and decision
  seconds of `--model-run`.

After a plan with zero missing locations, run `--run rules` and
`--run freeform` without waiting: they make no model call and no point
call. Do not start `--run model` until the author has seen `plan.md` and
named the worlds and repeats.

Every run writes a normal run directory under
`<out>/<site>/<world>/<condition>[_<repeat>]/`.

## 6. Tables

`--tables` writes `summary.md` and `runs.json`. One row per run:

| column | definition |
|---|---|
| `end_reason`, `closed` | from `run.json`; `closed` is true when the completion check passed, or `end_reason: closed` for `FF` |
| `locations_used` | charged locations |
| `locations_no_sample` | charged locations that returned no sample |
| `required_locations` | for a closed harness run, from its final completion record: the interior locations of its inside items plus, per beyond item closed by sample, `N_MIN_SAMPLED` or the item's size if smaller |
| `excess_share` | `1 - required_locations / locations_used`, closed harness runs only |
| `covered_found` | read locations that show an outage sector at or above the threshold |
| `covered_no_backup`, `covered_no_backup_active` | among `covered_found`: locations with no reachable backup by coverage alone, and with inactive backups not counted (part 8) |
| `recall_true` | `covered_found` over the covered locations of the unshifted reference, in the rings present |
| `recall_observable` | the same against the shifted world |
| `open_items_at_end` | harness runs |
| `rounds`, `rejections`, `kpi_cell_queries` | from `run.json` |
| `decision_seconds`, `input_tokens`, `output_tokens` | model runs; 0 for rules |
| `calibrated_seconds` | from `run.json` |

Then one table per world, one row per condition, with the model shown as
median, minimum and maximum over its repeats, and three derived lines:

1. `best_rule`: among `R-domain`, `R-cost`, `R-budget`, the closed run
   with the fewest locations; when none closed, the run with the highest
   `recall_true`.
2. `model_against_best_rule`: when both closed, the difference in
   locations; otherwise the difference in `recall_true`; and whether the
   difference is larger than the model's own minimum-to-maximum range.
3. `excess_share` of `best_rule` on `W0`. A small value means the
   completion check fixes most of the cost and no selector can save much
   under the stored conditions.

Then `calibration.md`, for `R-cost` and `R-budget`: every sampled
request grouped by predicted `P_close` in five equal bins, with the
share that did return the needed samples, and the mean predicted and
realized sample rate per stratum. The binomial treats locations as
independent; samples cluster along roads, so this table shows how far
that assumption is off.

Then `cost_recall.md`: for each world, every run as a point
(`locations_used`, `recall_true`), so the six free-form runs form a
curve and the harness runs are points beside it. Write the same data as
`cost_recall.json`. No figure.

## 7. Round-level comparison, from the model runs, no extra model call

`--tables` also writes `rounds.md`. For every model round that sent a
coverage action, compute what `expected_cost` selects from that round's
`state_before` (the score is a pure function of the state). Then, for
the model's action and for the rule's selection, look up in the world
what the location sets return: locations, samples, covered locations,
and whether each item closes by the counts the check uses (the samples
still needed are returned and none is covered, or the area is read in
full). The rule's selection is evaluated, not executed.

Report per world: rounds where the two name the same items; rounds where
the model named an area that was not an open item; and, for the rounds
that differ, how often the model's action gave more covered locations
per location, and how often more closed items per location. List the ten
rounds with the largest difference either way, with round number, both
actions and both outcomes.

## 8. Inactive backup cells

Why. Building the ground truth showed backup cells that coverage samples
list and that have no KPI row at all over the stored period. Such a cell
is not shown to carry traffic, so counting it as a backup understates
the locations without one. The data does not say why the rows are
absent: the cell may be retired or renamed, the table may have a gap, or
the cell id may have gone to the wrong technology table. The status is
therefore named for what is observed, and the counts are written both
ways.

One function, in the module that defines backup eligibility today,
returning a `Literal`:

```
backup_activity(cell_id, kpi) -> "active" | "inactive" | "no_data" | "not_queried"
```

| status | condition |
|---|---|
| `not_queried` | no successful KPI call named the cell |
| `active` | at least one row for the cell |
| `inactive` | successful calls named the cell over at least `INACTIVE_MIN_WEEKS` distinct baseline weeks, and over the outage interval when it was queried; the cell has no row in any of them; and at least one other cell of the same technology has rows in the same period |
| `no_data` | named and without rows, but a condition of `inactive` fails: fewer weeks, or no other cell of that technology returned rows, so the source cannot be told from the cell |

An `active` cell with rows missing for some hours keeps today's per-hour
`no_data` handling. `kpi` is the run's KPI state in a harness report and
the stored KPI rows in the reference and the evaluation; the function is
the same.

Use. A reachable backup counts toward a location's class unless its
status is `inactive`. `not_queried` and `no_data` backups count as they
do today. Every place that counts reachable backups calls the function;
list those places in the report. Every existing field keeps today's
meaning, coverage alone, and each gets a companion:

- the per-point record of `Evaluation_From_Stored_Data_2026-10-25.md`
  section 1: `backups[]` entries get `activity`; the record gets
  `n_backups_active` and `no_backup_active`;
- the reference classes (step 7 of the full-scan instruction): `class`
  stays, `class_active` is added, and the per-area and per-ring counts
  are written for both. Recompute from the stored files; no call;
- the harness final report: the class counts for both, and the list of
  inactive backups with the weeks checked;
- the tables of part 6: the two columns named there.

Not changed: the rendered context, the skill text, rule R3, the
completion check, the selectors, the concat packages. A run sends the
same queries with or without this part.

Check before trusting the status. Write
`<out>/<site>/inactive_backups.md` from the reference: per inactive
cell its id, technology, site prefix, the number of reference locations
that list it and the weeks checked; then the number of co-observed
backups, the inactive count and share, by technology and by site
prefix; then the number of locations whose `class_active` differs from
`class`. If the inactive cells share a technology or an id pattern, the
cause may be the routing of ids to tables, and the author decides
before the status is used in any result.

## 9. Tests, synthetic only

1. `RULE_SCORE=domain`: every existing rule-core test passes unchanged,
   and R1's proposals on every fixture equal the proposals before the
   change.
2. `p_samp`: a fixture with 30 queried and 6 sampled locations in one
   stratum gives 7/32; with 5 queried it falls back to the run-wide
   stratum; with none, 0.5.
3. `p_cov`: a stratum with observations uses them; an empty stratum
   uses the nearest band toward the site in the same bin; then the same
   band over all bins; then the run-wide rate; 0.5 only with no sampled
   location in the run.
4. `expected_cost` on a beyond item of 12 unread locations: `all` scores
   10/12 and is chosen over a sampled request whose `P_close` is 0.3.
5. `expected_cost` with `need` 10, on an item with at least 80 unread
   locations, picks `n` from 12 to 14 when `p_samp` is 0.9, from 23 to
   27 when it is 0.5, and from 60 to 68 when it is 0.2. The score is
   nearly flat around its maximum, so the test checks a range.
6. `budget_aware`: with the floor above `left`, the selection maximizes
   expected covered locations per location and `scarce_from_round` is
   set; with the floor below, it equals `expected_cost` when no
   candidate is removed.
7. Replay: a stored point returns its samples; a `no_sample` point an
   empty list; an `error` point raises the client exception; a location
   without a record, and a coordinate more than 1 m from a cell centre,
   raise `OutsideReference`; a coordinate outside the 30 km grid and
   inside the reference window is served; the per-site cache file is
   untouched.
8. Shifts: `W1` removes the same locations on two builds; `W2` leaves
   corridor locations unchanged; `W5` fails only the chosen area; `W6`
   empties exactly the locations within 2 km.
9. Free-form: a wedge with 10 sampled, uncovered locations beyond `F`
   closes at `eps` 0.26 and stays open at 0.10; a location with no
   sample does not count; a covered location beyond `F` resets the
   count.
10. Tables: two synthetic run directories give the columns of part 6;
    `best_rule` prefers a closed run over an open one with higher
    recall.
11. A replayed rule run whose only open item fails on every call ends
    `time_cap` at `RULE_REPLAY_SECONDS` (use a 2-second limit in the
    test).
12. `backup_activity`: hand-built KPI state gives each of the four
    statuses; with no other cell of the technology returning rows, a
    cell without rows is `no_data`, not `inactive`; with rows in 3 weeks
    queried and `INACTIVE_MIN_WEEKS` 4, the same.
13. A location whose only reachable backup is inactive has class
    `covered_backup` and `class_active` `covered_no_backup`.
14. With part 8 in place, the rule core's proposals and the rendered
    context are the same as before on every fixture.

Gate on the changed and new files: `uv run ruff format`,
`uv run ruff check --fix`, `uv run ty check`.

## 10. Order of work

1. Parts 1 to 3 and part 8 with their tests. The gate. Write
   `inactive_backups.md` and report it.
2. `--plan`. Stop if any location is missing or a launch seam is absent.
3. `--run rules`, `--run freeform`, `--tables`. Report.
4. Wait for the author's choice of worlds and repeats. Then
   `--run model`, `--tables`.

## 11. Report back

Change list as file and line, and the old and new `HARNESS_VERSION`.
Then `inactive_backups.md`, `plan.md`, `summary.md`, `calibration.md`,
`cost_recall.md`, `rounds.md` when it exists, and the answers to these
questions:

1. Where each runner takes its point client, and whether the replay
   callable went in without an edit to a harness package.
2. Whether the program's selectors return the location set of a template
   without executing it, and through which function.
3. Whether the state holds, per queried location, its sampled flag and
   its areas, or which file the estimates of part 2.1 read them from.
4. How many KPI calls the replayed runs made that were not in the cache.
5. Whether the harness grid can be built with a given origin, or is
   always centred on the site. This decides whether other sites inside
   the reference window can serve as further cases without new point
   calls.
6. Every place that counted reachable backups before part 8, as file
   and line, and how a failed point call is charged against the
   location budget today.
