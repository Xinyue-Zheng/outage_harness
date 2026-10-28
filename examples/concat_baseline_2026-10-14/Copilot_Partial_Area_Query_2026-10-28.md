# Partial area queries with selection patterns

Apply to the internal copy of `outage_harness_langgraph` (the harness) and
to `outage_harness_rule_based` (the rules runner). Do not touch the two
concat packages. No runs against real services or real cases; use the
synthetic fixtures and tests. Report every change as file and line, and
answer the questions at the end. This builds on
`Copilot_Harness_Changes_2026-10-27.md` (radius 4 or 10, four-rule policy)
and `Copilot_Budget_In_Context_2026-10-28.md` (budget block); both must be
in before this one.

## 0. What changes and why

Today one coverage action queries one whole activity area. The model has
no choice about how much of an area to query, so under a budget the
outcome is decided by the budget, not by the decision core. This change
lets one action carry up to four requests, each for a whole area or for n
locations of an area chosen by a named pattern. The program selects the
locations; the model never names a point. The completion check gains one
rule: an area can be resolved by a sample that shows no down-cell
coverage, but an area where any location shows the down cell must be
queried in full, because the impact statistics count every covered point.

Constants (one module, imported by both packages):

| constant | value | meaning |
|---|---|---|
| `N_MIN_SAMPLED` | 10 | locations with samples and no down cell needed to resolve an area by sample |
| `MAX_REQUESTS_PER_ACTION` | 4 | requests in one coverage action |
| `PATTERNS` | `("all", "near_edge", "far_edge", "sparse", "roadside")` | selection patterns |
| `AREA_RESOLUTIONS` | `(4, 10)` | radius, unchanged |

## 1. Data model

### 1.1 Point record

Every queried location record gets one new field:

```json
"selector": "near_edge"
```

Values: `all`, `near_edge`, `far_edge`, `sparse`, `roadside:<corridor id>`,
`probe` (ring probe), `expansion` (locations added by a wedge, if they
are queried as part of the wedge). The field says which pattern chose the
location. It is never read by the completion check; it is for the report
and the evaluation.

### 1.2 Area state

Each activity area (settlement or corridor) gets a state record,
recomputed by the program after every executed step:

```json
"S07": {
  "locations_total": 140,
  "queried": 20,
  "queried_by_selector": {"near_edge": 10, "roadside:R02": 10},
  "with_sample": 7,
  "covered": 2,
  "unqueried": 120,
  "resolution": "open",
  "reason": "coverage found; query all"
}
```

`resolution` is one of:

| value | condition |
|---|---|
| `unqueried` | `queried == 0` |
| `open` | queried but none of the three below holds |
| `resolved_sample` | `covered == 0` and `with_sample >= N_MIN_SAMPLED` |
| `resolved_full` | `unqueried == 0` |

Precedence: `resolved_full` is checked first, then `resolved_sample`, then
`open`, then `unqueried`. `covered` counts queried locations where any
outage sector is at or above `COVERAGE_RSRP_DBM`. `with_sample` counts
queried locations that returned at least one sample.

`reason` is a fixed sentence per case, used by the rendering:

| case | reason |
|---|---|
| open, covered > 0 | `coverage found; query all (N unqueried)` |
| open, covered == 0, with_sample < N_MIN_SAMPLED | `need K more with sample` where K = N_MIN_SAMPLED - with_sample |
| resolved_sample | `resolved by sample` |
| resolved_full, covered > 0 | `resolved in full` |
| resolved_full, covered == 0, with_sample == 0 | `resolved in full, no samples` |
| resolved_full, covered == 0, with_sample > 0 | `resolved in full, not covered` |

An area with `resolved_full` and `with_sample == 0` is what the direction
status `closed_without_sample` reads.

## 2. Action schema

Replace `query_area_coverage(area, resolution)` by:

```json
{
  "name": "query_coverage",
  "parameters": {
    "requests": [
      {"area": "S07", "pattern": "near_edge", "n": 10, "resolution": 10},
      {"area": "S05", "pattern": "all", "resolution": 10},
      {"area": "S07", "pattern": "roadside", "corridor": "R02", "n": 10, "resolution": 10}
    ]
  }
}
```

Declaration: `requests` is an array of 1 to `MAX_REQUESTS_PER_ACTION`
objects. `area` is a string. `pattern` is an enum of `PATTERNS`.
`resolution` is an enum of `AREA_RESOLUTIONS`. `n` is an integer, required
for every pattern except `all`, forbidden for `all`. `corridor` is a
string, required for `roadside`, forbidden otherwise. Put these rules in
the declaration description in one sentence each. One declaration only;
remove the old one.

