# Harness evolution: signals, gate, one engineer call, replay, on one trace

Apply to the repository that holds `outage_harness_langgraph` and
`outage_harness_rule_based`. Design reference:
`Harness_Evolution_Design_2026-11-08.md`, sections 3 to 9. This instruction
implements phase A and the smallest part of phase B, and runs them once on
one stored trace. No held-out reruns, no acceptance, no automatic edits of
the harness. Report every change as file and line.

## A run may be in progress

- Do not edit any file a run reads per round: skill text, templates,
  configuration, `unit_costs.json`, any run directory.
- Do not run `uv sync` and do not add dependencies. Use the model client
  the runner already uses.
- Put all new code in one new package, `outage_harness_evolution`, beside
  the two harness packages. It imports the harness packages read-only.
- The one edit to a harness package is part 1; it takes effect from the
  next run and does not change any per-round behaviour.
- Tests write only under a scratch directory given by an environment
  variable or `tmp_path`.
- The outer loop never writes into a run directory. All outputs go to
  `evolution/<run_name>/` beside the run directories.

## 1. Record the harness version

Add one module-level constant `HARNESS_VERSION: str` to the shared harness
package, for example `"2026-11-08a"`. At run start, both runners write it
into `run.json` as `harness_version`. The human changes the constant when
the harness changes; the outer loop only reads it. No git, no file hashes.

## 2. Signal extraction

`evolution signals <run_dir>` writes `evolution/<run_name>/signals.json`:
a list of signal records. Each record has `signal`, `rounds` (the rounds the
signal points at), and `evidence` (the `run.json` fields and values that
produced it). Implement these detections and no others:

| signal | detection |
|---|---|
| `rejection_cap` | `end_reason == "rejection_cap"`; rounds = the last `max_consecutive_rejections` entries of `rejections` |
| `rule_rejected` | `end_reason == "rule_rejected"`; rounds = the rejected round |
| `repeated_rejection` | two or more `rejections` entries with the same check in one run, not already covered by `rejection_cap`; rounds = those entries |
| `invariant_failed` | `end_reason == "completion_invariant_failed"`; rounds = the final round |
| `closure_leak` | `audit.json` exists and `found_rate > 0`; rounds = the final round; evidence includes `farthest_covered_past_edge_m` |
| `budget_before_complete` | `end_reason in {"query_budget", "kpi_budget"}` and `completion_checks` has an open item |
| `time_cap_program` | `end_reason == "time_cap"` and `resources.seconds.program > resources.seconds.decision` |
| `time_cap_decision` | `end_reason == "time_cap"` and not `time_cap_program` |
| `gap_mismatch` | a round whose decision `gap.targets` names an item that the rendered context of that round lists as closed, while the same context lists at least one open item; rounds = those rounds |

A run with none of these produces an empty list and the command says so.
If a field a detection needs is missing from `run.json`, the command fails
with the field name; it does not skip the detection silently.

## 3. Gate

`evolution gate <run_dir> <signal_index>` reads `signals.json`, and for each
round the signal points at answers Q1, Q2, Q3 from the stored
`context_NN.txt`, the stored decision and `state_NN.json`. It writes
`evolution/<run_name>/gate_<signal_index>.json`:

```json
{
  "signal": "rejection_cap",
  "rounds": [26, 27, 28],
  "per_round": [
    {"round": 28,
     "q1": {"answer": true,  "evidence": "context line(s) quoted; remaining budget from the budget line"},
     "q2": {"answer": true,  "evidence": "legal_requests(area, bin, state_28) result vs recorded verdict"},
     "q3": {"answer": true,  "evidence": "context statement quoted vs state_28 field and value"}}
  ],
  "class": "core_failure | interface_defect_q1 | interface_defect_q2 | interface_defect_q3",
  "class_rule": "first failing question over the rounds, in order q1, q2, q3; all pass means core_failure"
}
```

Procedures, all mechanical:

- **Q1**: parse the legal-actions section of `context_NN.txt` (the section
  the legal-actions-per-bin instruction defined, with one line per request
  and its cost) and the budget line (`locations_used/limit`). Q1 is true
  when at least one listed request has cost not above the remaining
  locations. If the section cannot be parsed, fail with the line that broke
  the parse. Do not fall back to a guess.
- **Q2**: take the proposed action of the round, call
  `legal_requests(area_id, bin_key, state_NN)` from the harness package, and
  compare its legality for that request with the verdict recorded in the
  round's validation record. Q2 is true when they agree.
- **Q3**: take the check that rejected the round (`rejections[].check`).
  For `budget`: compare the budget line in the context with
  `budget.locations_used` and `limit` in the state. For an open-direction or
  open-item check: compare the open items listed in the context with the
  open items in the state's completion record. For `kpi_cell_set`: compare
  the cell set the context names with the configured set in the state. Q3
  is true when the context matches the state. Any other check: write
  `"q3": {"answer": null, "evidence": "no procedure for check <name>"}`
  and treat it as passing for the class rule, with a note in the record.

## 4. Packet

`evolution packet <run_dir> <signal_index>` writes
`evolution/<run_name>/packet_<signal_index>/` with exactly the files listed
in the design, section 7.1: `signal.json` (signal record plus gate record),
`rounds/` with `context_NN.txt`, `decision_NN.json`, `validation_NN.json`
and `state_NN.summary.json` (only the state fields the gate read) for each
pointed round and the round before the first, `component/` with the source
file of the component the class points at (`legal_requests` module for q2,
the validator module for q3, the renderer module for q1; for `core_failure`
the renderer module, so that the engineer can still cite it),
`ledger_tail.md` (last 10 ledger entries, or the sentence "ledger empty"),
and `constraints.md` with the text of design sections 6 and 7.2 and this
sentence first: "If class is core_failure, the correct output has
`patched_file: null` and `component: null` and explains why no harness edit
is warranted." The output schema in `constraints.md` replaces the design's
`patch` field with `patched_file: {"path": "<file on the edit surface>",
"content": "<full new content of that one file>"}`, so that no patch tool
is needed.

