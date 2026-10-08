# Context method comparison: State rendering versus append-only transcript

Written for: whoever runs or extends the context experiment.

The harness has two ways to build what the deciding model reads. The first is
the project's design: the program renders the structured State into text every
round. The second is the method Codex CLI and similar coding agents use: an
append-only transcript of the model's replies and the raw tool outputs,
truncated and compacted when long. Everything else is the same code: the
registry, parser, validation, verifier, execution, State update, Step files,
caps and completion checks. The two methods differ only in two nodes of the
loop, `render_context` and `llm_call`.

## What code is in which file

Files that existed before this comparison were not changed.

| File | Status | What it does |
| --- | --- | --- |
| `src/outage_poc/context.py` | unchanged | The State rendering: `render_context(state, registry, config, history)` returns a `Rendered` with a stable prefix and a variable part. |
| `src/outage_poc/loop.py` | unchanged | The loop with the State rendering. Its `execute`, `apply_observation`, `record_step`, `finish_run`, `prepare_run_dir`, `resolve_data_version`, `RunEnv` and `LoopState` are reused by the transcript loop. |
| `src/outage_poc/model.py` | unchanged | `ChatEndpoint`, `chat(endpoint, system, user)`, `ChatModel`, `ScriptedModel`, `read_script`. |
| `src/outage_poc/run.py` | unchanged | The command line for the State rendering method. |
| `src/outage_poc/transcript.py` | new | The transcript data and rules: `Message`, `Transcript` (system, opener, summary, rounds), `append`, `tool_output` (raw rows or program errors as the next user message), `truncate_middle` (byte cap, middle removed), `maybe_compact` (model summary of older rounds past a token threshold), `TranscriptConfig`, the `Summarizer` protocol. |
| `src/outage_poc/transcript_model.py` | new | `chat_messages(endpoint, messages)`: one chat completion over a message list. `TranscriptChatModel` (live), `ScriptedTranscriptModel` (replay), `ChatSummarizer` (compaction by the model), `HeadSummarizer` (deterministic compaction for scripted runs). |
| `src/outage_poc/transcript_loop.py` | new | The loop with the transcript method. Same twelve nodes and edges as `loop.py`; `render_context` builds the transcript and `llm_call` sends its messages. `run(...)` is the entry point. |
| `src/outage_poc/run_transcript.py` | new | The command line for the transcript method, and the argument helpers `compare_contexts.py` shares. |
| `src/outage_poc/compare_contexts.py` | new | Runs the same case under both methods into two folders and writes `comparison.md`. |
| `tests/test_transcript.py` | new | Nine tests, listed below. |

## How the pieces connect

```
compare_contexts.main
  ├─ loop.run(config, task, ChatModel | ScriptedModel, ChatVerifier, LocalClient, <out>/state_context)
  │     render_context_node ── context.render_context(State) ── Rendered(prefix, variable)
  │     llm_call ──────────── model.propose(Rendered) ── chat(system=prefix, user=variable)
  │     parse → validate_action → verifier → execute_query → update_state → write_step → loop_guards
  │
  └─ transcript_loop.run(config, TranscriptConfig, task, TranscriptChatModel | ScriptedTranscriptModel,
                         ChatSummarizer | HeadSummarizer, ChatVerifier, LocalClient, <out>/transcript_context)
        render_context_node ── transcript.append(last round's reply, tool_output(...))
        │                      transcript.maybe_compact(...) ── Summarizer.summarize(older rounds)
        │                      Transcript.messages() ── [system, user opener(+summary), assistant, user, ...]
        llm_call ──────────── model.propose_from(messages) ── chat_messages(endpoint, messages)
        parse → validate_action → verifier → execute_query → update_state → write_step → loop_guards
                                  (reused from loop.py: execute, apply_observation, record_step, finish_run)
```

The verifier reads the State rendering in both methods. It is part of the
harness, not of the deciding model's input, so it stays the same to keep the
comparison to one variable.

## What the model reads in each method

State rendering (`inputs/round_NN.txt` in `state_context/`):

