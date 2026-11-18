# Greedy rule policy with a boundary-aware gain and a KPI candidate (instruction for the Copilot)

Build a new package, `outage_harness_greedy`, as a copy of
`outage_harness_rule_based_impact`, and change rule R1 in the copy. The
package `outage_harness_rule_based_impact` stays as it is, so that runs
of the earlier rule and of the new one can be compared.

Today R1 of `outage_harness_rule_based_impact` takes, among the valid
actions of the open items, the one with the highest value of
`p_samp * p_cov * mean exposure of the unread locations * expected severity`,
and keeps the earlier choice of pattern and count. In the copy, a
greedy score replaces that selection: the expected gain of a request
divided by its cost, over every valid request.

The new selection has four parts:

1. R1 ranks every valid request of every open coverage item by
   `gain / cost` and takes the highest. This is the `expected_cost`
   selection of `scores.py`. The impact value selects nothing any more.
2. The gain of a coverage request on an item beyond the boundary
   includes the case that the request finds the outage cell and the
   boundary moves.
3. A KPI request is a candidate in the same ranking, so that KPI is
   queried during the run and not only after coverage is closed.
4. The sample rate uses the direction bin when the area has too few
   reads.

Nothing else changes: not the completion check, not the valid request
list, not the selectors, not rules R2 to R4, not the validator. The
exposure that initialization stores with the geography stays.

## Rules

- Make the copy from the directory that holds the packages:

  ```
  cp -r outage_harness_rule_based_impact outage_harness_greedy
  cd outage_harness_greedy
  grep -rl "outage_harness_rule_based_impact" . | xargs sed -i 's/outage_harness_rule_based_impact/outage_harness_greedy/g'
  rm -rf __pycache__ */__pycache__ results runs
  ```

  Check: a search for `outage_harness_rule_based_impact` in the copy
  finds nothing, and the source package is byte for byte unchanged.
  The copy keeps its imports of other packages as they are.
- Edit only `outage_harness_greedy`. Do not edit
  `outage_harness_rule_based_impact`, `outage_harness_rule_based`,
  `outage_harness_langgraph_impact` or any other package.
- Reuse what the package has: `legal_requests`, the selectors that
  return the location set of a request, `p_samp`, `p_cov`, `need`, the
  function that rule R3 uses to build a KPI request, and the step
  record. Find them and call them. Do not write a second version of any
  of them.
- In the copy, remove the earlier selection by the impact value from
  R1, and its values from the step record. Do not keep it behind a
  setting.
- A run of another package may be in progress. Do not edit any file
  that a run reads per round: skill text, templates, configuration,
  `unit_costs.json`, any run directory.
- Do not run `uv sync`. Add no dependency. Do not use git.
- Tests are synthetic and write only under `tmp_path`. Make no point
  call and no KPI call.
- `GREEDY_VERSION` is a string at the top of `scores.py` of the copy,
  bumped by hand at every change of a rule below. Write it to
  `run.json` beside `rule_score`. Where the condition label of the
  copy ends in `+impact`, change the ending to `+greedy`.
- The source package has no test directory of its own. Put the tests
  of part 6 where the tests of the rule packages are, in a new file for
  `outage_harness_greedy`. Do not edit or delete an existing test: the
  existing tests check the source packages, which do not change.
- If `scores.py` of the copy has no `expected_cost` selection, or a
  function named above does not exist, or a part below cannot be done
  as written, stop and report. Do not work around it and do not put in
  a default.

This instruction can be applied without any earlier conversation. Read
these parts of `outage_harness_rule_based_impact` before you write
code. The copy holds the same files:

- `scores.py`: `p_samp`, `p_cov`, the scores `expected_cost` and
  `budget_aware`, and how a candidate gets its `cost`, `need`, `gain`
  and `score`;
- rule R1: where it computes the impact value, where it reads
  `RULE_SCORE`, and how it chooses the pattern and the count; rules R2
  to R4, and in R3 the function that builds a KPI request;
- `legal_requests` and the selectors that return the locations of a
  request;
- the completion check: its open coverage items, with their kind
  (inside or beyond), the boundary of a bin and the counts per (area,
  bin), and its open KPI items;
- the step record of an R1 round.

In the copy, the setting `RULE_SCORE` keeps its three values, and the
earlier order by the impact value is removed for all three:

- `domain` proposes what `outage_harness_rule_based` proposes with
  `domain`;
- `expected_cost` uses the gain of part 2;
- `budget_aware` uses the gain of part 2 while completion is
  affordable. Its second mode, which ranks by expected covered
  locations, is unchanged.

Parts 3 and 4 apply to `expected_cost` and `budget_aware`.

