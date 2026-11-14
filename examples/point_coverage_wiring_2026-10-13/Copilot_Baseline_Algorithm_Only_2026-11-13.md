# Baseline: a published search algorithm as the whole method, coverage and KPI, end to end (instruction for the Copilot)

Apply to the repository that holds `outage_harness_langgraph` and
`outage_harness_rule_based`. This adds one baseline: a program that
chooses every query with a published search policy, efficient nonmyopic
active search (ENS), with no language model and no harness. It has no
areas as actions, no valid action list, no completion check, no rendered
context and no rule policy. It reads locations until the location limit
is used, then queries KPI, then writes the same end outputs as a harness
run. It runs on the same case, the same data sources, the same caches
and the same three limits as a stored harness run.

Why. Every baseline so far runs inside the harness and inherits its
completion rule. This one answers the other question: does a published
search algorithm, with nothing around it, already solve the task. It
needs no reference, because it runs against the point API through the
caches, as a harness run does.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory, any file in the
  harness packages or the concat packages.
- Do not run `uv sync` and do not add dependencies. Use only what the
  environment already has.
- New code goes into a new package `outage_harness_active_search/` with
  two modules, `policy.py` and `runner.py`, and a `tests/` directory.
  The comparison module is `outage_harness_copilot/compare.py`, built by
  `Copilot_Baseline_Copilot_MCP_One_Prompt_2026-11-13.md`, which is
  applied first. Do not write a second one. It imports the harness
  packages read-only. If a harness
  function cannot be called without the harness state, stop and report
  which one. Do not copy harness code.
- Tests write only under `tmp_path`.
- Outputs go to `<results root>/active_search/<case>_<YYYY-MM-DD>_<policy>/`.
- Point and KPI calls go through the caches the harness uses
  (`point_cache.jsonl` keyed `grid_id|radius_m|epoch`, the KPI cache). A
  cached item is served from the cache; an uncached item is fetched live
  and written to the cache, as a harness run does.
- Do not start a real run while another run is using the point API.
- The package has a version string `ACTIVE_SEARCH_VERSION`, bumped by
  hand, written to `run.json`.

Run as

```
python -m outage_harness_active_search.runner --harness-run <run dir of a harness run on this case> --out <results root>/active_search [--policy ens|one_step] [--dry-run]
python -m outage_harness_copilot.compare <active search run dir> <harness run dir> [<harness run dir> ...]
```

Every number written comes from a tool result or from a file an earlier
step wrote. An absent value is `not recorded`.

## 0. Sources and constants

Put this table in the docstring of `policy.py`.

| part | source | what is taken | what is changed |
|---|---|---|---|
| which location to read next | Jiang, Malkomes, Converse, Shofner, Moseley, Garnett. Efficient nonmyopic active search. ICML 2017 | the ENS score, equation (7), and the pruning bound, equation (8) | a third outcome is added to the expectation: the location returns no sample (part 3) |
| the probability that a location is a positive | Garnett, Krishnamurthy, Xiong, Schneider, Mann. Bayesian optimal active search and surveying. ICML 2012, section 7 | the k-nearest-neighbour model, equation (7) there, with pseudocount 0.1 | neighbours are the nearest pool locations by ground distance |
| several locations per round | Jiang, Malkomes, Abbott, Moseley, Garnett. Efficient nonmyopic batch active search. NeurIPS 2018 | sequential simulation with the pessimistic oracle | none |
| the comparison policy | the same papers | the one-step policy: read the location with the highest probability | none |
| which KPI cells when the limit is short | Khuller, Moss, Naor. The budgeted maximum coverage problem. Information Processing Letters 1999 | take the cell with the largest marginal gain | none; the costs are equal |

The papers have no stopping rule: the policy spends the budget it is
given. This baseline does the same. The authors' reference code is in
MATLAB (`github.com/rmgarnett/active_learning`); it is not used here.

Constants, at the top of `policy.py`:

| name | value | meaning |
|---|---|---|
| `GAMMA` | 0.1 | pseudocount of the probability model, the papers' value |
| `K_NEIGHBORS` | 24 | neighbours of a location: its 24 nearest pool locations |
| `BATCH` | 50 | locations read per round |
| `MIN_OBS` | 20 | reads a stratum needs before its own sample rate is used |
| `SELECT_SECONDS_MAX` | 120 | if choosing one batch takes longer, stop and report |
| limits | read from `--harness-run` | `max_query_locations`, `max_kpi_cell_queries`, `max_time_seconds` from `run.json.limits`; never retyped |
| the case | read from `--harness-run` | the ticket: down cells, outage interval, supplied prefixes |
| the coverage threshold, the load limit, the signal margin, the frame half-width, the query radius 10 | imported from the harness modules that define them | one definition |

## 1. The pool

Active search works on a fixed pool. The pool is every activity location
inside the harness frame (the square the harness can expand to), around
every site of the case.