```
<prefix: skill, task, geography, relations, areas, actions, completion rules>

Investigation progress: ... per-area counts ...
Key areas with unqueried locations: ...
Coverage observations: ... D0 present at k of n ... query boundary ...
Impact and backup analysis: ...
Remaining unknowns: ...
Actions allowed now ... Query budget: ...
Evidence provenance: ...
Feedback from the last two rounds: ...
```

Transcript (`inputs/round_NN.txt` in `transcript_context/`, and the exact
messages in `transcript/round_NN.json`):

```
[system]    <the same prefix>
[user]      task opener (+ "Summary of rounds 1 to k" after a compaction)
[assistant] action: coverage.query / parameters: {...} / gap: {...}      round 1
[user]      coverage.query returned (observation obs_01, status ok, 12 ms):
            member S1: ok
            result_status partial_missing
            36 coverage rows
            {"grid_id":"G_r10_c08","status":"valid","cells":[...],...}
            ... [... N of M bytes omitted ...] ...
[assistant] ...                                                           round 2
[user]      error: decision rejected (bad_parameter): ...                 (an error is the tool output)
[user]      finish refused; unmet completion rules: - ...                 (a refused finish)
            reviewer concern (advisory; may be wrong): ...                (a verifier concern)
```

Rules of the transcript method, taken from Codex CLI:

- Only grows at the end. Nothing earlier is edited.
- Tool output is raw rows, cut to `output_cap_bytes` (default 10,000) with the
  middle removed and a note of how many bytes were omitted.
- Errors, refusals and reviewer concerns are returned as the tool output text,
  not as computed facts.
- When the estimated size (characters divided by four) exceeds
  `compact_threshold_tokens` (default 20,000), the rounds older than the last
  `keep_recent_rounds` (default 3) are summarized by a model call and the summary
  replaces them in the opener. Each compaction is recorded under `compactions/`.
- No State is rendered for the deciding model. The State still exists and is
  written after every step, so both folders have `states/` and `contexts/`.

## How to run

Scripted (no model is called: the decisions come from a file, the verifier agrees
with every decision and compaction uses a deterministic head summary, so both
methods produce the same States and the comparison shows only the input difference):

```bash
uv run python -m outage_poc.compare_contexts --output outputs/compare_scripted \
    --base-url http://127.0.0.1:8012/v1 --model x --verifier-model x \
    --script tests/scripts/complete.txt --query-budget 2400
```

Live (both model nodes on an endpoint; the decisions differ between methods):

```bash
uv run python -m outage_poc.compare_contexts --output outputs/compare_live_1600 --maps \
    --base-url http://127.0.0.1:8012/v1 --model qwen2.5-32b-instruct-awq \
    --verifier-model qwen2.5-32b-instruct-awq --query-budget 1600 --step-cap 30
# condition B for the state method: add --recent-steps 3
# transcript settings: --output-cap-bytes, --compact-threshold-tokens, --keep-recent-rounds
```

Transcript method alone: `uv run python -m outage_poc.run_transcript ...` with
the same arguments. The State method alone: `uv run python -m outage_poc ...`.

## What each output folder holds

```
<out>/comparison.md                 end reason, rounds, rejections, queried locations,
                                    input tokens per round, compactions; one step table per method
<out>/state_context/                the State rendering run
<out>/transcript_context/           the transcript run
  inputs/round_NN.txt               exactly what the deciding model read that round
  outputs/round_NN.txt              its reply
  steps/step_NN.json                the Step: decision, validation, review, observation,
                                    State before and after, counters (the checkpoint)
  states/state_00.json              State 0; later States are inside the Step files
  contexts/prefix.txt, state_NN.txt the State rendering after each step (both methods)
  observations/obs_NN_<member>.json the rows each tool call returned
  trace.json, run.json              the ordered Steps and the run record
  transcript/round_NN.json          (transcript only) the messages as sent
  transcript/final.json, summary.txt(transcript only) the final transcript, its size, compactions
  compactions/before_round_NN.txt   (transcript only) what was summarized and the summary
  maps/, index.html                 with --maps: the maps and a page for people
```

## Tests (`tests/test_transcript.py`)