## 5. One engineer call

`evolution engineer <packet_dir> --model <name> --reasoning-effort
<low|medium|high>` sends one request with the runner's model client:
system text = `constraints.md`; user text = the other packet files in the
order signal, rounds (oldest first), component, ledger tail. It parses the
reply as the JSON object of design section 7.2 and writes
`engineer_response.json` beside the packet. Parsing is strict: a reply
without `predicted_effect`, or with a `patched_file` when `class_agreement`
is `agree` and class is `core_failure`, is saved as `engineer_response_invalid.txt`
with the parse error, and the command exits non-zero. Record `model`,
`reasoning_effort`, token usage and `total_s` in the response file.

For this first test, the engineer is called regardless of class. The
response file gets `"test_mode": "engineer_called_despite_class"`. In the
later loop, `core_failure` episodes do not reach the engineer.

The engineer model for now is the in-loop model. Record that in the ledger
entry (`engineer_model_is_inloop_model: true`), because it changes what
the test shows: it tests the pipeline, not a stronger reader.

## 6. S0 and S1 on the engineer's patched file

`evolution replay <run_dir> <packet_dir>`:

1. If `engineer_response.json` has `patched_file: null`, write
   `replay_report.md` with the single line "no patch; replay not run" and
   exit zero.
2. Copy the harness package to a scratch directory and write the
   engineer's `patched_file` content over the named file there. A
   `patched_file.path` outside the edit surface of design section 6 fails
   S0 with the file name.
3. Run `uv run ruff format --check`, `uv run ruff check`, `uv run ty check`
   and the harness tests against the copy. Any failure is S0 fail; write
   the tool output to `s0_report.txt`.
4. S1: for every stored run whose `harness_version` equals this run's (or,
   when the field is absent, the runs the user names on the command line
   with `--replay-runs <dir> ...`; say which rule was used), and
   for every round NN of it, using the patched copy: re-render the context
   from `state_NN.json` and diff against `context_NN.txt`; re-validate the
   stored decision and compare with the stored verdict; re-compute the
   legal action list for the decision's (area, bin) and compare. Write
   `replay_report.md` with three tables: changed contexts (run, round,
   section), changed verdicts (run, round, was, now), changed legal lists
   (run, round, diff). Then state whether `predicted_effect` holds: the
   named signal's rounds show the promised change, and no verdict flipped
   from accepted to rejected outside `predicted_effect.unchanged`.

The replay never calls the model and never writes into a run directory.

## 7. Ledger

`evolution/ledger.jsonl` in the repository root of the outer-loop outputs,
one line per episode with the fields of design section 8.5, `S2` and
`observed_effect` set to `null` with the note "not run in this instruction".
`evolution run-one <run_dir> --signal <index> --model <name>
--reasoning-effort <level>` runs parts 2 to 6 in order and appends the
ledger line.

## 8. Tests

Fixtures are synthetic run directories built in `tmp_path`; no real run
directory is read by a test.

1. `signals`: a fixture with `end_reason: rejection_cap` and three
   `rejections` entries yields one `rejection_cap` record with those three
   rounds and no `repeated_rejection` record.
2. `signals`: a fixture missing `rejections` fails with the field name.
3. `gate` Q1 false: a fixture round whose legal-actions section lists only
   requests costing more than the remaining budget gives
   `interface_defect_q1`.
4. `gate` Q2 false: a fixture round where `legal_requests` on the stored
   state marks the proposed request legal and the recorded verdict is
   rejected gives `interface_defect_q2`.
5. `gate` all pass: a fixture round with an affordable legal request, an
   agreeing verdict and a context whose open items match the state gives
   `core_failure`.
6. `packet`: the packet directory contains exactly the files of part 4 and
   `constraints.md` starts with the core-failure sentence.
7. `engineer` parsing: a reply without `predicted_effect` produces
   `engineer_response_invalid.txt` and a non-zero exit; a valid reply is
   written with the usage fields.
8. `replay`: a patched renderer file that changes one section produces a
   changed-contexts table with exactly that section for every fixture round
   and empty changed-verdicts and changed-legal-lists tables.
9. `replay` S0: a `patched_file.path` that names the rule policy module
   fails S0 and names the file.

## 9. Run it once

Run `evolution run-one` on the most recent stored run that ended with
`rejection_cap` on the current harness (the run where the only open
direction was 3 and the core proposed direction 2 at step 28), with the
in-loop model and `--reasoning-effort medium`. Paste into the report:
`signals.json`, the gate record with the quoted evidence for each question,
`engineer_response.json` in full, `replay_report.md`, and the ledger line.

Then run `evolution signals` and `evolution gate` only (no engineer call)
on the two completed runs of the 1-site case and on the two time-capped
runs of the 4-site case, and paste the signal lists and classes. These
show what the extraction finds on runs that did not fail at the interface.

## 10. Report

File and line for every change. For part 3, say which context section
format the parser assumes and quote one parsed line. For part 6, say which
rule selected the replay runs. For part 9, give the numbers and the full
engineer response. List anything in the design that the stored records
could not support, with the record field that was missing.
