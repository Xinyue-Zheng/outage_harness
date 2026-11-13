# Two literature selection scores for the rule core (instruction for the Copilot)

Apply to `outage_harness_rule_based` only. Synthetic fixtures and tests;
no real case, no reference, no comparison run. Report every change as
file and line.

This instruction adds two ways for rule R1 to choose its coverage
requests. Nothing else changes: not the completion check, not the legal
requests, not rules R2 to R4, not the rendered context, not any other
package.

Why. Rule R1 today takes the open items nearest first and sends a fixed
pattern with a fixed count. It never reads the sample rate, the cost or
the budget. The literature on this kind of problem gives two better
forms: choose the request with the most expected progress per unit of
cost, and take the remaining budget into account. Both are added as
selectable scores, so the current rule stays available unchanged and the
three can be compared later.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory.
- Do not run `uv sync` and do not add dependencies.
- The edit is one new file, `outage_harness_rule_based/scores.py`, and
  one dispatch in rule R1. With the default setting every proposal is
  the same as today.
- Bump `HARNESS_VERSION` by hand and record the old and new strings.
- Tests write only under `tmp_path`.

## 0. Setting and constants

`RULE_SCORE` is read once at run start, in the same place and by the
same mechanism as the current rule setting, and written to `run.json`
beside it.

| `RULE_SCORE` | source | what is taken from it |
|---|---|---|
| `domain` (default) | the current rule | nearest item first, fixed pattern and count; the current setting applies |
| `expected_cost` | adaptive greedy for minimum-cost cover (Golovin and Krause, JAIR 2011; Al-Thani, Cui and Nagarajan, Mathematics of Operations Research, arXiv 2208.08351) | each round, take the request with the largest expected progress toward closing everything, per unit of cost |
| `budget_aware` | cost-effective active search (Jiang, Garnett, Moseley, NeurIPS 2019) | the same, with the remaining budget in the decision: keep closure affordable while it is, and switch to finding covered locations when it is not |

With `expected_cost` or `budget_aware`, the score chooses the pattern
and the count, so the current rule setting is not used; `run.json`
records it as `not used`. The radius stays 10.

The earlier instructions say that the rule never reads the budget, the
sample rate or the cost, and never changes a count. Those statements
hold for `domain` and stay true for it. The two new scores read the
sample rate, and `budget_aware` reads the budget; that is their purpose.

Say in the module docstring how the papers' terms map and what is
replaced. In the minimum-cost cover papers an item is one thing to
select, it has a cost and a random outcome, a function `f` measures
progress, and the policy stops when `f` reaches its goal value. Here an
item is one valid request, its cost is its new locations, its outcome is
the samples it returns, `f` is the progress count of part 2, and the
goal is reached when the completion check passes. The greedy
rule is theirs: take the item with the largest expected increase of `f`
per unit of cost. Their bound needs two conditions that do not hold
here, so it does not carry over. The outcome probabilities must be
known, and here the two probabilities of part 1 are estimated from the
run's own queried locations. `f` must never decrease, and here a covered
location beyond the boundary adds new required locations.

Constants, at the top of `scores.py`:

| name | value | meaning |
|---|---|---|
| `MIN_OBS` | 20 | observations an area needs in a stratum before its own rate is used |
| `BAND_M` | 1000 | width of a distance band from the site |
| `N_MIN_SAMPLED`, `MAX_REQUESTS_PER_ACTION`, the coverage threshold | imported from the modules that define them | one definition |

## 1. Two estimates, from the run's own state only

Both are pure functions of the state and the geometry file. They use no
other run, no stored result of another case, no training.

- `p_samp(x)`, the probability that location `x` returns a sample. The
  stratum of `x` is one fact: whether `x` lies in any road corridor area
  or not. The estimate is `(1 + sampled) / (2 + queried)` over the
  queried locations of that stratum inside the area of the request being
  scored, when there are at least `MIN_OBS` of them; else over the
  stratum in the whole run; else, when the run has queried no location
  of the stratum, 0.5.
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

`p_cov` is used only by the scarce mode of part 3. It is not part of
the gain in part 2. A sampled request that finds coverage is not
wasted: the boundary moves and those locations would have been read as
interior locations anyway. Charging for it would also make every sampled
request score near zero in a band with no observation yet, and the rule
would fall back to reading whole areas.

## 2. `expected_cost`

This is the greedy rule of the minimum-cost cover papers, with nothing
added: take the request with the largest expected gain of `f` per unit
of cost.

The progress count `f`: the interior locations already read, plus, for
every beyond item, its locations that returned a sample, counted up to
the `N_MIN_SAMPLED` the item needs. A beyond item that is read in full
counts as `N_MIN_SAMPLED`. `f` is not stored; only the gain of a
candidate is computed.

Candidates: for every open coverage item (area, bin) of the completion
check, every template `legal_requests(area_id, bin_key, state)` returns.
For a template with a count range, the candidate is its smallest valid
count only. The expected gain per location of a sampled request cannot
rise with its count, so a larger count never scores higher; say so in
the docstring. For each candidate, get the location set `X` the
program's own selector would choose for it. If the selectors cannot
return the set without executing the query, stop and report.

Per candidate:

