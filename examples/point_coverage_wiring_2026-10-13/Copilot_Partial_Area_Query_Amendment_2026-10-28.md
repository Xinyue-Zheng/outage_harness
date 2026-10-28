# Amendment to the partial area query: covered-point detail and resolution by extent

Apply after `Copilot_Partial_Area_Query_2026-10-28.md`, to the same two
packages (`outage_harness_langgraph` and `outage_harness_rule_based`). Do
not touch the two concat packages. Synthetic fixtures and tests only; no
real services, no real cases. Report every change as file and line.

Two changes. The first adds detail to the area line so the model can see
where and how strongly an area is covered. The second adds a third way for
an area to resolve, for areas that the down cell covers only in part,
which is the usual case in urban geography.

## 1. Covered-point detail on the area line

Every area state record (part 1.2 of the partial-query instruction) gets
three fields, computed from the queried locations that show the down cell:

```json
"covered": 3,
"covered_distance_m": [5400, 5600],
"covered_rsrp_dbm": [-109, -104],
"farthest_covered_m": 5600
```

`covered_distance_m` is the minimum and maximum distance from the site
among covered locations; `covered_rsrp_dbm` the minimum and maximum of the
strongest outage-sector RSRP among them; `farthest_covered_m` the maximum
distance. All three are null when `covered` is 0.

The rendered area line shows them whenever `covered > 0`:

```
S07 village, 5.8 km NE, 140 locations, crossed by R02 (trunk)
    queried 10 (near_edge), with sample 7, covered 3 at 5.4 to 5.6 km, RSRP -109 to -104 dBm
    open: coverage found to 5.6 km; legal: all (130), or beyond n>=10 (118 unqueried beyond)
```

Distances in km with one decimal, RSRP as integers. The same three fields
appear in `run.json` for every area.

## 2. Resolution by extent

### 2.1 Definition

An area where coverage was found can resolve without a full query when a
sampled band beyond its farthest covered location shows no down cell.

Add to the resolution values:

| value | condition |
|---|---|
| `resolved_extent` | `covered > 0`, and at least `N_MIN_SAMPLED` queried locations with samples lie farther from the site than `farthest_covered_m`, and none of them shows the down cell |

Precedence: `resolved_full`, then `resolved_extent`, then
`resolved_sample`, then `open`, then `unqueried`. `resolved_sample` still
requires `covered == 0`; it is unchanged.

Two more fields on the area state record:

```json
"beyond_with_sample": 12,
"unqueried_within_extent": 41
```

`beyond_with_sample` counts queried locations with samples farther than
`farthest_covered_m`. `unqueried_within_extent` counts unqueried locations
at or nearer than `farthest_covered_m`: the locations that could be
covered but were never queried. It is the undercount risk of an
extent-resolved area and is reported, never hidden.

Reason sentences:

| case | reason |
|---|---|
| open, covered > 0 | `coverage found to D km; legal: all (N), or beyond n>=10 (K unqueried beyond)` |
| open, covered > 0, beyond band started | `coverage found to D km; B of 10 beyond with sample, none covered; legal: all (N), or beyond n>=10` |
| resolved_extent | `resolved by extent: covered C at D1 to D2 km; U unqueried within extent` |

### 2.2 The `beyond` pattern

Add a sixth pattern, legal only when the area has `covered > 0`:

| pattern | selection |
|---|---|
| `beyond` | the n unqueried locations with distance from the site greater than `farthest_covered_m`, nearest to it first |

Validation: `beyond` on an area with `covered == 0` is rejected with
`beyond needs a covered location in area X; use near_edge, far_edge or
sparse`. If fewer than n unqueried locations lie beyond, the request takes
all of them and the message in the step record says so; if none lie
beyond, the request is rejected with `no unqueried location beyond the
farthest covered location in X; legal: all`.

When the beyond band moves (a later query finds a covered location farther
out), `farthest_covered_m` moves with it and `beyond_with_sample` is
recomputed from the new value. An area can therefore fall back from
"beyond band started" to "coverage found" and the model sees that on the
line.

### 2.3 Legal actions when coverage was found

Replace the rule "any covered location: the only legal request is all"
with: when `covered > 0`, the legal requests are `all` and `beyond`
(n at least `N_MIN_SAMPLED`). `near_edge`, `far_edge`, `sparse` and
`roadside` are rejected on such an area with the message
`coverage found in X; legal: all or beyond`.

### 2.4 Completion check

An area with `resolved_extent` is resolved. For the boundary test in a
bin:

- its `farthest_covered_m` moves the bin's farthest covered location
  outward, as a `resolved_full` area with coverage does today;
- its own beyond band is the absence evidence for that location, so no
  farther area is required for closure on account of this area;
- areas farther out in the bin are still subject to the "within reach"
  rule: an unresolved area within the activity reach remains an open item.

### 2.5 Impact counting and the report

Impact classes are computed from queried covered locations, as today. For
an extent-resolved area the report and `run.json` list the area with its
`unqueried_within_extent`, and the report's area table gets a column
"unqueried within extent". The evaluation reads it as a separate number
beside area recall; it is the price of the extent resolution and must be
visible next to the budget saved.

### 2.6 Rule policy

`RULE_PATTERN` gains a third value, `near_edge_extent`:

| `RULE_PATTERN` | unqueried area | open, covered == 0 | open, covered > 0 |
|---|---|---|---|
| `all` | all | all | all |
| `near_edge` | near_edge, n = 2 * N_MIN_SAMPLED | near_edge, n = min(2 * N_MIN_SAMPLED, unqueried) | all |
| `near_edge_extent` | near_edge, n = 2 * N_MIN_SAMPLED | near_edge, n = min(2 * N_MIN_SAMPLED, unqueried) | beyond, n = 2 * N_MIN_SAMPLED; all when nothing lies beyond |

The three variants are three rule baselines (`RB-all`, `RB-near`,
`RB-extent`); `run.json` records which one ran.

### 2.7 Skill text

Add two sentences after the pattern definitions: "`beyond` queries the n
unqueried locations just past the farthest location where the down cell
was seen; it is legal only after coverage was found. An area where
coverage was found resolves when 10 locations beyond its farthest covered
location returned samples and none shows the down cell; locations nearer
than that which were never queried are reported as unqueried within
extent." Nothing about when to prefer `all` or `beyond`.

## 3. Tests

1. Area line: a fixture with 3 covered locations renders the distance band
   and RSRP range exactly as in part 1; a fixture with 0 covered renders no
   band.
2. `beyond` selector: picks the n nearest unqueried locations past
   `farthest_covered_m`, deterministic; rejected on an area with no
   coverage; takes all remaining when fewer than n lie beyond.
3. Resolution: covered 3, beyond_with_sample 10, none covered is
   `resolved_extent`; the same with 9 is `open` with the "beyond band
   started" reason; a later covered location farther out resets
   `beyond_with_sample` and the state returns to `open`.
4. Precedence: an area fully queried with coverage is `resolved_full`,
   never `resolved_extent`.
5. Completion: a bin whose only area is `resolved_extent` closes without a
   farther area; the same bin with an unresolved area within reach stays
   open.
6. Report and `run.json`: `unqueried_within_extent` present per area and
   summed in the run summary.
7. Rules: `RB-extent` proposes `beyond` 20 on an area with coverage found
   and `all` when nothing lies beyond.

## Questions to answer with the report

1. The distance used for `farthest_covered_m` is the grid-cell centre
   distance to the site; confirm that the same distance function is used
   by `near_edge`, `far_edge` and the direction records, with file and
   line.
2. Whether the strongest outage-sector RSRP per location is already stored
   in the point record or must be added.
