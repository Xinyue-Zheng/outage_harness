# Rule scores, follow-up: close the verification, and skip a request that returned nothing (instruction for the Copilot)

Apply to `outage_harness_rule_based` only. This follows your report on
`Copilot_Rule_Scores_2026-11-13.md`. It changes no scoring rule. It does
four things: it removes the failing tests, it adds one behaviour for a
request whose every point call fails (part 2), it runs the end-to-end
synthetic runs, and it records the gate. Report every change as file and
line.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory.
- Do not install anything. Do not run `uv sync`.
- Tests write only under `tmp_path`.
- No real case, no point API call, no KPI call.
- Part 2 changes what the rule proposes after a failed request. Bump
  `HARNESS_VERSION` by hand and record the old and new strings.

## 1. The seven failing tests

Four tests assert the earlier scoring (`P_close`, one large count per
item). That scoring is replaced, so those tests are wrong now.

- Delete the four. Do not keep them as skipped tests.
- Check that each of the nine tests of part 5 of the instruction exists.
  Add the ones that are missing. Your report says seven passed; say
  which two are absent or failing.
- For test 1 (`domain` unchanged), say what it compares against: the
  expected proposals the existing rule tests already hold, or something
  else.

Three tests fail on older APIs. Do not fix them here. For each one,
report:

- the test name and file;
- the first line of the error;
- the function it calls that is missing or has changed;
- whether its call path reaches `scores.py` or the dispatch in rule R1.

A test whose call path reaches neither is recorded as failing before
this change and left alone.

## 2. A request that returned nothing is not sent again

Why. Your report says that when every point call of a request fails,
nothing is charged, the locations stay unqueried and the item can be
proposed again. The rule is deterministic, so it sends the same request
in every round. Failed calls use no budget and the harness has no round
limit, so the run repeats until the time limit. The end reason then
hides the cause.

The rule already has the condition this needs. Part 3 of
`Copilot_Rejection_Handling_2026-10-31.md` says that a rejected item is
tried again only if the state record of that item changed. Apply the
same condition to an executed request. It holds for every `--rule-score`
value: `domain`, `expected_cost` and `budget_aware`.

- The rule keeps, in its own proposal history, the state record of each
  (area, bin) item at the moment it sent a request for it.
- In a later round, an open item whose state record equals the stored
  one is skipped: its last request was accepted and executed, and it
  read no location. The rule takes the next item in its order. Rules R2
  to R4 apply as today, with skipped items treated as not fetchable.
- When a location of the item is read by any request, the record changes
  and the item is proposed again as usual. A request that read some of
  its locations and failed on others changes the record, so it is not
  skipped.
- When every open coverage item is skipped or rejected and no R2, R3 or
  R4 action is legal, the run ends with
  `end_reason = "rule_request_failed"`. `run.json` stores every request
  that read nothing, with its round and the point client's error.
- The rule never changes the pattern, the count or the radius of an item
  to get past a failure. Nothing here applies to the model core.

The rule compares state records. It does not need a new state field. If
the comparison cannot be made from what the rule reads today (the state,
the completion check records, its own proposal history), stop and report
the file and line before you add anything.

Tests, with a fake point source that fails every call for the locations
of one area:

1. The rule sends the request for that area once. In the next round it
   takes the next item. The failed request is not charged, and
   `run.json` lists it.
2. With that area as the only open item, the run ends
   `rule_request_failed` after one attempt, not at the time limit.
3. With half of the calls failing, the item is proposed again in the
   next round.
4. A skipped item is proposed again after another request reads one of
   its locations.
5. Tests 1 and 2 pass under each of the three `--rule-score` values.
6. With no failing call, the proposals of `domain` on every existing
   fixture are the same as before this part.

## 3. End-to-end synthetic runs

The instruction named `synthetic_case.py`. That file is not in your
repository; the reference was wrong. Use the fixtures the completion
check tests already have:

- F1, the one-site fixture;
- F2, the two-site fixture of
  `Copilot_Completion_Check_v4_Per_Site_Bins_2026-10-31.md` part 14.

Run the rule runner from initialization to its end on each fixture, with
the fake point source and the limits those tests use, once per
`--rule-score` value: `domain`, `expected_cost`, `budget_aware`. That is
six runs.

Then one more run: `budget_aware` on F1 with the location limit set to
half of the floor's `locations` at step 0, rounded down. Closing
everything is then not affordable from the first round, so the scarce
mode must start.

If F1 and F2 are hand-built states and cannot drive a whole run, do not
write a new synthetic world. Report that, and name the entry point of
any existing test that runs the rule runner from start to end on
synthetic data.

## 4. The gate

`uv`, `ruff` and `ty` are not installed. Do not install them. Record
`gate: not run, tools not installed`. Run what the environment has:

- `python -m compileall` on the changed files;
- the test suite of the rule package.

Name any linter or type checker the environment already has. If there is
one, run it on the changed files and report its output.

## 5. Report back

1. The change list as file and line, and the old and new
   `HARNESS_VERSION`.
2. The nine tests of part 5 of the instruction and the six tests of
   part 2 here, one line each: test name, pass or fail.
3. The three older failures, as part 1 asks.
4. For each of the seven runs: end reason, locations used, rounds, the
   count each coverage request asked for per round, and
   `scarce_from_round`.
5. For the six runs of F1 and F2: whether `domain` and `expected_cost`
   close the same items, and the difference in locations used.
6. The gate line of part 4.
7. Where the rule stores the state record of an item when it sends a
   request, and where it compares it (file and line).