- Sites: every configured down cell maps to one site with coordinates,
  through the lookup the harness uses. A cell without a site or a site
  without coordinates is a named error.
- Build the activity areas and their 100 m locations for the whole frame
  with the harness's own builder and its half-width argument. Map data
  comes from the harness's stored copy when it covers the frame, else
  from the harness's own fetch path; count the calls.
- Per location, compute once: grid id, centre, distance to the nearest
  site, `corridor` (true when the location lies in any road corridor
  area), and its `K_NEIGHBORS` nearest pool locations. Also store the
  reverse lists: for each location, the locations that have it as a
  neighbour. Area ids are kept for the report only. The selection never
  reads them.
- Write `pool.json`: the count of locations, by corridor flag and by
  site.

## 2. The probability model

A read location has one of three results:

| result | meaning | label |
|---|---|---|
| `covered` | a sample lists a down cell at or above the threshold | 1 |
| `not_covered` | it returned samples and none does | 0 |
| `no_sample` or `error` | nothing to judge | none; the location is used up and is in no neighbour count |

- `p(x)`, the probability that `x` is covered. With `L(x)` the
  neighbours of `x` that have a label:
  `p(x) = (GAMMA + number of L(x) with label 1) / (1 + size of L(x))`.
- `s(x)`, the probability that `x` returns a sample:
  `(1 + sampled) / (2 + read)` over the reads with the same `corridor`
  flag, among the neighbours of `x` and their neighbours when that gives
  at least `MIN_OBS` reads, else in the whole run. With no read of that
  flag, 0.5.

Both are pure functions of the read records.

## 3. The policy

`t` is the number of locations left before this pick. `top(m, P)` is the
sum of the `m` largest values in `P`, over unread locations.

One-step score: `s(x) * p(x)`.

ENS score, the paper's equation (7) with the no-sample outcome added:

```
ens(x) = s(x) * [ p(x) * (1 + top(t-1, P after x gets label 1))
                + (1 - p(x)) * top(t-1, P after x gets label 0) ]
       + (1 - s(x)) * top(t-1, P unchanged, without x)
```

Only the locations that have `x` as a neighbour change their
probability, so compute each `top` from the sorted current probabilities
and the few changed values, without sorting again. Prune with the
paper's bound (8): a location whose current `p` is below the bound
cannot have the best score. Locations with the same `p`, the same `s`
and the same multiset of affected probabilities have the same score;
compute it once.

A round:

1. Choose `BATCH` locations, or as many as are left, by sequential
   simulation: take the location with the highest score; pretend it
   returned label 0; update; repeat. Ties: nearer to its nearest site
   first, then grid id. After the batch is chosen, discard the pretended
   labels.
2. Read the batch through the same point fetch helper the harness uses,
   at radius 10, with its own retries. Charge one location per grid id
   not charged before in this run, cached or live. A location whose call
   still fails is recorded as `error`, is not charged, as in the
   harness, and is not read again in this run.
3. Record the results and repeat.

Reading ends when no location is left in the limit (`query_budget`),
when the pool is read in full (`pool_read`), or when the time limit is
reached (`time_cap`). Start the clock where the harness starts its own,
and say in the report where that is.

With no read yet, every location has `p = GAMMA`, so the first batch is
decided by the ties: nearest to a site first. That is the start the
papers use: one known point and a prior.

If choosing one batch takes more than `SELECT_SECONDS_MAX`, stop and
report the pool size, the count of locations left after pruning, and the
seconds. Do not shrink the pool or the neighbour count to make it fit.

## 4. KPI

The KPI step comes once, after reading stops. The reason belongs in the
docstring: a KPI result does not change which location to read, the set
of backup cells is final only when reading stops, and a cell named in
two calls is charged twice. After `query_budget` or `pool_read` the step
runs. After `time_cap` it does not, and `run.json` says
`kpi: not queried`.

