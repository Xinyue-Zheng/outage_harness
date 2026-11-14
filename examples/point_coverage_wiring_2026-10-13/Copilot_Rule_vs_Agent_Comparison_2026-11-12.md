# Rule against agent: published selection rules adapted to the harness, and one comparison on shifted conditions (instruction for the Copilot)

> **On hold. Do not apply this file yet.** The reference it replays from
> is being regenerated. The two rule scores are no longer defined here:
> they are in `Copilot_Rule_Scores_2026-11-13.md`. The method without the
> harness is in `Copilot_Baseline_Algorithm_Only_2026-11-13.md`. Both
> are applied first and on their own. This file keeps the parts that
> wait for the reference: replay, the shifted conditions, the tables,
> and the inactive backup status. It will be
> revised when the reference is ready.

Apply to the repository that holds `outage_harness_langgraph`,
`outage_harness_rule_based` and `outage_harness_evolution`. This
instruction does three things, in this order:

1. It replays the method without the harness, which
   `Copilot_Baseline_Algorithm_Only_2026-11-13.md` adds earlier, and the
   two scores inside the rule core, which
   `Copilot_Rule_Scores_2026-11-13.md` adds earlier.
2. It adds one status for backup cells, `inactive`: a cell that coverage
   samples list and the KPI data has no row for (part 8).
3. It runs one comparison of every rule and the model core on the same
   case, replayed from the full-read reference of
   `Copilot_Reference_Full_Scan_2026-11-10.md`, under the stored
   conditions and under six shifted conditions.

The Copilot baseline of
`Copilot_Baseline_Copilot_MCP_One_Prompt_2026-11-13.md` is independent of
this instruction. It writes its own summary; a comparison with the
harness runs is a later step.

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
- The only harness edit of this file is the backup activity function
  with its call sites in the classification and report code (part 8).
  It does not change the rendered context, the skill text, the
  completion check or any query a run sends. Bump `HARNESS_VERSION` by
  hand, once, and record the old and new strings. The concat packages
  are not edited.
- Everything else is new modules in `outage_harness_evolution`:
  `replay.py`, `matrix.py`.
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
| `GAMMA`, `K_NEIGHBORS`, `BATCH` | as `outage_harness_active_search.policy` defines them | the method without the harness (part 3) |
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

The rule does not send again a request that read nothing
(`Copilot_Rule_Scores_Followup_2026-11-13.md` part 2): it takes the next
item, and the run ends `rule_request_failed` when nothing is left. A
replayed rule run finishes in seconds, so its time limit is
`RULE_REPLAY_SECONDS`. A rule run that still ends `time_cap` in replay
is shown as that in the tables; it is a result, not an error to repair.
Model runs keep the stored time limit.

## 2. Two literature scores inside the rule core

Defined in `Copilot_Rule_Scores_2026-11-13.md` and already applied
before this file: the setting `RULE_SCORE` with the values `domain`,
`expected_cost` and `budget_aware`, the two estimates `p_samp` and
`p_cov` (its part 1), and the step record fields (its part 4). Where
this file says "part 2.1", read part 1 of that file; where it says
"part 2.3", read its part 3. Nothing in this file changes the scores.

## 3. One literature method without the harness

Defined in `Copilot_Baseline_Algorithm_Only_2026-11-13.md` and already
applied before this file: the package `outage_harness_active_search`,
its probability model, its two policies (`ens` and `one_step`) and its
KPI step.
Nothing in this file changes the method.

In replay, `matrix.py` calls the loop function of that package's
`runner.py` with the replay callable of part 1 in place of the point
query, and with the activity locations of every complete reference ring
as the pool. The KPI step runs through the KPI client and cache,
unchanged. One run per policy: two runs per world.

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
| `FF` | active search without the harness, `ens` and `one_step` | no | 2 |
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
| `end_reason`, `closed` | from `run.json`; `closed` is true when the completion check passed; `not applicable` for `FF`, which has no completion rule |
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
request grouped by its predicted sample rate in five equal bins, with
the predicted gain and the samples that did come back and count, and the
mean predicted and realized sample rate per stratum. The binomial treats locations as
independent; samples cluster along roads, so this table shows how far
that assumption is off.

Then `cost_recall.md`: for each world, every harness run as a point
(`locations_used`, `recall_true`), and every `FF` run as one point per
round from its `rounds.json`, so each `FF` run forms a curve and the
harness runs are points beside it. Write the same data as
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

1. to 6. Moved with the scores to `Copilot_Rule_Scores_2026-11-13.md`.
7. Replay: a stored point returns its samples; a `no_sample` point an
   empty list; an `error` point raises the client exception; a location
   without a record, and a coordinate more than 1 m from a cell centre,
   raise `OutsideReference`; a coordinate outside the 30 km grid and
   inside the reference window is served; the per-site cache file is
   untouched.
8. Shifts: `W1` removes the same locations on two builds; `W2` leaves
   corridor locations unchanged; `W5` fails only the chosen area; `W6`
   empties exactly the locations within 2 km.
9. Moved with the method to
   `Copilot_Baseline_Algorithm_Only_2026-11-13.md`.
10. Tables: two synthetic run directories give the columns of part 6;
    `best_rule` prefers a closed run over an open one with higher
    recall.
11. A replayed rule run whose only open item fails on every call ends
    `rule_request_failed` after one attempt.
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

1. Parts 1 and 8 with their tests. The gate. Write
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