- `cost` = the new locations in `X`.
- `need` = `N_MIN_SAMPLED` minus the locations of that (area, bin) that
  already returned a sample, not below 0.
- `gain`: for an `inside` request, `cost`. For `all` on a beyond item,
  `need`. For a sampled request on a beyond item, the expected number of
  samples that count: `E[min(need, Binomial(|X|, mean p_samp over X))]`,
  computed exactly from the binomial terms.
- `score` = `gain / cost`.

Selection: sort candidates by score, highest first; ties by the area's
distance from the site, then area id. Take the best candidate of the
best item, then of the next item, up to `MAX_REQUESTS_PER_ACTION` items,
and send one action. The rejection rule of
`Copilot_Rejection_Handling_2026-10-31.md` part 3 is unchanged: a
rejected item is skipped for the round. This score does not read the
budget, so a request above the budget is rejected by the validator and
the rule takes the next item, as today.

What the score does. Interior reads score 1 and go first. Among beyond
items, the one with the highest sample rate goes first. Each request has
the smallest valid count, the rule sees how many samples came back, and
asks again while the item is open. A small area is read in full when
that costs less per counted sample. For an item that needs 10 samples,
the expected locations to close it are about 17 at a sample rate of 0.9,
24 at 0.5 and 55 at 0.2. The current rule, 20 at a time, needs about 20,
28 and 60.

## 3. `budget_aware`

Read `left` (locations left) and the floor's `locations` from the state.

- While the floor is at most `left`: use `expected_cost`, after removing
  every candidate whose cost exceeds `left` minus the floor cost of all
  other open items. If that removes every candidate, keep them all.
- When the floor exceeds `left`: closing everything is not affordable.
  Rank every candidate with `cost <= left` by expected covered locations
  per location, the sum over `X` of `p_samp(x) * p_cov(x)` divided by
  `cost`, and take the best ones as in part 2. `run.json` records the
  round of the switch as `scarce_from_round`. If no candidate fits, R1
  proposes nothing and the existing rules and guards apply.

## 4. Records

The step record of every R1 round under either new score holds, per
chosen candidate: the item, the request, `cost`, `need`, `gain`,
`score`, the mean `p_samp` and, in scarce mode, the mean `p_cov`. A
reader can recompute the choice from the step's `state_before` and these
values. The next step record of the same item already holds the samples
the request returned, so predicted and realized can be compared later
without a new field.

`run.json` gets `rule_score`, and `scarce_from_round` (null when the
switch did not happen). Nothing else is added.

## 5. Tests, synthetic only

1. `RULE_SCORE=domain`: every existing rule-core test passes unchanged,
   and R1's proposals on every fixture equal the proposals before the
   change.
2. `p_samp`: a fixture with 30 queried and 6 sampled locations of one
   stratum in the request's area gives 7/32; with 5 queried there it
   uses the run-wide stratum; with none in the run, 0.5.
3. `p_cov`: a stratum with observations uses them; an empty stratum
   uses the nearest band toward the site in the same bin; then the same
   band over all bins; then the run-wide rate; 0.5 only with no sampled
   location in the run.
4. `expected_cost` on a beyond item of 12 unread locations that needs
   10 samples: with `p_samp` 0.5, `all` scores 10/12, the sampled
   request of 10 scores 0.5, and `all` is chosen. With `p_samp` 0.9 the
   sampled request scores 0.9 and is chosen.
5. `expected_cost` on a beyond item with at least 80 unread locations:
   the request has the smallest valid count at `p_samp` 0.9, 0.5 and
   0.2. With 6 samples already in, `need` is 4 and the gain of a request
   of 10 at `p_samp` 0.5 equals `E[min(4, Binomial(10, 0.5))]`.
6. `expected_cost`: an inside item and a beyond item open together; the
   inside item is taken first. Two beyond items with `p_samp` 0.8 and
   0.3: the first is taken first.
7. `budget_aware`: with the floor below `left` and no candidate removed,
   the selection equals `expected_cost`; a candidate whose cost would
   leave the other items unaffordable is removed; with the floor above
   `left`, the selection maximizes expected covered locations per
   location and `scarce_from_round` is set; with no candidate that fits,
   R1 proposes nothing.
8. The step record of an R1 round under each new score holds the fields
   of part 4, and recomputing the score from them gives the recorded
   value.
9. A rejected candidate is not proposed again in the same round, under
   both new scores.

Gate on the changed and new files: `uv run ruff format`,
`uv run ruff check --fix`, `uv run ty check`.

## 6. Run it once, on the synthetic case

Run the rule core on the synthetic case of `synthetic_case.py` three
times, once per `RULE_SCORE`, with the limits the synthetic tests
already use. Do not run a real case.

## 7. Report back

Change list as file and line, and the old and new `HARNESS_VERSION`.
For each of the three synthetic runs: end reason, locations used,
rounds, and for the two new scores the counts `n` they asked for per
round. Then the answers to these questions:

1. Whether the program's selectors return the location set of a template
   without executing it, and through which function.
2. Whether the state holds, per queried location, its sampled flag, its
   areas and its bin, or which file the estimates of part 1 read them
   from.
3. Where the rule setting is read today, and where `RULE_SCORE` was
   added.
4. What the rule does today when a point call fails for every location
   of an item: whether the locations are charged, and whether the item
   is proposed again in the next round.
