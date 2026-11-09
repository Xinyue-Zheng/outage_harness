# Amendment 3: Q1 is answered over all action kinds

Amends the gate amendment of 2026-11-08. Q2 and Q3 stay per action kind.
Q1 changes.

## Q1

Q1 asks whether the context of the round offered at least one legal,
affordable action of any kind. It is not restricted to the kind the core
proposed. Read every legality statement the context contains:

| statement | present when | affordable when |
|---|---|---|
| priced request lines of a bin | at least one coverage request is legal | a listed cost is not above the remaining locations |
| "expand_study_area may name one of: <keys>" | at least one direction is legal | always |
| the KPI cell set and KPI budget line | at least one cell may be queried | cell-queries remain |

Q1 is true when any present statement is affordable. Q1 is false when no
statement is present, or none is affordable. Record which statements were
present and which one made Q1 true.

An absent priced-request section is not a parse failure. It means no
coverage request was legal in that round, and the gate records
`coverage_requests_offered: false`. A parse failure is only a section that
is present and cannot be read; that still fails with the line.

## Round 29 of the episode

Kind coverage request, no priced section, expansion sentence present with
one key. Q1 true (expansion offered). Q2: `legal_requests` on the
pre-round state for the proposed request returns not legal, the recorded
verdict is rejected, so Q2 true. Q3 per the coverage row. Expected class
for rounds 28 to 30: `core_failure`.

## Then

Re-run part 9 of the first-trace instruction on the episode. The engineer
is called in test mode regardless of class. Paste the gate record for
rounds 28 to 30, the full engineer response, and the replay report (or its
"no patch" line). Name the one existing test that fails and what it tests.
For S0, list which of ruff, ty and the test runner are available in the
environment; a tool that is not installed is recorded as `not_available`
in the ledger entry, not run and not replaced.

## Test added

13. `gate` on a fixture round of kind coverage request whose context has no
    priced section but lists one expansion key gives Q1 true with
    `coverage_requests_offered: false`, and class `core_failure` when Q2
    and Q3 pass.
