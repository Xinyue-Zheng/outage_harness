# Transcript baselines: what differs from the current harness (instruction for the Copilot)

Read-only. Compare the two transcript packages,
`outage_harness_codex_state` (concat) and `outage_harness_concat_checked`,
with the current harness package `outage_harness_langgraph`, and report
the differences. Edit nothing. The author decides from the report what
to update, and a second instruction then makes the changes.

Why. The transcript packages were copied from the harness in October.
They were meant to differ from it only in what the model reads and in
who ends the run. The harness has changed a lot since then, so the
packages now also differ in parts that were meant to be the same code.
A comparison between them and the harness is only meaningful when those
shared parts are equal again.

## Rules

- Change no file in any package. Create no file in a package.
- Make no data call and start no run. Run no tests.
- Do not use git. Compare the files directly: read them, or use a plain
  file comparison if the environment has one.
- Keep the report short. Give tables and one line per difference. Do
  not paste code.

## 1. The file inventory

Compare the three packages file by file, by relative path. One table:

| file | harness | concat | concat_checked | status |
|---|---|---|---|---|

`status` is one of: `same in all three`, `differs`, `only in harness`,
`only in the transcript packages`. Leave out `__pycache__`, results and
run directories. For a file that is the same in all three, give only
the count of such files, not a row each.

## 2. The differences, classified

For every file with status `differs` or `only in ...`, one row per
difference, at the level of a function, a constant or a text block:

| file | function or constant | harness now | transcript packages now | class |
|---|---|---|---|---|

The class is one of three.

**A. By design.** The difference defines the baseline and must stay:

- what the model reads: the transcript of replies and raw tool outputs,
  against the text rendered from the State;
- the skill text variant of the transcript packages;
- validation by schema only; a rejection returned as a tool output;
- no verifier call and no gap checks;
- the ending: concat accepts the model's finish; concat_checked refuses
  it until the completion check passes;
- the initialization message at the start of the transcript;
- the package name and the condition label.

**B. Shared part that is out of date.** The code was meant to be the
same in all three packages, and the harness has a newer version. Look
at these parts in particular:

- how the outage cells are identified (exact down cell IDs or a prefix
  match), and the backup eligibility;
- the tools and their declarations: names, parameters, descriptions,
  the coverage query parameters (pattern, count, direction, radius);
- the point coverage path, the caches, retries and resume;
- initialization: the sites, the map, the areas, the grid, the ring
  probe;
- the State update after a tool result;
- the budget accounting and the limits that can end a run;
- the completion check file and its version;
- the expansion of the study area;
- the KPI path: the cell set, the windows, the handling of a failed
  call and of an empty result;
- the end of a run: classes per location, the load estimate, the
  report;
- the run directory layout and the fields of `run.json`;
- constants and configuration values.

**C. Harness only.** The harness added it, and it has no place in a
transcript baseline: a block of the rendered context, the valid action
list as text, the recovery option, the rule policy, the evolution
hooks.

If a difference fits no class, mark it `unclear` and say why in one
line.

## 3. Eight questions, answered per package

One table, columns harness, concat, concat_checked:

1. Which version of the completion check does the package run, and does
   it work per down site and per direction?
2. Which limits can end a run (locations, KPI cell-queries, seconds,
   tool calls, rounds, rejections), and with which default values?
3. Are the outage cells exact IDs or a prefix match?
4. Which radius values does the coverage tool offer?
5. Does initialization read the ring probe?
6. What does the package store for a KPI call that failed, and can a
   later step read it as "no rows"?
7. Does the package use the shared point cache, and can a run resume?
8. Which fields does `run.json` have that the others lack?

## 4. The two transcript packages against each other

They were meant to differ only in the ending. List every other
difference between them, one line each, or state that there is none.

## 5. What an update would take

For each row of class B, say which of these applies:

- `copy`: the harness file can replace the transcript package's file as
  it is, because the transcript package made no edit of its own in it;
- `merge`: the transcript package has its own class A edits in that
  file, so the harness changes must be added by hand; name the
  functions;
- `depends`: the change needs another class B row first; name it.

Then give the shortest order in which the class B rows can be applied,
as a numbered list of file names. Do not apply it.

## 6. Report back

Parts 1 to 5 as written above, in that order. Then anything in the
transcript packages that is broken today regardless of the harness: an
import that fails, a tool the client does not declare, a file that is
referenced and missing. One line each.