- Required cells: the outage sectors, and every eligible backup cell
  (the harness's eligibility function) listed in the same sample as an
  outage sector at or above the threshold at any read location.
- Window: the outage interval moved back 1 to 8 whole weeks, from the
  harness function that computes those windows. One call per technology,
  from the start of the earliest window to the end of the latest, as
  rule R3 of the rule policy sends it.
- When the required cells fit in the cell-queries left: name them all.
- When they do not: take the outage sectors first. Then repeat: take the
  backup cell with the most covered locations at which it is a reachable
  backup and no cell taken so far is; ties by cell id. Stop at the
  limit. Record the cells left out. The run's `end_reason` is then
  `kpi_budget`.
- A call that fails after the client's own retries, or returns no rows,
  is recorded and not sent again.

## 5. End outputs and records

Classes and the load estimate come from the harness's own end-of-run
functions (classification per location, redistribution, report), called
on this run's samples and KPI rows. If they read a harness State, build
it through the harness's own constructors and list in the report which
fields they read. If that is not possible, stop and report.

Files in the run directory:

| file | content |
|---|---|
| `pool.json` | part 1 |
| `reads.jsonl` | one line per charged location, in order: index, round, grid id, centre, `p`, `s`, score, result, `cached`, seconds |
| `samples.jsonl` | every sample returned, keyed by grid id |
| `rounds.json` | per round: batch size, locations left, covered found so far, the highest and lowest score in the batch, the count of locations left after pruning, selection seconds |
| `kpi.json` | required cells, cells named in order, cells left out, per call the rows, the query id and the seconds |
| the report files | as a harness run writes them |
| `run.json` | `end_reason`, `limits`, `policy`, pool size, `ACTIVE_SEARCH_VERSION`, and `resources`: locations charged (cached, live, no sample, error), covered locations found, KPI calls, cell-queries and rows, map calls, and seconds split into `setup`, `selection`, `coverage`, `kpi`, `total` |

The loop in `runner.py` is one function that takes the point query and
the KPI query as parameters, with the signatures the harness passes to
`make_point_query` and to its KPI tools. Nothing in `policy.py` does
I/O.

## 6. Comparison

`outage_harness_copilot.compare <active search run dir> <harness run dir> [...]`
writes `<active search run dir>/compare/`. It reads `run.json`, the read
records and the samples of each run and nothing else, so that every
baseline that writes the same files uses it unchanged. The three outputs
below are defined here; the module itself is built with the Copilot
baseline.

1. `resources.md`: one column per run. Rows: locations charged, of
   which no sample, covered locations found, KPI cell-queries, rounds,
   decision calls, input and output tokens (0 here and for a rule run),
   seconds total, seconds in the point API, end reason.
2. `order.md`: covered locations found after each tenth of the location
   limit, one column per run. Then, for each harness run: the number of
   locations this run had read when it had found as many covered
   locations as that harness run found in total, or `not reached`.
   `order.geojson` per run: every charged grid id as a point with
   `order`, `covered` and `class`.
3. `classes.md`: every grid id each run read, classified by the same
   function from the stored samples and KPI rows. Per class: the count
   in each run. Then, for each pair of runs: grid ids read by both and
   the agreement on them; covered locations that one run found and the
   other never read, both directions.

No reference is used. No pictures.

## 7. Tests, synthetic only

1. `p`: no labelled neighbour gives 0.1; one positive gives 0.55; one
   positive and one negative give 1.1/3; a neighbour with `no_sample`
   changes nothing.
2. `s`: 30 reads and 6 sampled of one flag near `x` give 7/32; with 5
   reads there the run-wide value is used; with none, 0.5.
3. ENS on a hand-built pool of six locations with `t = 2`: the score of
   every location equals the value computed by hand from the formula of
   part 3, and with `s = 1` everywhere it equals the paper's equation
   (7).
4. With `t = 1`, ENS and one-step choose the same location.
5. A fixture where one-step and ENS differ: a location with a slightly
   lower `p` and many unread neighbours is chosen by ENS when `t` is
   large and not when `t` is 1.
6. Pruning: on a pool of 2000 random locations, the choice with pruning
   equals the choice without it, for ten random read histories.
7. Sequential simulation: the pretended labels are discarded after the
   batch is chosen; a batch never holds a location twice; a batch is cut
   at the locations left.
8. Charging: a grid id is charged once; cached and live are both
   charged; an `error` location is not charged and is not chosen again.
9. `query_budget` still runs the KPI step; `time_cap` does not.
10. KPI under the limit: one call per technology names every required
    cell once. Over the limit, with backup A at 5 covered locations, B
    at 4 of the same 5, C at 2 others: the order is the outage sectors,
    A, C, B, and the run ends `kpi_budget` with the cells left out
    recorded.
11. End to end on fixture F1 of the completion check tests, with its
    fake point source, both policies: every file of part 5 exists, every read location has a
    class, and a second run gives the same `reads.jsonl` apart from the
    seconds.
12. The comparison module on that run and a synthetic harness run
    directory writes the three outputs and no `claims.md`.

Gate on the new package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 8. Run it

1. `--dry-run`: fixture F1 of the completion check tests, a location
   limit of 300, a time limit of 600 seconds, both policies. Read `run.json` and
   `rounds.json`, the selection seconds first.
2. One real run with `--policy ens` on the case that has a stored model
   run and a stored rule run, with `--harness-run` set to the model run.
3. The comparison module with both stored runs.
4. Stop and report. The author decides whether to run
   `--policy one_step`. That run is charged in full and reads partly
   from the cache.

## 9. Report back

Change list as file and line. Then `pool.json`, `run.json`, `kpi.json`,
the three comparison files, and the answers to these questions:

1. Which harness function built the frame-wide pool, how long it took,
   and how many map calls it made.
2. How many pool locations are in the geometry of the stored harness
   run, and how many are not.
3. The selection seconds per round, the share of locations pruned, and
   whether any numeric library was already available and used.
4. Where the harness starts the clock of its time limit, and where this
   runner starts its own.
5. Which harness functions produced the classes and the load estimate,
   and which State fields they needed.