## 3. Validation

Validate the whole action before executing any request. On the first
failure, reject the whole action with one message, record the rejection,
and count the round, as for every rejection. Checks, in this order:

1. `requests` has 1 to `MAX_REQUESTS_PER_ACTION` entries. Message:
   `query_coverage takes 1 to 4 requests; got N`.
2. Each `area` exists in the geometry. Message: `unknown area X; areas: ...`
   listing the areas the open items name.
3. Each `area` has resolution `unqueried` or `open`. Message:
   `area X is resolved (<reason>); it cannot be queried again`.
4. No `area` appears twice in one action. Message: `area X appears twice`.
5. Each `pattern` is in `PATTERNS`; each `resolution` in `AREA_RESOLUTIONS`.
   Message names the allowed values.
6. For `all`: no `n`, no `corridor`. For the other patterns: `n` present,
   `N_MIN_SAMPLED <= n <= unqueried` of that area. Message:
   `n for area X must be between 10 and <unqueried>`.
7. For `roadside`: `corridor` is a corridor id that crosses the area
   (shares at least one grid cell with it, or lies within the corridor
   half-width of any area location). Message:
   `corridor R0x does not cross area X; corridors crossing X: ...`.
8. Cost: sum over requests of `n` (or `unqueried` for `all`) is at most
   `locations_left` from the budget record. Message:
   `action costs N locations; M left`.

The existing "fully queried area" rejection (C2) is replaced by check 3.
The existing "queried at the other radius" rejection stays: a location is
queried once, at one radius.

## 4. Selectors

All selectors operate on the unqueried locations of the area, use the
location centre coordinates, and break ties by ascending grid id. They
are pure functions: (area locations, queried set, site, corridors, n) to
an ordered list of grid ids. Put them in one module with one function per
pattern.

| pattern | selection |
|---|---|
| `all` | every unqueried location |
| `near_edge` | the n unqueried locations with the smallest distance to the site |
| `far_edge` | the n unqueried locations with the largest distance to the site |
| `sparse` | farthest-point sampling: start with the unqueried location nearest the site; then repeat n-1 times: pick the unqueried location whose minimum distance to every location already picked is largest. Result: n locations evenly spaced over the area |
| `roadside` | the n unqueried locations with the smallest distance to the corridor's centreline (distance to the nearest corridor grid cell centre) |

Determinism test: the same inputs give the same ordered list on two calls.

## 5. Execution and state update

- Execute requests in the order given. Each request produces one point
  query call for its selected locations at its radius; charge the
  location count to the budget; store the point records with
  `selector` set.
- If one request fails at the client (transport error), stop the action
  there, keep the results of the earlier requests, record the failure in
  the step, and do not charge the failed request. The round counts as
  executed, not rejected.
- After the action, recompute every touched area's state record (part
  1.2), the coverage facts, the direction records and the completion
  checks, as today.
- The step record lists, per request: area, pattern, n, resolution,
  locations charged, with_sample, covered, and the area resolution after
  the request.

## 6. Completion check

In the boundary check, replace every test on "unqueried activity
locations" by a test on area resolution:

- Within the activity reach of an active-plus-margin bin: every activity
  area must be `resolved_sample` or `resolved_full`. An `open` or
  `unqueried` area is an open item.
- Beyond the farthest covered location in the bin: the nearest activity
  area must be `resolved_sample`, or `resolved_full` with `covered == 0`.
  A `resolved_full` area with `covered > 0` moves the farthest covered
  location outward, and the test repeats with the next area, as today.
  An area with `resolved_full` and `with_sample == 0` is skipped, as
  today, and sets `closed_without_sample` if it is the last candidate.
- A `resolved_sample` area counts as absence for closure. Its covered
  count is zero by definition.

The check reads area states only. It never reads `selector`.

Frame cap and legacy-edge exceptions are unchanged. `backup_load` is
unchanged; co-observed backups come from queried points, whatever the
selector.

## 7. Rendering

### 7.1 Area lines

In the geometry section, every area line shows the total location count,
distance, bearing, the corridors that cross it, and, when queried, the
breakdown and the state. Exact format:

```
S07 village, 5.8 km NE, 140 locations, crossed by R02 (trunk)
    queried 20 (near_edge 10, roadside R02 10), with sample 7, covered 2, open: coverage found; query all (120 unqueried)
S05 town, 1.1 km E, 410 locations
    queried 410 (all), with sample 302, covered 97, resolved in full
S09 hamlet, 7.4 km N, 31 locations
    unqueried
R02 trunk corridor, 3.1 to 8.2 km NE, 260 locations
    queried 40 (sparse), with sample 12, covered 0, resolved by sample
```

