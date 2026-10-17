# Final outage report: CCL00001

- Outage window: 2026-02-10T09:00:00Z to 2026-02-10T12:00:00Z (planned; not evidence that it happened)
- Objective: Find where the outage sectors serve users and which cells can take over.
- Generated: 2026-10-17T19:00:41-04:00
- Run end: complete; boundary check complete; backup_load check complete (Every candidate was queried; no KPI rows for: CCL00003_ab_1 (reported as missing)).
- Program-generated from the run's State; the model wrote none of it. A run ended by a cap keeps every unresolved item below as unknown.

```
OUTAGE IMPACT REPORT
Case: CCL00001, planned outage 2026-02-10T09:00:00Z to 2026-02-10T12:00:00Z
Outage sectors observed: CCL00001_aa_1, CCL00001_ab_1 (whole site down: no sector of it is a backup)
Completion: boundary check complete; CCL00001_aa_1: 6 of 12 directions closed, 0 open, 6 open at the study-area edge; CCL00001_ab_1: 5 of 10 directions closed, 0 open, 5 open at the study-area edge
Evidence: 80 locations fetched, 57 with samples; coverage threshold -110 dBm; signal margin 10 dB; load limit 80% PRB.

1. Where service is lost or degraded (locations where an outage sector covers at or above the threshold)

   area                             covered      loss    signal  capacity      both    backup   unknown
   S1 (Ashford village)                  21        15         2         0         4         0         0
   S2 (Bramble hamlet)                    1         0         0         1         0         0         0
   road_H1 (primary road H1)             24        10         6         6         2         0         0
   total                                 46        25         8         7         6         0         0

   S1 (Ashford village): 71% of the covered locations lose connection entirely (15 of 21), in 3 groups, in the north and west and south-east parts of the area. 10% of the covered locations may degrade by signal (2 of 21), in 2 groups, in the north-west part of the area. 19% of the covered locations may degrade by signal and capacity (4 of 21), gathered in the east part of the area.
   S2 (Bramble hamlet): 100% of the covered locations may degrade by capacity (1 of 1), gathered in the west part of the area.
   road_H1 (primary road H1): 42% of the covered locations lose connection entirely (10 of 24), scattered across the corridor. 25% of the covered locations may degrade by signal (6 of 24), in 3 groups, in the west and centre and north-west parts of the corridor. 25% of the covered locations may degrade by capacity (6 of 24), gathered in the east part of the corridor. 8% of the covered locations may degrade by signal and capacity (2 of 24), gathered in the east part of the corridor.

2. Why: per backup cell
   CCL00002_aa_1: strongest living backup at 11 locations (32% of covered locations). Signal: adequate at 7; weaker than the outage sector by more than 10 dB at 3; below -110 dBm at 3. Load: baseline PRB 41%, estimated after transfer 86%; limit 80%: exceeded.
   CCL00003_ab_1: strongest living backup at 6 locations (18% of covered locations). Signal: adequate at 0; weaker than the outage sector by more than 10 dB at 1; below -110 dBm at 6. Load: whether service degrades cannot be assessed because the historical load data of CCL00003_ab_1 is missing.
   CCSN000004_aa_1: observed but not an eligible backup, or never the strongest living backup at a covered location.

3. Total loss, by location
   S1: grid 167, 168, 170, 171, 187, 189, 191, 207, 209, 227, 229, 230, 231, 249, 250
   road_H1: grid 189, 191, 204, 206, 207, 209, 227, 229, 230, 231

4. What this report does not establish
   - S1: 9 locations with missing data; coverage there is unknown.
   - S2: 4 locations with missing data; coverage there is unknown.
   - road_H1: 18 locations with missing data; coverage there is unknown.
   - CCL00001_aa_1, north 0-30 deg: covered to 255 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_aa_1, north-east 30-60 deg: covered to 354 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_aa_1, south-east 120-150 deg: covered to 292 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_aa_1, south-east 150-180 deg: covered to 158 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_aa_1, south 180-210 deg: covered to 0 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_aa_1, north-west 330-360 deg: covered to 255 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_ab_1, south-east 150-180 deg: covered to 158 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_ab_1, south 180-210 deg: covered to 0 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_ab_1, south-west 210-240 deg: covered to 292 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_ab_1, south-west 240-270 deg: covered to 255 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - CCL00001_ab_1, north-west 330-360 deg: covered to 255 m; no activity location beyond inside the study area; expand the study area to close this direction.
   - Counts are analysis grid locations, not users or traffic; land use is not demand.
```

## KPI baseline

KPI baseline (same weekday and hours, 4 prior weeks):
- CCL00001_aa_1: MEAN_PRB_USED mean 35 over 4 prior weeks (12 samples)
- CCL00001_ab_1: MEAN_PRB_USED mean 28 over 4 prior weeks (12 samples)
- CCL00002_aa_1: MEAN_PRB_USED mean 41 over 4 prior weeks (12 samples)

## Provenance

- real_obs_01: query_area_coverage area S1; success; file artifacts/step_01_S1.json
- real_obs_02: query_area_coverage area road_H1; success; file artifacts/step_02_road_H1.json
- real_obs_03: query_area_coverage area S2; success; file artifacts/step_03_S2.json
- real_obs_04: query_lte_rrc_prb; success; file artifacts/query_kpi_step_04.csv
