# Final report: proposal (not implemented)

The report is produced by the program after the completion check passes. It
reads State only: the coverage table (every sample's cells with RSRP per
location), the per-area summaries, the KPI baselines, and the completion
result. The model writes none of it.

## 1. What each location becomes

Every location where an outage sector serves is put in exactly one class.
"Living backup" means a cell that is not an outage cell, of the same
technology, observed in the same sample as the outage sector at that
location. When the whole base station is down, every sector of it is an
outage cell, so none of them is a living backup.

| class | condition at the location |
|---|---|
| total loss | no living backup is observed in any sample at the location |
| degrade, signal | a living backup exists, but the strongest one is weaker than the outage sector by more than a margin, or below the service threshold [both numbers are parameters, to be chosen] |
| degrade, capacity | a living backup exists with adequate signal, but its estimated load after the transfer exceeds a limit |
| degrade, signal and capacity | both of the above |
| served by backup | a living backup exists with adequate signal and load within the limit |
| degrade, unknown cause | a living backup exists but its load baseline is missing, so the capacity part cannot be assessed; the signal part is still reported |

The capacity estimate per backup cell, as in the outside harness:
estimated PRB = baseline PRB + 100 × transferred share × (outage sector's
baseline PRB) / capacity, where the transferred share is the fraction of the
outage sector's served locations assigned to that backup (the strongest
living backup at each location). [Open: whether a per-location demand
measure exists in the real data. Without one, locations are the unit, and
the report says so.]

## 1b. Where, and how much of the area

For each area and each non-empty class the report gives a sentence with the
count, the share, and the position. All of it is computed from the class's
grid locations.

- Share: class locations over the locations the outage sector serves in
  the area; the table also gives the share over all valid locations of the
  area.
- Position: the centroid of the class locations relative to the area's
  centroid, as one of eight compass words; "centre" when within a quarter of
  the area's radius.
- Grouping: connected components of the class locations on the grid. One
  component with most of them: "gathered in the <position> part". Two or
  three: "in N groups", with a position each. More: "scattered across".
- Road corridors: position along the road, from the component's nearest
  settlement and the direction from it: "the stretch leaving S1 to the east".
- Name: the area's OpenStreetMap name tag, kept at initialisation.

Sentence template:

    In <area> (<name>), <share>% of the locations the outage sector serves
    <class phrase> (<count> of <served>); they are <grouping and position>.

Examples:

    In S1 (Mansfield town), 30% of the locations the outage sector serves lose
    connection entirely (9 of 30); they are gathered in the north-west part of
    the town.
    On road_H1, 12% of served locations lose connection (6 of 48), in two
    groups: the stretch leaving S1 to the east, and the stretch near S2.
    In S1, 20% may degrade by signal (6 of 30), scattered across the town.

A map per area with served locations coloured by class is written next to
the report for the human reader; the sentence carries the fact.

## 2. Report layout

```
OUTAGE IMPACT REPORT
Case: EnodeB CCL06069, planned outage 2026-02-10 09:00 to 12:00 UTC
Outage sectors observed: CCL06069_aa_1, CCL06069_ab_1 (whole site down: no sector of CCL06069 is a backup)
Completion: boundary check passed in 6 of 6 checked directions; 0 left open.
Evidence: 214 locations fetched in 4 areas, 183 with samples; budget 214 of 1500.

1. Where service is lost or degraded (locations where an outage sector serves)

                         served   total loss   degrade      degrade       degrade    served by   degrade
   area                  by d                  signal       capacity      both       backup      unknown cause
   S1 (village)            21         4           3            6             0          8           0
   road_H1 (corridor)      27         2           5            9             2          9           0
   S2 (hamlet)              6         0           0            0             0          0           6
   total                   54         6           8           15             2         17           6

   S1 (Mansfield town): 19% of the locations the outage sector serves lose connection entirely (4 of 21),
     gathered in the north-west part of the town. 14% may degrade by signal (3 of 21), scattered across
     the town. 29% may degrade by capacity (6 of 21), gathered in the east part.
   road_H1: 7% lose connection (2 of 27), the stretch leaving S1 to the east. 33% may degrade by
     capacity (9 of 27), the stretch between S1 and S2.
   S2 (hamlet): 100% have a backup whose load cannot be assessed (6 of 6); see section 2.

2. Why: per backup cell

   CCL00002_aa_1 (LTE): strongest living backup at 31 locations (57% of served locations).
     Signal: adequate at 24, weaker than the outage sector by more than 10 dB at 7.
     Load: baseline PRB 41% (4 prior weeks, same weekday and hours); estimated after transfer 78%;
           limit 70%: exceeded. Locations assigned to it are therefore "degrade, capacity" unless
           already "degrade, signal".
   CCL00003_ab_1 (LTE): strongest living backup at 17 locations (31%).
     Signal: adequate at 11, weaker at 6.
     Load: baseline PRB 22%; estimated 39%; within limit.
   CCSN000004_aa_1 (NR): observed at 15 locations; not an eligible backup for an LTE outage.
   Backup cells without load baseline: CCL00005_aa_1, present in S2 (6 locations); whether service
     degrades there cannot be assessed because its historical load data is missing.

3. Total loss, by location
   S1: grid 171, 172, 189, 191 (centre of the village; the only cell listed is an outage sector)
   road_H1: grid 243, 262

4. What this report does not establish
   - Locations with missing data: S1 9, road_H1 12, S2 2. Coverage there is unknown.
   - 0 directions left open at the study-area edge. [When open: "north-east: outage sector served
     to 2.1 km; no activity location beyond inside the study area; expand the study area to close."]
   - Land use is not demand; counts are locations, not users or traffic.
   - Activity areas outside every sector's reach were not required and were not queried: F1.
```

## 3. What exists and what is missing to produce it

Exists in State today: served locations per area and per sector; the living
backups co-observed per location with RSRP; the strongest cell per
location; the KPI baseline per cell when queried; missing-data counts per
area; the completion result.

Missing:

- The two signal parameters (margin against the outage sector, service
  threshold) and the load limit. Choose them or make them run parameters.
- The transfer rule for load: strongest living backup per location, as in
  the outside harness, or a split. One line of code either way.
- Per-location demand, if the real data has any. Otherwise the unit is
  locations and the report says so.
- The outage sector's own baseline PRB, needed for the transferred load. It
  comes from the same KPI tool; the skill already tells the model to query
  the outage cells too.
- The open-direction text depends on the completion rule being implemented.

## 4. Where it lives

One function in `completion_point.py` next to the check, returning the text
and a JSON twin of the tables (for the UI and for scoring later). Called by
the finish node after the check passes, or by the cap node with a header
line saying the run ended by a cap and the check did not pass.