## 1. Terms

For one candidate request on an open coverage item (area, bin):

- `X`: the new locations that the selector returns for the request.
- `F`: the boundary of the bin, or none when no location of the bin
  shows an outage sector.
- `X_in`: the locations of `X` at or inside `F`. Empty when the bin has
  no boundary.
- `X_out`: the other locations of `X`, sorted by distance from the site
  of the bin, nearest first; ties by grid id. `m` is their count.
- For location `i` of `X_out`: `p_i` is `p_samp` and `q_i` is `p_cov`.
- Three outcomes of a location: `A`, it shows an outage sector, with
  probability `p_i * q_i`; `N`, it has a sample and shows no outage
  sector, with probability `p_i * (1 - q_i)`; `U`, no sample, with
  probability `1 - p_i`. Locations are treated as independent.

## 2. The gain of a coverage candidate

```
gain  = len(X_in) + gain_out
cost  = len(X)
score = gain / cost
```

Every location of `X_in` counts 1, with or without a sample, because
every location inside the boundary must be read.

`gain_out` depends on the request:

**`all`.** `gain_out` is the sum of `need` over the open beyond items
of this area, one per bin. `len(X_in)` is counted over all bins of the
area, each location against the boundary of its own bin.

**Every other pattern.** If `X_out` is empty, `gain_out` is 0.
Otherwise:

```
c_i = p_i * q_i
h_i = p_i * (1 - q_i) / (1 - c_i)

P(J = 0) = product over i = 1..m of (1 - c_i)
P(J = j) = c_j * product over i = j+1..m of (1 - c_i)        for j = 1..m

gain_out = sum over j = 0..m of  P(J = j) * ( j + E[ min(K_j, D_j) ] )
```

- `J` is the position of the farthest location of `X_out` with outcome
  `A`; `J = 0` when none has it. When `J = j >= 1`, the boundary moves
  to location `j`, and the locations 1 to `j` are then inside the
  boundary. That is the term `j`.
- `K_j` is the number of locations after position `j` with outcome `N`.
  Given that none of them is `A`, each one is `N` with probability
  `h_i`, independently. Compute the distribution of `K_j` exactly, as a
  sum of independent Bernoulli variables. Do not use a mean rate in
  place of the single `h_i`.
- `D_j` is what the item lacks under the new boundary.
  `D_0 = need` of the item. For `j >= 1`:
  `D_j = max(0, N_MIN_SAMPLED - known_j)`, where `known_j` is the
  number of already read locations of this (area, bin) that have a
  sample, show no outage sector, and lie farther from the site than
  location `j`. If the area has no location in this bin farther than
  location `j`, `D_j = 0`.
- If `X` holds locations of several bins, split `X_out` by bin, compute
  `gain_out` per bin and add.

When every `q_i` is 0, `gain_out` equals the earlier value
`E[min(need, K_0)]`.

Do not enumerate the `3^m` outcome combinations in `scores.py`. The sum
over `j` gives the same value.

The candidates are as before: every template that `legal_requests`
returns for an open coverage item, with the smallest valid count where
the template has a count, and radius 10.

## 3. The sample rate

`p_samp` of a location uses the locations of the same kind, in a road
corridor or not:

- the read locations of that kind in the area of the request, when
  there are at least `MIN_OBS`;
- else the read locations of that kind in the same site and direction
  bin, over all areas.

The estimate is `(1 + sampled) / (2 + read)` in both cases. With no
read location, it is 0.5 by the same formula. The earlier second step,
the whole run, is removed. `p_cov` is unchanged.

## 4. The KPI candidate

Pending cells are the cells that the open KPI items of the completion
check name, without the cells whose KPI query failed earlier in this
run.

- When there is at least one pending cell, and the KPI cell-queries
  left cover all pending cells, one KPI request for the pending cells
  is a candidate. Build it with the code that rule R3 uses. If R3
  builds its request inline, move that code, in the copy, into one
  function that takes the cells to name as a parameter. Call it from R3
  and from the KPI candidate. R3 must propose exactly what it proposes
  today. If R3 sends one technology per request, the candidate holds
  the pending cells of the first technology in the order of R3.
- Its gain is the number of cells named, its cost is the same number,
  and its score is 1.
- Selection: take the highest score over the coverage candidates and
  the KPI candidate. On a tie, the KPI candidate goes first, because it
  uses no location budget. A coverage score is at most 1, so the KPI
  candidate is proposed whenever it exists. One action holds one kind
  of request: the KPI request in this round, coverage in the next.
- When the KPI cell-queries left do not cover the pending cells, there
  is no KPI candidate, and R3 applies after coverage as before.
