# Completion rule: proposal for discussion (not implemented)

Revised after the comments of 2026-10-15. The direction-based version is
withdrawn; the rule below needs no direction, no distance threshold, and no
wedge count. Nothing here is in code yet. The same rule will go into both
packages once agreed.

## What the comments establish

1. Only areas with human activity count: settlements, road corridors, and
   activity areas (A##) where they exist. Forest, farmland and water are
   never required, even where coverage extends into them.
2. Closure must follow the shape of the coverage, which is a sector and not
   a circle, without a hand-chosen number of directions.
3. One absent area outward is enough.
4. Missing data is not a separate case. A location with no sample is simply
   not evidence of service or absence.
5. A missing backup load never blocks completion; the report states it.

## The rule: grow over the activity areas

Definitions, all computed by the program from State and the geometry file.

- **Activity area**: an area of kind settlement, road corridor or activity
  area. Nothing else is ever required.
- **Served in an area**: the outage sector is the serving sector of at least
  one sample at some location of the area. **Absent in an area**: the area is
  fully fetched (every location was queried) and at every location that has
  samples the sector is never serving and never the strongest cell.
- **Neighbours of an area**: the activity areas that touch it (share a grid
  location or intersect, which the initialisation already records as
  relations), and, if it touches none, the nearest activity area to it by
  boundary distance. Every area therefore has at least one neighbour unless
  it is the only activity area.

Closure, per outage sector c, is a region that grows from where c serves:

- Start with every activity area where c is served.
- (a) Every area in the region is fully fetched.
- (b) Every neighbour of an area in the region is fetched. If c is served
  there, it joins the region and (a) and (b) apply to it in turn. If c is
  absent there, the region stops at it.
- The region is closed when every neighbour of every area in it is either
  in the region or absent. An area with no neighbour outside the region
  closes by exhaustion.

The boundary check passes when the region of every observed outage sector is
closed. It is the only required check. Backup load is reported, never
required.

Why this needs no direction: the region only grows where the sector is
served, so a sector-shaped coverage produces a sector-shaped region, and a
settlement on the far side of the site is never visited unless coverage
reaches a neighbour of it. The forest case: S1 served; its neighbour, the
highway corridor, is fetched and served near S1, so it joins; the corridor's
neighbour S2 is fetched and shows absent; S2 has nothing to do with the
forest; closed. If S1 has no neighbour at all, closed by exhaustion after S1
is fully fetched.

What the rule does not do, stated so it can be judged:

- A served pocket beyond an absent area (coverage returning past a
  building) is not demanded. The model may still query it from the area
  list; the rule does not force it. That is the "one absent area" choice.
- Missing-data locations never block closure. They are counted and reported
  per area.
- A long road corridor is one area: if the sector serves anywhere on it, all
  of it must be fetched. If that is too costly on the real map, the
  initialisation can split corridors at settlements, which changes the
  areas, not the rule.

## What the context shows (so the model can act on the rule)

Per outage sector: the areas in its region with their fetched share, and the
open neighbours, which are exactly the areas to query next for closure.

```
CCL06069_aa_1: region S1 (30 of 30), road_H1 (60 of 60); open neighbours: S2 (0 of 16 fetched); closed neighbours: none.
CCL06069_ab_1: region S1 (30 of 30); open neighbours: none; closed neighbours: road_H1 (absent); closed.
```

The finish feedback lists the same open neighbours, so the context and the
feedback agree on what is missing.

## The report

Produced by the program after the boundary check passes.

1. Per outage sector: the areas where it serves (its region) and the areas
   that close it.
2. Per activity area in a region: locations served by an outage sector, the
   backup cells observed in the same sample as the outage sector with their
   location counts and RSRP range, and the locations with no eligible
   backup.
3. Per backup cell: its load baseline if present; otherwise "Backup cell X
   is present in areas Y; whether service degrades after the outage cannot
   be assessed because its historical load data is missing."
4. Unknowns: locations with missing data per area; areas closed by
   exhaustion; activity areas outside every region, which were never
   required.

## Open before implementation

- Confirm the neighbour definition: touching, else nearest by boundary
  distance. An alternative is "the two nearest", which costs one more area
  per region edge and partly covers the pocket case.
- Activity areas A##: present in the real State per the skill text; absent
  from the synthetic case, which needs them for the report sample.
- Whether the program report replaces your `final_step_report` function or
  feeds it.
