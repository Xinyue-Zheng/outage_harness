# Completion check v4: one bin set per down site

Apply to `outage_harness_langgraph` and `outage_harness_rule_based`.
Synthetic fixtures and tests; no real cases. Report every change as file
and line. This amends `Copilot_Completion_Check_v3_Bin_Local_2026-10-30.md`;
where the two disagree, this file wins. `CHECK_VERSION` gains the value
`"v4"`.

## Why

The saved rural cases have down cells at more than one site. The check
has one bin origin, the first site, and one frame F per bin. A location
covered only by a second site lies in some bin of the first site at a
distance that has nothing to do with the second site's footprint, so the
first site's frame cannot say whether coverage continues past it, and the
reach test from that frame may never name the second site's areas. In the
audited two-site run both cores ended complete with covered locations,
some with coverage holes, never queried.

A bin is a wedge from one point and F is the farthest location that
point's cells cover. The check therefore runs once per site. One query
still answers every site's item for that location; only the bookkeeping
multiplies.

## 1. Sites

Every configured down cell maps to one site with coordinates. The run
holds `state["sites"]`: a list of site ids with coordinates and the down
cells each owns. A one-site case is a list of one. Initialization fails
with a named error if a configured cell has no site or a site has no
coordinates; no default position.

## 2. Geometry window

Activity areas are fetched for the union of the per-site windows (the
current window, centred on each site). The ring probe at initialization
runs once per site.

## 3. Bin key

A bin is identified by the string `site/index`, for example
`WTL05870/5`. Every point record and every geometry location stores one
bin index per site, computed once at initialization and at expansion.
The v3 `bin` field becomes a map from site id to index.

## 4. Coverage attribution

A location is covered for site s when any cell of s is at or above
-110 dBm in its sample. The frame F of bin `s/b` is the farthest location
in that wedge covered for s. One sample record updates the frames of
every site.

## 5. Per (area, site, bin) record

The v3 record keyed by bin index is keyed by `site/index`, with the same
fields: `locations`, `queried`, `with_sample`, `covered` (for that site),
`farthest_covered_m`, `boundary_m`, `inside_unqueried`,
`beyond_with_sample`, `covered_beyond`, `unqueried_beyond`, `resolution`.
Distances are from the key's site. Area-level counts stay for the area
line and `run.json`.

## 6. Bin test

Part 4 of v2, as amended by v3, is unchanged in wording and runs for
every `site/index`. The unobserved-bin rule (v2 4.1) applies per site: a
site whose cells have not been seen anywhere has twelve unobserved bins
and each must be probed. The "no coverage seen" rule of v2 applies per
site in the same way.

## 7. Open items

Open items are the union over sites, each (site/index, area, kind).
Rendering groups by area, one line per area:

```
Open: R12: inside for WTL03023/2 (14 unqueried within 3.9 km); beyond for WTL05870/9 (0 of 10 sampled beyond 2.7 km). Legal: query_coverage R12 inside bin=WTL03023/2, or beyond bin=WTL05870/9 n>=10, or all.
```

A location that is inside for two sites is counted once in the area
line. The per-bin progress lines ("minimum N locations to close") are
rendered per site, one block per site, in site order.

## 8. Requests

`inside` and `beyond` take `bin` as the `site/index` string. A request
with a bare index, an unknown site, or a key the area has no locations in
is rejected with the list of legal keys for that area:

```
Rejected: bin "5" is not a key. R12 crosses: WTL03023/2, WTL05870/9.
```

Selection is restricted to the area's locations in that site's wedge, by
distance from that site. Area-wide patterns are unchanged.

## 9. Expansion

R2 and the edge test run per `site/index`; an expansion extends from the
key's site in the key's wedge.

## 10. Floor

`state["floor"]` counts a location once when it appears in inside items
of several sites, and counts a beyond item's `N_MIN_SAMPLED` once per
(area, site/index). `min_action_locations` (rejection-handling
instruction, part 2) is unchanged in meaning.

## 11. Rule policy

Unchanged. Items are ordered nearest first by distance from the item's
own site; ties break by site order then area id. The bin key passes
through.

## 12. Completion and invariant

The run may end only when every bin of every site is closed. The end_run
invariant of v3 part 6 runs over every `site/index`. `run.json` records
`sites`, the per-site bin states, and for every closed bin the sampled
location ids beyond F in that bin.

## 13. Skill text

Two sentences, no more. In the task statement: "The outage covers cells
at N sites: <ids>." In the query section: "A bin key names the site it
belongs to; one query answers every site's item for that location." No
sentence about the order in which to serve sites.

## 14. Fixtures

- F2: two sites 8 km apart, settlements and corridors around each, one
  settlement between them. One location in the between settlement is
  covered only by the second site's cell.
- F3: three sites, two of them 2 km apart and one 9 km away, so the
  close pair has overlapping wedges and the far site a disjoint
  footprint.
- F1: the v3 one-site fixture, unchanged.

## 15. Tests

1. F2: with `CHECK_VERSION v3` the location covered only by the second
   site leaves every bin of the first site closed; with `v4` a beyond
   item on the second site's bin names its area and finish is refused.
2. F2: a location that is inside for both sites is listed once in the
   area line, one query clears both records, and the floor counts it
   once.
3. F2: a `beyond` request with `bin="5"` and one with `bin="WTL09999/5"`
   are rejected with the legal-keys message.
4. F2: an area 3 km from the second site and 12 km from the first is
   present in the geometry.
5. F3: the end_run invariant runs over 36 bins; a hand-built state with
   one closed bin of the far site and no bin-local evidence ends
   `completion_invariant_failed` naming that key.
6. F3: one query in the overlap of the close pair updates records under
   both sites' keys; the rule orders items by distance from their own
   site.
7. F3: the far site with no covered location anywhere keeps twelve
   unobserved bins open until probed; the check does not close them on
   the other sites' samples.
8. F1: open items equal the v3 result apart from the key format.
9. Rendered context on F3 at the round with the most open items stays
   within the size reported for v3 plus the per-site progress block; report
   the number.

## Questions to answer with the report

1. Where site coordinates come from for a configured cell (file and
   line), and whether that lookup is available at initialization without
   a service call.
2. The current geometry window construction (file and line), so the
   change log states how the union replaces it.
3. The per-site progress block length on F3, in characters.
