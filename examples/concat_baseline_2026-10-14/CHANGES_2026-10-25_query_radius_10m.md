# Change of 2026-10-25: the point API serves a 10 m radius only

Applies to the three packages. The 100 m radius is no longer available
from the point coverage API; every call uses 10 m.

## Why

The tool still offers the model `[4, 10, 100]`, so a run can spend
rounds on calls the API rejects, and the skill text tells the model to
choose the radius by the question. Both must go. The rule policy and the
ring probe already use 10, and the point cache key includes the radius,
so results fetched at 100 m are never reused by mistake.

## Edits

1. `runner_point_nodes.py`: `AREA_RESOLUTIONS = (10,)` and, in
   `QUERY_AREA_COVERAGE`, `"resolution": {"type": "number", "enum": [10]}`.
   The check in `validate_action` stays as it is. In the concat package,
   the `allowed_resolutions` passed to the parser becomes `(10,)`.
2. `synthetic_case.py`: the same enum `[10]` in the tool list.
3. `investigation_skill.txt` and `investigation_skill_rendered.txt`:
   delete the sentence that starts "The resolution values the coverage
   tool accepts" and the sentence "Choose the radius by the question ...
   the locations of an area." Replace them with one sentence: "Each
   location call returns the samples within 10 m of the grid cell centre;
   a location with no sample is unknown, not uncovered." The rest of the
   paragraph stays.
4. Nothing changes in `point_coverage.py`: `valid`, `missing` and `error`
   per location already separate a point with samples from one without,
   and `locations_missing` is already in the summary. Check that the
   rendered context prints the missing count for every area next to the
   covered count, and that an unobserved direction (ring probe change)
   is decided by the absence of sampled points, not by the absence of
   covered points; a direction whose probe points all returned no sample
   is unobserved.

## Check

A run offers only `resolution: 10` in the action list; a decision with
100 is rejected with the message naming `[10]`; the progress block of
every area shows `missing` next to `covered`; `calls.json` keys read
`...|10|...`.
