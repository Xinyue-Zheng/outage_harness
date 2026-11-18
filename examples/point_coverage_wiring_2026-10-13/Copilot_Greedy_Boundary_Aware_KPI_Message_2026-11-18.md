# Reply to the Copilot after it stopped on the greedy rule policy

Send this in the same chat. It answers the two points of the Copilot's
report: rule R3 builds its KPI request inline, and the source package
has no test directory of its own.

```
Two answers, then continue with the instruction.

1. You may add one function. In outage_harness_greedy/rule_policy.py,
   move the code with which R3 builds its KPI request into one function
   that takes the cells to name as a parameter. Call it from R3 and
   from the KPI candidate of part 4. R3 must propose exactly what it
   proposes today: add one test that compares R3 of the copy with R3 of
   the source package on an existing fixture. Do not change
   rule_policy.py of any other package.

2. No test is deleted. Put the tests of part 6 where the tests of the
   rule packages are, in a new file for outage_harness_greedy. Do not
   edit or delete an existing test.
```

The current version of
`Copilot_Greedy_Boundary_Aware_KPI_2026-11-18.md` already holds both
points. If you replace the instruction in the workspace with the
current version, the message above is still correct.