- A cell whose query failed is not named again by the candidate. It
  stays an open KPI item, and R3 handles it after coverage as before.

## 5. Records

The step record of an R1 round holds, per chosen coverage candidate,
the fields that `outage_harness_rule_based` records under
`expected_cost` (the item, the request, `cost`, `need`, `gain`, `score`
and the mean `p_samp`) and four more: `len_x_in`, `gain_out`,
`p_no_move` (the value `P(J = 0)`; null for `all` and for an empty
`X_out`) and the mean `p_cov` over `X_out`. For a KPI candidate it
holds the cells named and the score. Nothing else is added.

## 6. Tests, synthetic

1. `gain_out` equals the value from a direct enumeration of all `3^m`
   outcome combinations, written in the test only, for `m = 4`, unequal
   `p_i` and `q_i`, and three already read locations with a sample at
   different distances. Tolerance 1e-9.
2. With every `q_i = 0`, `gain_out` equals the gain that
   `outage_harness_rule_based/scores.py` gives for the same request.
3. Three locations, every `p_i = 0.5` and `q_i = 0.4`, `need = 2`, the
   eight counted locations all nearer than the three, and area
   locations farther than the third: `gain_out` is 1.753 to three
   decimals. The earlier value for the same request is 1.375.
4. `all` on an area with 30 unread locations inside the boundary and a
   beyond item with `need = 6`: the gain is 36.
5. `p_samp`: 30 reads of the kind in the area use the area; 5 reads in
   the area and 40 in the same site and bin use the bin; none gives
   0.5.
6. KPI candidate: with two pending cells and enough KPI budget, R1
   proposes the KPI request while an inside item is open. A cell that
   failed earlier is not named. With one KPI cell-query left and two
   pending cells, R1 proposes coverage. On an existing fixture, R3 of
   the copy proposes the same KPI request as R3 of the source package.
7. With `RULE_SCORE=domain`, the copy proposes the same requests as
   `outage_harness_rule_based` on the fixtures of the existing rule
   tests.

Gate on the copy: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 7. One synthetic run, as a check before the real cases

Run the copy from initialization to its end on fixture F1 of the
completion check tests, with `RULE_SCORE=expected_cost`, the fake point
source and the limits that those tests use. Write the run under
`tmp_path` or another folder outside every real run directory.

Then run the metrics command of part 8 on that run folder alone, to
confirm that it reads a run of the copy. If it stops, report the error
as it is. Do not edit `outage_harness_impact`.

Do not run a real case yourself.

## 8. Two commands for the real cases

The author runs the real cases. For each case of the author's message,
write one command line that the author can copy and run as it is. Do
not run it.

Each case names an earlier run of a rule package on that case, and an
output folder. Read the stored files of the earlier run, and only
those:

- the case: the down cell IDs and the outage interval;
- the three limits: locations, KPI cell-queries and seconds.

The command line of a case does two things, in this order, and the
second runs only if the first succeeds:

1. It starts a run of `outage_harness_greedy` on the same case, with
   the same three limits and `RULE_SCORE=expected_cost`. The run folder
   is `<output folder>/run`.
2. It writes and prints the metrics of the earlier run and the new run
   side by side, with the existing command:

   ```
   python -m outage_harness_impact.quick_table --out <output folder>/metrics rule_before=<earlier run folder> greedy=<output folder>/run
   ```

The table of that command has these columns per run: locations
queried, covered found, hit rate, no-backup found, located impact,
reportable impact, seconds and end reason. Do not add a column and do
not write a second metrics program.

If `<output folder>/run` already exists, the command must stop and not
overwrite it. Use the Python of the project environment, as the earlier
run did.

## 9. Report back

- The files of the copy that differ from the source package, as file
  and line, and the value of `GREEDY_VERSION`.
- The file that holds the new tests.
- The names of the existing functions that the new code calls.
- For the synthetic run: end reason, locations used, rounds, the round
  of each KPI request, and whether the metrics command read the run.
- The command line of each case, ready to copy, with the author's
  folders filled in. Under each one, the case and the limits that you
  read from the earlier run.
- Anything that could not be done as written. State it, and do not work
  around it.

## The author's message

```
Read Copilot_Greedy_Boundary_Aware_KPI_2026-11-18.md in full, then
apply it. Build outage_harness_greedy as a copy of
outage_harness_rule_based_impact, run the tests and the synthetic run,
and report as part 9 asks. Do not edit any other package. Do not run a
real case; give me the two command lines of part 8.

Case 1
  earlier run:   <run folder of an earlier rule run, case 1>
  output folder: <path 1>

Case 2
  earlier run:   <run folder of an earlier rule run, case 2>
  output folder: <path 2>
```