The second line is the state record in words; the `reason` sentence of
part 1.2 is used verbatim after the colon.

### 7.2 Open items

An open item for an area states the fact and the legal actions, not one
action:

```
open: S07 is open (coverage found; query all, 120 unqueried).
      Legal: query_coverage S07 all (120 locations).
open: S09 is unqueried (31 locations, 7.4 km N).
      Legal: query_coverage S09 all (31), or near_edge / far_edge / sparse n>=10, or roadside R02 n>=10.
```

When an area has `covered > 0`, the only legal request is `all`. When an
area is `unqueried` or `open` with `covered == 0`, list `all` and the
patterns with the minimum n. For `roadside`, list the crossing corridors.
Each open item ends with its cost, as in the budget instruction.

### 7.3 Budget block

Unchanged. The cost line of each open item lets the model compare n with
`locations left`.

## 8. Skill text

Replace the sentence about `query_area_coverage` with these lines, and
nothing else about coverage queries:

```
query_coverage sends up to 4 requests in one action. A request names an
area, a pattern, a radius (4 or 10) and, except for "all", a number n of
locations (at least 10). Patterns: "all" queries every unqueried location
of the area; "near_edge" the n locations nearest the site; "far_edge" the
n farthest from the site; "sparse" n locations evenly spaced over the
area; "roadside" the n locations nearest a named corridor that crosses
the area. The program chooses the locations. An area is resolved when 10
queried locations returned samples and none shows the down cell, or when
every location is queried. An area where any location shows the down
cell must be queried in full. A location with no sample counts as
missing, not as uncovered.
```

No sentence about which pattern to use when. That belongs to the playbook.

## 9. Rule policy

Rule R1 ("the boundary check names an area to fetch") becomes: take up to
`MAX_REQUESTS_PER_ACTION` open areas, nearest to the site first, and build
one action. The requests depend on a package constant `RULE_PATTERN`:

| `RULE_PATTERN` | request for an `unqueried` area | request for an `open` area |
|---|---|---|
| `all` | `all` | `all` |
| `near_edge` | `near_edge`, n = 2 * N_MIN_SAMPLED, radius 10 | if `covered > 0`: `all`; else `near_edge`, n = min(2 * N_MIN_SAMPLED, unqueried) |

When n would be below `N_MIN_SAMPLED` because fewer locations remain, the
request is `all`. The two variants are two rule baselines, `RB-all` and
`RB-near`; `run.json` records which one ran. R2, R3, R4 are unchanged.

## 10. Run record and report

`run.json` gets:

- `areas`: the state record of part 1.2 for every area, plus
  `queried_by_selector`.
- `locations_by_selector`: totals per selector value.
- `rule_pattern` (rules runner only).

The report lists, per area, its resolution and reason. The impact classes
are computed from queried covered locations as today; a `resolved_sample`
area contributes none. The evaluation reads `areas[...].resolution` to
separate areas resolved by sample from areas resolved in full.

## 11. Tests

Synthetic fixtures only.

1. Selector determinism and correctness: for a 12 by 12 area with the site
   outside it, `near_edge` 10 are the 10 nearest, `far_edge` 10 the 10
   farthest, `sparse` 10 have a minimum pairwise distance above the grid
   step times 2, `roadside` 10 lie within the corridor half-width plus one
   cell of a corridor that crosses the area.
2. Validation: each of the eight checks has one failing fixture and the
   expected message.
3. Resolution: an area with 10 sampled, 0 covered is `resolved_sample`;
   with 9 sampled is `open` with `need 1 more with sample`; with 1 covered
   is `open` with `coverage found`; with all queried and 0 samples is
   `resolved_full, no samples`.
4. Completion: a direction whose nearest area beyond is `resolved_sample`
   closes; the same direction with that area `open` is an open item that
   lists the legal actions.
5. Rendering: the area lines and open items of part 7, character for
   character, for a fixture with the four areas shown.
6. Rules: `RB-all` and `RB-near` each produce the expected action on the
   fixture of test 5; `RB-near` on an `open` area with `covered > 0`
   requests `all`.
7. Budget: an action whose cost exceeds `locations_left` is rejected with
   the message of check 8, and the budget record is unchanged.

## Questions to answer with the report

1. How the corridor centreline is represented in the geometry, so that
   `roadside` distance is defined on it (grid cells, polyline, or both).
2. Whether corridor areas themselves can be queried with `roadside`
   (recommended: no; a corridor uses `all`, `near_edge`, `far_edge` or
   `sparse`).
3. The number of activity areas and the total location count per case
   type in the synthetic fixtures, so that the location budgets for the
   experiment can be set below the full-query cost.
