# Request overlap check: inside and beyond on one area and bin in one action

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Amends check 4 of `Copilot_Partial_Area_Query_2026-10-28.md`
part 3 as implemented after v3 and v4. No completion rule changes.

## Why

A model run was rejected for an action carrying S01 inside, S01 beyond,
R04 inside and R04 beyond in one bin. Inside and beyond select from
disjoint pools (at or nearer than the boundary, past it), so nothing is
double-charged. The check forced the natural one-round closure of a bin
into four rounds plus the rejected ones.

## 1. Check 4

Two requests overlap only when their selection pools can intersect:

| pair, same area | overlap |
|---|---|
| different bins | no |
| same bin, inside with beyond | no |
| same bin, two inside, or two beyond | yes |
| same bin, beyond with near_edge, far_edge or sparse in that bin | yes |
| any bin request with an area-wide request | yes |

Two different areas never overlap. Reject on overlap with a message that
names the two requests and the shared pool:

```
Rejected: requests 1 and 3 both select from S01 bin WTL03023/5 beyond the boundary.
```

## 2. Rendering

An open item with both an inside and a beyond part lists them as one
legal action:

```
Legal: query_coverage S01 inside bin=WTL03023/5 + beyond bin=WTL03023/5 n>=10
```

## 3. Skill text

One sentence in the `query_coverage` paragraph: "One action may carry
up to four requests; inside and beyond on the same area and bin in one
action is the normal way to close a bin in one round."

## 4. Tests

1. An action with S01 inside bin=k, S01 beyond bin=k n=10, R04 inside
   bin=k and R04 beyond bin=k n=10 is accepted, all four execute, and
   the charged locations equal the sum of the four.
2. Two inside requests on S01 bin=k are rejected with the message of
   part 1.
3. S01 beyond bin=k with S01 sparse bin=k is rejected; S01 beyond bin=k
   with S01 beyond bin=j is accepted.
4. The rendered open item of fixture 1 carries the combined legal
   action of part 2, and the parsed action passes validation.

## Question to answer with the report

File and line of check 4 as it stood, and its condition, so the report
says what was rejected before.
