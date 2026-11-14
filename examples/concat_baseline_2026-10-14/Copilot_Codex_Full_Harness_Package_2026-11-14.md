# A third transcript package: the Codex harness without the shell (instruction for the Copilot)

Build one new package, `outage_harness_codex_full`, as a copy of
`outage_harness_codex_state` with two additions taken from the Codex
CLI source: history compaction and the plan tool. Edit no existing
package.

Why. `outage_harness_codex_state` implements one part of the Codex
harness: the append-only transcript with long tool outputs cut. It is
used as an ablation of the harness (what the model reads). The new
package is a baseline: the orchestration of Codex, as far as it applies
to this task, run with the same model, the same tools, the same limits
and the same action format as the harness. A difference between its
results and the harness's results then comes from the orchestration and
from nothing else.

## Rules

- Do not edit `outage_harness_codex_state`, `outage_harness_concat_checked`
  or any harness package. The new package is a copy.
- Do not use git. Copy files and replace names as part 1 says.
- A run may be in progress. Do not edit any file a run reads per round
  outside the new package. Do not run `uv sync`. Add no dependency.
- Make no data call. Tests are synthetic and write only under `tmp_path`.
- Add a version string `CODEX_FULL_VERSION` at the top of the runner,
  bumped by hand, written to `run.json`.

## 0. What is taken from Codex, and what is left out

Put both tables in the docstring of the new module `compaction.py`.
Source: repository `openai/codex`, branch `main`, read on 2026-11-14.

| part | Codex source file | in the copied package | here |
|---|---|---|---|
| turn loop, ends when the model proposes no further action | `core/src/session/turn.rs` | yes | kept |
| instructions, tool list and start message in the request | `core/src/context/`, `agents_md.rs` | yes | kept |
| append-only history, long tool outputs cut at head and tail | `context_manager/history.rs`, `utils/output-truncation` | yes | kept |
| a tool error returned to the model as the tool output | `tools/` | yes | kept |
| compaction of the history at a token limit | `core/src/compact.rs`, `prompts/templates/compact/prompt.md`, `summary_prefix.md`, `protocol/src/openai_models.rs` | no | **added, part 2** |
| the plan tool `update_plan` | `core/src/tools/handlers/plan.rs`, `plan_spec.rs` | no | **added, part 3** |

| left out | reason |
|---|---|
| shell and file editing tools | decided by the author; the agent has the task's tools only |
| approvals, sandbox, reviewer model | the tools only read data |
| hooks | Codex ships with no hook configured; a run-end hook with the completion check is the package `outage_harness_concat_checked` |
| several tool calls in one model turn | every method in the comparison takes one action per step, as one JSON object |
| subagents, tool search, cross-session memory, interactive screen | five tools, one unattended run |

## 1. Copy the package

From the directory that holds the packages:

```
cp -r outage_harness_codex_state outage_harness_codex_full
cd outage_harness_codex_full
grep -rl "outage_harness_codex_state" . | xargs sed -i 's/outage_harness_codex_state/outage_harness_codex_full/g'
rm -rf __pycache__ */__pycache__ results runs
```

Set the condition label of the new package to `codex_full`, where the
copied package sets `concat`. Check: a search for
`outage_harness_codex_state` in the new package finds nothing.

## 2. Compaction (`compaction.py`, and the call in the runner)

Constants at the top of `compaction.py`:

| name | value | source |
|---|---|---|
| `AUTO_COMPACT_NUMERATOR`, `AUTO_COMPACT_DENOMINATOR` | 9, 10 | `auto_compact_token_limit`: `(context_window * 9) / 10` |
| `COMPACT_USER_MESSAGE_MAX_TOKENS` | 20000 | `compact.rs` |
| `BYTES_PER_TOKEN` | 4 | Codex's approximate token count |
| `EMPTY_SUMMARY` | `"(no summary available)"` | `compact.rs` |
| the context window of the model, in tokens | read from the package's model configuration | never typed here; if the configuration has no such value, stop and report |

`SUMMARIZATION_PROMPT`, word for word from Codex:

```
You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task.

Include:
- Current progress and key decisions made
- Important context, constraints, or user preferences
- What remains to be done (clear next steps)
- Any critical data, examples, or references needed to continue

Be concise, structured, and focused on helping the next LLM seamlessly continue the work.
```

`SUMMARY_PREFIX`, word for word from Codex:

```
Another language model started to solve this problem and produced a summary of its thinking process. You also have access to the state of the tools that were used by that language model. Use this to build on the work that has already been done and avoid duplicating work. Here is the summary produced by the other language model, use the information in this summary to assist with your own analysis:
```

The rule, as pure functions over the list of transcript messages:

1. **Count.** The token count of a text is its UTF-8 byte length
   divided by `BYTES_PER_TOKEN`, rounded up. The count of a request is
   the sum over its messages.
2. **Trigger.** Before each decision call, count the request that would
   be sent. If the count is at or above
   `context_window * 9 // 10`, compact first.
3. **The compaction call.** Send the same system message and the whole
   transcript, followed by one user message with `SUMMARIZATION_PROMPT`.
   Use the same model, endpoint and sampling settings as a decision
   call. The reply text is the summary. An empty reply gives
   `EMPTY_SUMMARY`.
4. **The new transcript**, in this order:
   - the start message of the transcript (the initialization message),
     cut at the end to `COMPACT_USER_MESSAGE_MAX_TOKENS` tokens if it is
     longer;
   - one user message: `SUMMARY_PREFIX`, a newline, the summary.

   Every model reply and every tool output before the compaction is
   dropped. The system message is unchanged. The run then continues and
   appends as before.
5. **A compaction call that does not fit.** If the endpoint rejects the
   compaction call because the request is too long, remove the oldest
   transcript message after the start message and send again. Repeat.
   If only the start message is left and the call still fails, end the
   run with `end_reason: context_window`.
6. **Accounting.** A compaction call is not a decision. Count it
   separately: `compactions`, its input and output tokens, its seconds.
   Its seconds count toward the time limit. It charges no location and
   no KPI cell-query.
7. **Record.** For each compaction write, in the step directory where
   it happened: the request sent, the summary, the transcript before
   and the transcript after.

The hidden State of the package, which is used for scoring only, is not
touched by compaction.

## 3. The plan tool

Add one action, `update_plan`, to the tool declarations that the model
reads and to the decision schema. Declaration, with the description
word for word from Codex:

```json
{"name": "update_plan",
 "description": "Updates the task plan.\nProvide an optional explanation and a list of plan items, each with a step and status.\nAt most one step can be in_progress at a time.",
 "parameters": {
   "explanation": "string, optional",
   "plan": "array, required; each item: {\"step\": string, \"status\": \"pending\" | \"in_progress\" | \"completed\"}"}}
```

- A valid call appends the tool output `Plan updated` to the transcript,
  as Codex does. The program does not print the plan back. The model
  finds its plan in its own earlier reply.
- An invalid call (a missing `plan`, an unknown status, an extra field
  in an item, more than one `in_progress`) appends an error string as
  the tool output, like every other tool error in this package.
- The call charges no location and no KPI cell-query. It is one step,
  and its seconds count toward the time limit.
- Write each accepted plan to the step record, so that the sequence of
  plans can be read after the run.
- Add one sentence after the tool declarations in the system message:
  "Use `update_plan` to keep a short plan of the investigation up to
  date." Add nothing else to the skill text.

## 4. Tests, synthetic, with a fake model

1. A request below the limit is sent unchanged; at the limit, one
   compaction call is made first, with `SUMMARIZATION_PROMPT` as the
   last message.
2. After a compaction the transcript has exactly two messages: the
   start message and the summary message that begins with
   `SUMMARY_PREFIX`. A start message longer than 20000 tokens is cut to
   that length. An empty summary becomes `EMPTY_SUMMARY`.
3. A fake model that rejects the first two compaction calls as too long
   receives a third call with the two oldest messages removed. With
   only the start message left and a rejection, the run ends
   `context_window`.
4. `update_plan`: a valid call gives `Plan updated`, charges nothing and
   is in the step record; two `in_progress` items give an error string;
   an unknown status gives an error string.
5. A scripted run of five steps with one compaction writes `run.json`
   with the condition `codex_full`, `CODEX_FULL_VERSION`, and
   `compactions: 1`, and the State after the run equals the State of
   the same script without compaction.

Gate on the new package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 5. Report back

The change list as file and line. The context window value used and
where it was read. Whether the endpoint returns a distinct error for a
request that is too long, and how the code recognizes it. Whether the
copied package already cut long tool outputs at head and tail, and with
which limits. Anything that could not be done as written; state it, do
not work around it silently.
