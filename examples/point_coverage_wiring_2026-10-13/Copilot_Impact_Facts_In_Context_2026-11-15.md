# Impact facts in the context (instruction for the Copilot)

Apply after `Copilot_Impact_Score_and_Curve_2026-11-15.md`. This
instruction uses the package `outage_harness_impact` that the other one
builds.

One change to the harness: the context that the LLM reads gains the
facts it needs to judge where the impact is. The LLM then has to
estimate, from those facts, which open item is likely to hold the most
impact per location spent, and work on that one first.

Why. Today the context says what is open and what each action costs. It
says nothing about what a place is worth. The rule policy therefore
works outward by distance, and the LLM has no basis for doing better.
The completion check, the validator, the tools and the limits do not
change: they decide what must be read and when a run may end. The order
in which the open items are worked on is the policy's choice, and this
change gives that choice a basis.

## Rules

- The author confirms that no run is in progress before you start. This
  instruction edits files that a run reads.
- Edit only: the context renderer, the skill text and the step record
  of `outage_harness_langgraph`; initialization, to store the exposure;
  the run entry point, for one argument; and the rule package, for one
  policy option. Do not edit the validator, the completion check, the
  tools, the limits, the verifier or the transcript packages.
- Import `outage_harness_impact.impact`. Do not write a second
  definition of exposure or severity.
- Do not run `uv sync`. Add no dependency. Do not use git. Make no data
  call. Bump the version string of each package you edit.

## 1. One run argument

`--impact-facts on|off`, default `off`. With `off`, the context, the
skill text sent to the model and the rule's behaviour are exactly as
they are today. The value is written to `task.json` and `run.json`, and
the condition label gets the suffix `+impact` when it is `on`.

## 2. Exposure at initialization

With `--impact-facts on`, initialization computes the exposure counts
of every location with `exposure_table` and stores them with the static
geography of the run. Nothing else in the State changes.

## 3. The context

With `--impact-facts on`, the renderer adds two things.

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

## 4. The skill text

With `--impact-facts on`, this section is added to the skill text sent
to the model, after the section on choosing an action. The stored skill
file is not changed; the section lives in its own file in the package.

```
Impact
An outage matters most where service is lost and where there are people and places that need it. The context gives, for each open item, how many locations are unread, what the map shows in them, and what the locations already read there have shown.
Among the open items, work first on the one where you expect the most impact per location spent. Estimate it from the facts: how likely the unread locations are covered by an outage cell, how likely they have no good backup, and their exposure. A direction where coverage has just been found, with many buildings or a critical place in the unread part, is worth more than a direction where the last reads showed no coverage.
The completion rules still apply. Impact decides the order in which you work, not what must be read in the end. State your estimate in one sentence in the purpose of the decision.
```

## 5. The step record

For each decision with `--impact-facts on`, the step record keeps the
impact facts of every open item as shown, and which item the chosen
action belongs to.

## 6. The same basis for the rule policy

Add one policy option to the rule package, `impact`, so that a rule
with the same facts runs beside the LLM. Among the valid actions of the
open items it takes the one with the highest value of

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
selects. With the option unset, the rule behaves as it does today.

## 7. Tests, synthetic

1. On a fixture with two open items, the impact facts line of each
   equals the values counted by hand, and the block prints the
   constants of `impact.py`.
2. With `--impact-facts off`, the context of a fixture run is identical,
   byte for byte, to the context before this change.
3. The rule option `impact` selects the item computed by hand on a
   fixture where the nearest item has low exposure and a farther one
   has a critical place.
4. The step record holds the facts of every open item and the item
   chosen.

Gate on the changed packages: `uv run ruff format`,
`uv run ruff check --fix`, `uv run ty check`.

## 8. Report back

The change list as file and line. One rendered context from a fixture
with `--impact-facts on`. Which estimates of `p_samp` and `p_cov` the
rule option uses. Anything that could not be done as written; state it,
do not work around it silently.
