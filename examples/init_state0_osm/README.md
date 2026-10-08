# State 0 example from real OpenStreetMap data

The rendering ends with a scope instruction: the model does not have to resolve
every unknown; it names the areas it leaves unqueried in its finish decision and
the program accepts the stop under the three completion rules. The unknowns are
rendered as grouped facts, not as a list of tasks.

A hypothetical rural site in Vermilion County, Illinois (lat 39.95, lon -87.95),
with a 30 km x 30 km initial window, built with the initialization rules of the
outage harness. Only OpenStreetMap is real; the cell id, outage time and the
"rural" environment class stand in for what `cell.lookup` returns. No coverage is
read and no model is called.

| File | Content |
| --- | --- |
| `overpass_query.txt` | the Overpass query: places, land use, water, major roads inside the window |
| `osm_raw.json` | the Overpass answer, 3,433 objects (5.6 MB) |
| `build_state0.py` | the initialization rules and the build; standard library only, `python3 build_state0.py` |
| `state_00.json` | State 0 without grid ids: task, site, study-area rule, grid, geography, 64 areas, 43 relations, 64 zero-queried region summaries, unknowns, data version |
| `areas_grid_ids.json` | area id to grid ids (90,000 locations) |
| `context_state_00.txt` | the text the model reads before its first decision |
| `map_state_00.svg`, `.png` | the window for people |
| `osm_raw_iowa_sparse.json`, `overpass_query_iowa.txt` | a first attempt in Keokuk County, Iowa: 537 objects, no mapped farmland at all; kept to show how sparse rural OSM land use can be |

## The rules, as declared in the script

| Rule | Value | Note |
| --- | --- | --- |
| initial window | rural: 30 km square centered on the site | a table keyed by environment class; other classes unset on purpose |
| grid | 100 m spacing, origin at the window's south-west corner, equirectangular local metres | spacing equals the coverage heatmap resolution of the first scan |
| settlement area | disc around the mapped place node: city 3 km, town 2 km, village 1 km, hamlet 500 m | OSM places here are nodes, not polygons |
| road corridor | centerline buffer, full width by class: motorway 400 m, trunk/primary 300 m, secondary 200 m; a route needs at least 50 locations to be its own area | grouped by `ref` or name |
| blocks | 5 km squares tiling the window, 36 of them, described by the mapped land-use shares inside | the remaining area, so the areas tile the window |
| land-use label | one per grid cell from a closed vocabulary; precedence settlement > industrial_commercial > water > forest > farmland > grassland > unmapped | the original OSM tag is kept on each object |
| relations | corridor crosses settlement; block contains part of settlement, each with the overlapping grid-cell count | |

## What the real data showed

- 69,791 of 90,000 grid cells are mapped farmland; 15,046 are unmapped. The
  unmapped cells sit in the south-east corner, where the neighbouring county has
  no land-use mapping. "Unmapped" is therefore a real label with real extent.
- Settlements come as place nodes without polygons; a radius rule is needed to
  turn them into areas. Residential polygons exist (306) but do not match place
  nodes one to one.
- Of 18 named routes only 6 are long enough to be corridors; IL 49 resolves to
  633 locations, the county roads to 64 to 133.
- The Iowa attempt returned no farmland polygons in a 30 km square, only water
  bodies and roads. The same rules would produce 36 blocks labelled unmapped.
