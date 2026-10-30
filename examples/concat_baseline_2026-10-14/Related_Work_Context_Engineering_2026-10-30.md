# Context engineering: position, related work, baselines (discussion record, 2026-10-30)

Advisor's challenge: the rendered-state context is straightforward. Is
there related work, are there other methods, should we compare with them?

## Position

The rendering by itself is standard practice. What is defensible is the
combination, measured against a ground truth:

- every number in the context is computed by the program; the model never
  counts or remembers;
- the context is replaced each round, never appended, with the same blocks
  in the same order;
- the open items are derived from the same completion function that decides
  whether the run may end.

Frame it as agent-computer interface design for a data investigation task,
not as a new context method.

## Related work by family (verify every id before citing)

| family | what it does | representative work |
|---|---|---|
| Agent-computer interface design | the interface, not the model, decides agent performance; rendered views, concise tool outputs | SWE-agent, arXiv 2405.15793 |
| Program-rendered observations | the program renders the environment state to structured text every step | Voyager 2305.16291; web agents on accessibility trees, WebArena 2307.13854 |
| Transcript with compaction | append, then summarize past a length limit; the commercial default beyond Codex | ReSum 2509.13313; context folding 2510.11967; AgentFold 2510.24699; ACON 2510.00615; OpenHands condensers |
| Model-maintained state | the model writes its own state block each round; the program feeds it back | MemGPT 2310.08560; StateAct 2410.02810; MEM1 2506.15841 |
| Practitioner guidance | cache-stable prefix, keep errors in context, recite goals, mask rather than remove tools | Manus context-engineering post (2025); Anthropic "effective context engineering for AI agents" (2025) |
| Explicit control flow | program-side state machine decides what the model sees and may do | StateFlow 2403.11322 |
| Survey | taxonomy of context retrieval, processing, management | Mei et al. 2507.13334 |

Our design sits between program-rendered observations and explicit control
flow: Voyager-style rendering plus a program-owned test of "done".

## Baselines to add (context axis only; same validator, caps, checks)

1. Concat with compaction: the transcript is summarized by the model when
   it passes a length limit. The fair commercial baseline.
2. Model-maintained state: each round the model emits a state block
   (areas, counts, open directions); the program renders that block plus
   the last raw tool output. Same shape as ours, but the model counts.
   Tests whether the program-side computation is needed.
3. Rendered without open items: our harness with the completion-derived
   block removed. Isolates the part of the context that comes from the
   completion function.

Existing: plain concat (Codex style). The rule policy is the floor on the
decision-core axis, a separate axis.

## Claim that survives

On a long-horizon data investigation with a ground truth, program-computed
state and completion-derived open items let a mid-size model reach the
specification where appended transcripts do not, at a measured cost.
Whether model-maintained state is enough is answered by baseline 2.

## Open thread to pick up: completion-check blind spots (2026-10-29)

A rule run passed the completion check while the ground truth shows
covered areas, with coverage holes, that were never queried. Causes to
classify per area: resolved by sample on the near strip only; resolved by
extent with coverage reappearing farther out; only the nearest area beyond
the farthest covered point is tested; unobserved bins do not block; the
area is not an activity area or is outside reach. Candidate fixes: require
samples to cover the area (no unqueried location farther than a fixed
distance from a sampled one); test every area within reach beyond, not
only the nearest; make unobserved bins block. The check is a tunable proxy;
the curve to report is false-closure rate against points queried, for both
cores.
