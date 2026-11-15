# Impact facts in the context, as two new packages (instruction for the Copilot)

Apply after `Copilot_Impact_Score_and_Curve_2026-11-15.md`. This
instruction uses the package `outage_harness_impact` that the other one
builds.

Build two new packages as copies, and change only the copies:

| new package | copy of | change |
|---|---|---|
| `outage_harness_langgraph_impact` | `outage_harness_langgraph` | the context that the LLM reads gains the facts it needs to judge where the impact is |
| `outage_harness_rule_based_impact` | `outage_harness_rule_based` | the rule orders the open items by the same facts |

The two original packages are not edited, so that runs of the old and
the new packages can be compared.

Why. Today the context says what is open and what each action costs. It
says nothing about what a place is worth. The rule policy therefore
works outward by distance, and the LLM has no basis for doing better.
With the facts, the LLM has to estimate which open item is likely to
hold the most impact per location spent, and work on that one first.
The completion check, the validator, the tools and the limits are the
same code as in the originals: they decide what must be read and when a
run may end. The order in which the open items are worked on is the
policy's choice, and this change gives that choice a basis.

## Rules

- Edit no existing package. Change only the two copies.
- In the copies, change only what parts 2 to 6 name. Do not change the
  validator, the completion check, the tools, the limits or the
  verifier.
- Import `outage_harness_impact.impact`. Do not write a second
  definition of exposure or severity.
- Do not run `uv sync`. Add no dependency. Do not use git. Make no data
  call.
- Each copy gets a version string `IMPACT_PACKAGE_VERSION` at the top
  of its runner, bumped by hand, written to `run.json`.

## 1. Copy the two packages

From the directory that holds the packages, for each pair of the table:

```
cp -r <original> <new>
cd <new>
grep -rl "<original>" . | xargs sed -i 's/<original>/<new>/g'
rm -rf __pycache__ */__pycache__ results runs
```

Do `outage_harness_langgraph_impact` first. If the rule package imports
the harness package for shared parts, the rule copy imports the harness
copy. Add the suffix `+impact` to the condition label of each copy.
Check: a search for the original name in a copy finds nothing, and the
originals are byte for byte unchanged.

## 2. Exposure at initialization

Initialization of each copy computes the exposure counts of every
location with `exposure_table` and stores them with the static
geography of the run. Nothing else in the State changes.

## 3. The context (harness copy)

The renderer adds two things.

**One block, once, above the open items:**

```
Impact
The impact of a location is its severity times its exposure.
Severity: covered with no backup 1.0; covered and every backup has a problem 0.5; covered with a good backup 0.1; not covered or no sample 0.
Exposure: 1 per building, 10 per critical place, 3 per other place, 2 to 5 for a major road.
Impact found so far: 31.5 with equal weight, 212 with exposure, in 640 locations.
```

The numbers of the second and third line are printed from the constants
of `impact.py`. The last line is computed from the State.

**One line under each open item, after its existing lines:**

```
Impact facts: 140 unread locations; in them 62 buildings, 1 critical place (hospital), 3 other places, primary road on 20 locations; exposure 95. Read here so far: 30 sampled, 12 covered, 4 of those with no backup.
```

- "Unread locations" and their exposure counts cover the locations of
  that open item that the run has not been charged for.
- A critical place is printed with its kind from the map tag.
- "Read here so far" covers the locations of the same area and
  direction that the run has read.
- An item with no unread location gets no line.

The program prints these facts and nothing more. It does not print an
expected impact, a ranking of the items, or a recommended item. The
estimate is the model's task.

## 4. The skill text (harness copy)

Add this section to the skill text of the copy, after the section on
choosing an action:

```
Impact
An outage matters most where service is lost and where there are people and places that need it. The context gives, for each open item, how many locations are unread, what the map shows in them, and what the locations already read there have shown.
Among the open items, work first on the one where you expect the most impact per location spent. Estimate it from the facts: how likely the unread locations are covered by an outage cell, how likely they have no good backup, and their exposure. A direction where coverage has just been found, with many buildings or a critical place in the unread part, is worth more than a direction where the last reads showed no coverage.
The completion rules still apply. Impact decides the order in which you work, not what must be read in the end. State your estimate in one sentence in the purpose of the decision.
```

## 5. The step record (harness copy)

For each decision, the step record keeps the impact facts of every open
item as shown, and which item the chosen action belongs to.

## 6. The rule (rule copy)

Among the valid actions of the open items, the rule of the copy takes
the one with the highest value of

```
p_samp * p_cov * mean exposure of the unread locations * expected severity
```

- `p_samp` and `p_cov` are the package's existing estimates for that
  item. If the package has none, stop and report; do not write new
  ones.
- Expected severity is the mean severity of the covered locations the
  run has read so far, and 0.5 before any.
- Ties go to the item nearest to the down site.

The rule keeps its existing choice of pattern and count for the item it
selects. Its step record keeps the value of every open item and the
item chosen.

## 7. Tests, synthetic

1. On a fixture with two open items, the impact facts line of each
   equals the values counted by hand, and the block prints the
   constants of `impact.py`.
2. The rule copy selects the item computed by hand on a fixture where
   the nearest item has low exposure and a farther one has a critical
   place.
3. The step records of both copies hold the facts or values of every
   open item and the item chosen.
4. On the same fixture and the same scripted decisions, the State after
   each step of the harness copy equals the State of the original
   package, apart from the stored exposure.

Gate on the two copies: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 8. Report back

The change list as file and line. One rendered context from a fixture.
Which estimates of `p_samp` and `p_cov` the rule copy uses. Whether the
rule package imports the harness package, and what the copy imports
now. Anything that could not be done as written; state it, do not work
around it silently.
