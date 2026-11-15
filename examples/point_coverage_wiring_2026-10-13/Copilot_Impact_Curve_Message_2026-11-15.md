# Message for the Copilot: run the impact score and curve on three cases

Paste the text in the box into a new chat, together with
`Copilot_Impact_Score_and_Curve_2026-11-15.md`. Fill in the paths first.

```
Apply the attached instruction. Give me the exact command for each
case below, ready to copy. Then run them and show me impact_summary.md
of each case.

Case 1: <case name>
Runs to draw: <package A run folder>, <package B run folder>, <package C run folder>
Output folder: <output root>/<case 1>

Case 2: <case name>
Runs to draw: <package A run folder>, <package B run folder>, <package C run folder>
Output folder: <output root>/<case 2>

Case 3: <case name>
Runs to draw: <package A run folder>, <package B run folder>, <package C run folder>
Output folder: <output root>/<case 3>
```

To get the commands without Copilot running them, replace the last
sentence of the first paragraph with "Print the commands only."

## Optional lines, under a case

- `Reference: <reference folder>` when the reference of that case is
  complete. The curves then show the share of the total impact. Without
  it they show absolute values.
- `Geometry for the Copilot run: <a harness run folder of that case>`
  when one of the runs of that case is a Copilot baseline run. Runs of
  the harness, the rule package or a transcript package need no
  geometry line.

## Conditions

- The runs of one case are on the same case: the same down cell IDs and
  the same outage interval.
- Each output folder is new and lies outside the run folders.
