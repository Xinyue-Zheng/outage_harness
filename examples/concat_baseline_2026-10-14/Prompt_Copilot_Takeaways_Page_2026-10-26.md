# Prompt for the Copilot: a "Takeaways and next steps" page

Add one page, "Takeaways and next steps", as the last navigation entry of
the presentation system, same single-file rules as the other pages, and
also saved on its own as `takeaways.html` (it holds no coverage pictures,
so it can be shared). Three tables, each with one sentence under it, the
text below typed in verbatim. Use the existing table style; cells wrap.

## 1. What the three conditions did

| condition | what happened in the runs | consequence in the report |
|---|---|---|
| Codex-style state (concat) | calls finish early, often before every area is queried and before the KPI window is fetched | areas missing from the report; backup load unknown; classes rest on signal only |
| Concat with completion check | runs to completion because the program refuses the early finish | many more rounds; repeated invalid actions, such as queries for areas that do not exist, each caught by the validator |
| Rendered state | completes within the cap with valid actions | all areas and the KPI window in the report |

Under it: "The completion check decides whether the investigation
finishes; the state organization decides how many rounds and how many
invalid actions it takes to get there. Not shown here: whether the
finished report is right; that is what the ground truth pages are for."

## 2. What evolves and what stays fixed

Two columns. Left, "Stays fixed": model weights, validator code,
completion check code, classification rule. Right, "Evolves, each with its
own score":

| object | representation | driven by |
|---|---|---|
| Playbook (by reflection) | scoped text items: terrain, technology, phase | rejections, wasted rounds, areas left open, verifier flags |
| Case memory (by reflection) | per-case records: terrain, outage set, areas that mattered, backups that carried load | the scored run of each case |
| Fitted tools (by fitting) | redistribution parameters; KPI window rule; direction-bin constants | observed KPI against estimates |
| Guarantee table (by fitting) | thresholds, required checks, blocking open items, probe radii | extent misses and early stops from the truth; rounds and rejections from the traces |
| Verifier checklist (by reflection) | the checks applied before a stop is accepted | cases where validator and model passed and the truth disagreed |

Under it: "The model stays frozen and the code stays fixed; what evolves
is the advice, the memory, the fitted tools, the guarantee parameters,
and the verifier's checks, each scored by the ground truth."

## 3. Next steps

| step | what is done | what it produces |
|---|---|---|
| 1. Refine the ground truth | recompute the per-point record from stored samples and observed KPI; impact truth at the agent's own points; the scan kept for extent only; next cases scanned over the areas plus one band | a truth reproducible from stored data, dense where the agent looked, cheaper for new cases |
| 2. Score the existing runs | the area-level scorer and per-area figures on the three cases; no new calls | area recall, degraded and congested shares, class distance, cost, per condition |
| 3. Rule policy as the floor | the five-rule policy on the same cases under the same program | the line every model condition must beat |
| 4. Evolve by fitting | redistribution parameters on observed load; the guarantee table under the recall-against-rounds score | a calibrated load model; the tightness trade-off tuned by hand so far |
| 5. Evolve by reflection | playbook items and case memory from scored traces; held-out terrain decides acceptance | a playbook and a memory with provenance, and the before-and-after curve |
| 6. Verifier checklist | from the cases where everything passed and the truth still disagreed | the checks applied before a stop is accepted, and the share of such cases they catch |

Under it: "Steps 1 to 3 need no new design; steps 4 to 6 are the
self-evolving part, each with a before-and-after number from the same
scorer."

Last line, set apart: "The limit today is three cases with a ground
truth. The ask is cases."