| Test | What it checks |
| --- | --- |
| messages alternate and only grow at the end | system, user, then assistant/user pairs; appending keeps earlier messages identical; an out-of-order round raises |
| truncation keeps head and tail | the byte cap removes the middle and reports the omitted bytes |
| compaction replaces older rounds | past the threshold the older rounds become one summary in the opener; the last `keep_recent_rounds` stay verbatim; below the threshold nothing changes |
| tool output reports errors, refusals and concerns | each kind appears as text; a round with nothing to report raises |
| estimate is characters over four | |
| complete script gives identical States and observations | the `complete.txt` decisions under both methods: same States after every step, same observation files, both end `complete`; the inputs differ (raw rows and a growing chat in one, a State rendering in the other) |
| faults reach the model as errors | `faults.txt`: parse failures and rejections appear as `error:` lines in the transcript |
| compaction runs in a long run and is recorded | with a low threshold the recorded run compacts; the compaction files and the final transcript carry the summary |
| observation text is truncated to the byte cap | the 192-location corridor result shows the omission note |

Run them with `uv run python -m unittest discover -s tests -p "test_transcript.py"`.
The full suite (81 tests, 1 skipped without an endpoint) passes with the new files.

## Results so far (one live run per setting, 2026-10-08)

Qwen2.5-32B-Instruct-AWQ for both model nodes, temperature 0, step cap 30,
boundary share 0, condition A for the State method. Folders:
`outputs/compare_live_1600/` and `outputs/compare_live_2400/`.

| Budget | Method | End | Rounds | Rejections | Queried | Input tokens, max / total |
| --- | --- | --- | --- | --- | --- | --- |
| 1,600 | state_context | query_budget | 6 | 1 | 1,526 | 6,397 / 35,602 |
| 1,600 | transcript_context | query_budget | 8 | 4 | 1,575 | 14,229 / 68,425 |
| 2,400 | state_context | repeated_query | 6 | 0 | 2,126 | 6,579 / 35,718 |
| 2,400 | transcript_context | complete | 13 | 4 | 2,400 | 19,027 / 157,169 |

What the runs show, and what they do not:

- Input size: the State rendering stays between 4.9k and 6.6k tokens per round
  in every run; the transcript grows every round and reaches 19k tokens by round
  13. Over a run the transcript costs 2 to 4 times the input tokens. No
  compaction fired (threshold 20k), so the transcript method ran uncompacted.
- Rejections: 4 per run with the transcript against 0 or 1 with the State
  rendering. The transcript's first decision in both runs was `cell.lookup`, an
  initialization action, because nothing in the transcript says initialization
  already ran; the State rendering names the phase and the allowed actions. The
  other rejections were gap-versus-State contradictions and a malformed
  drill-down parameter, facts the State rendering states and the transcript
  leaves to the model to infer from raw rows.
- Outcome at 1,600: both end `query_budget`. The State method spent 1,526
  locations in 4 queries and then proposed a finish naming the unaffordable
  areas; the transcript method spent 1,575 in 5 queries, one of them a re-query
  of an area it had already queried (round 7, F3, 0 new locations).
- Outcome at 2,400: the transcript method completed in 13 rounds by querying
  every area, then KPI, then impact. The State method ended on the
  repeated-query guard: it proposed the same query in rounds 5 and 6 after a
  verifier concern on round 5. In condition A the model does not see its own
  previous decision, only the concern about it; condition B (recent steps in the
  context) exists for this case and was not run here. The earlier run G with the
  same settings completed, so this outcome is within run-to-run variation.
- These are single runs. Repeat each setting, and run condition B, before
  comparing end reasons; the token and rejection differences are stable across
  the two budgets, the end reasons are not.

## What the live comparison measures

Per method, from `comparison.md`: the typed end reason, rounds, rejections,
queried locations, and the estimated input tokens per round. The research
question is whether the State rendering changes the model's decisions, not
only the input size. Both methods run the same harness with the same caps, so a
difference in end reason or in queried area is attributable to what the model
read. One live run per method is a single sample; repeat with the same settings
before drawing a conclusion.
