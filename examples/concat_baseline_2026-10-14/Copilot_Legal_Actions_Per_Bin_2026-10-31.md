# Legal actions per (area, bin): one function for validator and renderer

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. Builds on `Copilot_Completion_Check_v3_Bin_Local_2026-10-30.md`,
`Copilot_Completion_Check_v4_Per_Site_Bins_2026-10-31.md` and
`Copilot_Rejection_Handling_2026-10-31.md`. No completion rule changes.

## Why

A model run ended `rejection_cap` on an open item that had no legal
affordable action:

- the item was (S01, bin k), and bin k had no boundary F, so `inside`
  and `beyond` were both illegal in that bin;
- the rendered item said `near_edge` was legal, but the validator applies
  the v2 part 3 rule at the area level ("no covered location and no
  interior part"), and S01 has covered locations in another bin, so
  `near_edge` was rejected;
- `all` on S01 costs 50 978 locations, above the budget.

Two defects. First, the renderer and the validator compute legality with
different rules, so the context can name an action the validator rejects.
Second, since v3 the open items are per (area, bin) but the sampled
patterns are still legal per area, so a large area that is covered in one
bin has no sampled action left in any other bin. Raising the cap cannot
fix either.

## 1. One legality function

Add one function, in the validation module:

```
legal_requests(area_id, bin_key, state) -> list[RequestTemplate]
```

A `RequestTemplate` is pattern, `bin` (or none), the legal range of `n`
(or none for `all`), the location count the request costs, and whether
that cost is within `locations_left`. The validator's pattern check
(check 5 and 6 of the partial-query instruction, as amended by v2 part 3
and v3 part 5) and the renderer's `Legal:` text both call this function
and nothing else. The renderer prints the templates it returns; the
validator accepts a request only if it matches one of them. Delete the
separate legality rules in the renderer.

## 2. Legality per (area, bin)

For an open item (area, `site/index` key k), with the counts of the
(area, k) record:

| request | legal when |
|---|---|
| `inside bin=k` | `inside_unqueried > 0` |
| `beyond bin=k n` | bin k has a boundary (`boundary_m` not null) and `unqueried_beyond > 0`; `min(N_MIN_SAMPLED, unqueried_beyond) <= n <= unqueried_beyond` |
| `near_edge bin=k n`, `far_edge bin=k n`, `sparse bin=k n` | the (area, k) resolution is `unqueried` or `open` and the area has unqueried locations in bin k; `min(N_MIN_SAMPLED, unqueried in bin k) <= n <= unqueried in bin k` |
| `roadside bin=k n corridor=c` | as the row above, and corridor c crosses the area's locations in bin k |
| `all` | always; cost is the area's unqueried count |

The area-wide forms (`near_edge`, `far_edge`, `sparse`, `roadside`
without `bin`) keep the v2 part 3 rule unchanged: legal only when the
area has no covered location and no interior part. They are never listed
for an item whose area has coverage somewhere.

Consequence: every open item has at least one legal request that costs at
most `N_MIN_SAMPLED` locations. The affordability guard
(rejection-handling part 2) therefore ends the run with `query_budget`
only when fewer than that remain.

## 3. Selection with `bin`

`near_edge`, `far_edge`, `sparse` and `roadside` with `bin=k` select
among the area's unqueried locations whose bin for the key's site is k,
with distances measured from the key's site, by the selectors of the
partial-query instruction part 4. Farthest-point sampling for `sparse`
starts from the wedge location nearest the key's site. Without `bin` the
selectors are unchanged.

## 4. How an item in a bin without a boundary closes

Nothing in the bin test changes. For the record: with no F in bin k, the
(area, k) record closes by `resolved_sample` on bin-local counts
(`with_sample >= N_MIN_SAMPLED` in bin k, `covered == 0` in bin k) or by
`resolved_full`. If a sample in bin k shows the down cell, bin k gets a
boundary, the record is recomputed, and the item becomes `inside` or
`beyond` as in v3. The rendered item states this.

## 5. Rendering

Open item in a bin without a boundary:

```
Open (beyond), bin WTL03023/7: S01: no coverage seen in this bin; 0 of 10 sampled. Legal: query_coverage S01 near_edge bin=WTL03023/7 n>=10, or sparse bin=WTL03023/7 n>=10, or all (50978 locations, exceeds 11 left).
```

Rules for the `Legal:` text:

- every template from part 1 is listed, in the order of the table in
  part 2;
- `all` always shows its cost, and `exceeds N left` when the cost is above
  `locations_left`;
- a request that exceeds the budget is still listed, because it is legal;
  the budget check (check 8) rejects it with its own message.

The `min_action_locations` of the floor record for this item is
`min(N_MIN_SAMPLED, unqueried in bin k)`.

## 6. Rejection messages

A request on an open item that matches no template is rejected with the
template list for that item, from the same function:

```
Rejected: near_edge without bin is not legal for S01 (covered in WTL03023/3). Legal: query_coverage S01 near_edge bin=WTL03023/7 n>=10, or sparse bin=WTL03023/7 n>=10, or all (50978 locations, exceeds 11 left).
Rejected: beyond bin=WTL03023/7 is not legal: bin WTL03023/7 has no boundary. Legal: ...
```

## 7. Rule policy

Rule R1 is unchanged in wording. The item carries the bin and the rule
passes it through, as in v3 part 5:

- settings B and C: for an item in a bin without a boundary, the rule
  proposes `near_edge bin=k n = min(N, unqueried in bin k)`;
- setting A: the rule proposes `all`; when `all` exceeds the budget the
  request is rejected by check 8, the rule takes the next item
  (rejection-handling part 3), and the run ends `rule_rejected` when no
  item is left. That is the recorded behaviour of setting A on a large
  area, not a defect.

## 8. Tests

1. Fixture: S01 with 50 978 locations across bins `WTL03023/3` and
   `WTL03023/7`, covered in bin 3, nothing queried in bin 7, 11 locations
   left. The open item for (S01, 7) renders exactly the text of part 5.
   `near_edge bin=WTL03023/7 n=10` is accepted. `near_edge` without `bin`
   is rejected with the first message of part 6. `beyond bin=WTL03023/7`
   is rejected with the second.
2. Agreement: for every open item of every fixture, each rendered legal
   request, parsed back into an action, passes validation up to check 7
   (the budget check excluded). One test over all fixtures.
3. On fixture 1, after ten clean samples in bin 7, (S01, 7) is
   `resolved_sample` and the item is gone. After one covered sample in
   bin 7 instead, bin 7 has a boundary and the item is `inside` or
   `beyond`.
4. `near_edge bin=k n=10` returns ten locations, all with bin k for the
   key's site, nearest to that site first. `sparse bin=k` returns
   locations with bin k only.
5. The floor record on fixture 1 has `min_action_locations` 10, and the
   affordability guard does not fire with 11 left.
6. Rule core on fixture 1: setting B proposes
   `near_edge bin=WTL03023/7 n=20`; setting A proposes `all`, is rejected
   by check 8, and the run ends `rule_rejected` with the rejection stored.

## Questions to answer with the report

1. File and line of the renderer's `Legal:` text and of the validator's
   pattern check today, and confirmation that after the change both are
   one call to `legal_requests`.
2. The number of areas in the synthetic fixtures whose unqueried count
   exceeds `max_query_locations`, so the tests cover at least one.
