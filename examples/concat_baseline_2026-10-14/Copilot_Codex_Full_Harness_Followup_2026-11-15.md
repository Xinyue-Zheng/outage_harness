# Codex harness package: three small changes (instruction for the Copilot)

Apply to `outage_harness_codex_full` only. Edit no other package. Make
no data call. Bump `CODEX_FULL_VERSION`.

## 1. The context window

Set `MODEL_CONTEXT_WINDOW_TOKENS = 131072` in `compaction.py`. The value
8192 was the output-token limit of the model client, not the context
window. Correct the sentence in the README.

## 2. No repeated compaction

If the request is still at or above the limit right after a compaction,
end the run with `end_reason: context_window`. Never compact twice
without a decision call between.

Why. The system message and the start message survive every
compaction. If those two alone are at or above the limit, a compaction
cannot help, and the loop would compact at every step and never reach a
decision.

## 3. Count with the tokens the endpoint reports

The trigger now uses this count for the next request:

- if the endpoint reported the prompt tokens of the last decision call
  (`usage.prompt_tokens`): that number, plus the approximate count
  (bytes divided by 4, rounded up) of every message appended since that
  call;
- else: the approximate count of the whole request, as today.

After a compaction, use the approximate count until the next decision
call reports a number.

Why. The approximation undercounts text with many cell IDs and numbers.
Some servers cut a request that is too long without an error, so the
"too long" rejection may never arrive. Codex itself uses the token
usage the server reports.

## 4. Tests, synthetic

1. A system message and a start message that together exceed the limit:
   one compaction, then the run ends `context_window`; no second
   compaction call is made.
2. A fake model that reports 110000 prompt tokens for a request whose
   approximate count is 60000: the next request, with 9000 approximate
   tokens appended, triggers a compaction.

Gate on the package: `uv run ruff format`, `uv run ruff check --fix`,
`uv run ty check`.

## 5. Report back

The change list as file and line. Whether the model client returns
`usage.prompt_tokens`, and under which name. The approximate token
count of the system message and of the start message on a real case,
without a model call.
