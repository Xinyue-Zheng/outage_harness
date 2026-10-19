# Changes of 2026-10-21: offer expansion only when a direction is open at the edge; name the action in every open item; reuse the saved OSM payload across packages

All three packages. Every step starts with why, then the edit.

---

## 1. Why

Run `ARL02850_rendered_kpi_fixed_20261019` ended as `rejection_cap`: in
rounds 12 to 14 the model proposed `expand_study_area` for directions that
were open inside the study area (unqueried activity within the observed
reach), not open at the edge, and repeated the proposal after two
rejections. Three things let that happen:

- The action was offered. `expand_study_area` was in the action list
  whether or not any direction was open at the edge. The registry design
  says an action is offered only when its precondition holds in the State;
  this action had no precondition.
- The open items did not name the action. An open direction said "R13 has
  221 locations in this direction not fetched"; the edge line said
  "expand the study area". A weak model read both as "expand".
- The rejection named the wrong thing but not the right one: "direction
  must be one of the directions reported open at the study-area edge:
  none". The design rule for rejections is to name the wrong thing and the
  right things. Here the right things were two coverage queries.

The rejection cap itself did its job: a model that repeats an invalid
action three times is stuck, and ending the run is the correct outcome.
The cap stays at three.

The concat run failed at initialisation, in the OSM fetch, with a
certificate hostname mismatch and 5xx responses from the public Overpass
servers. The code is identical across packages; the service is not. For
the comparison this is also a flaw in the design of the runs: the three
packages should start from the same State 0, which they only do if they
share the same OSM payload. So the concat and concat_checked runs reuse the
rendered run's saved payload, and the fetch happens once per case.

---

## 2. Precondition: `expand_study_area` is offered only with an edge-open direction

### 2a. The registry entry (`runner_point_nodes.py`, where `EXPAND_STUDY_AREA` is declared)

Find the declaration dict of `expand_study_area` and add one key:

```python
    "precondition": "edge_open_direction",
```

### 2b. The precondition test (`completion_point.py`)

Add after `unmet_required`:

```python
def edge_open_labels(state: dict[str, Any]) -> list[str]:
    """Direction labels open at the study-area edge for some outage sector, from the last check."""
    checks = state.get("completion_checks") or {}
    sectors = ((checks.get("boundary") or {}).get("sectors") or {})
    return sorted({r["label"] for s in sectors.values() for r in s["bins"].values() if r["status"] == "open_at_edge"})
```

### 2c. The offer (`context_builder.py`, `_action_lines`; `context_builder_concat.py`, the tool list)

Why: the model must not see an action it cannot take. In the rendered
builder, find the loop that renders one line per declared tool in
`_action_lines`. Before the line is appended, add:

```python
        if tool["name"] == "expand_study_area" and not edge_open_labels(state):
            continue
```

with `from .completion_point import edge_open_labels` in the imports. In the
concat builder, where the tool declarations are serialised into the system
message, the list is fixed for the run (the prefix is cached), so the
concat model keeps seeing the tool; the rejection in 2d then names the
right action. That is a difference between the two inputs, and it is a
property of the transcript design, not something to patch.

### 2d. The rejection names the right actions (`runner_point_nodes.py`, `validate_expand_study_area`)

Find the rejection raised when the direction is not open at the edge (the
message that ends with "open at the study-area edge: none" or lists the
labels). Replace it with:

```python
    if label not in open_labels:
        checks = state.get("completion_checks") or {}
        sectors = ((checks.get("boundary") or {}).get("sectors") or {})
        to_fetch = sorted({r["closing_area"] for s in sectors.values() for r in s["bins"].values()
                           if r["status"] == "open" and r.get("closing_area")})
        hint = (f"; the open directions need coverage queries, not expansion: query_area_coverage for "
                f"{', '.join(to_fetch)}" if to_fetch else "; no direction is open at all")
        raise ValueError(f"{label} is not open at the study-area edge; directions open at the edge: "
                         f"{', '.join(open_labels) or 'none'}{hint}")
```

`open_labels` is the list the function already computes (2b gives it a
name; use `edge_open_labels(state)`).

### 2e. Every open item names its action (`completion_point.py`, `progress_lines`)

Find the line that renders an open direction:

```python
                    lines.append(f"  {cell}, {r['label']}: {reach}; {r['reason']}.")
```

Replace with:

```python
                    area = r.get("closing_area")
                    action = (f" Next action: query_area_coverage(area_id={area})." if area and "not fetched" in r["reason"]
                              else " Next action: query_area_coverage for the area named." if "not fetched" in r["reason"]
                              else "")
                    lines.append(f"  {cell}, {r['label']}: {reach}; {r['reason']}.{action}")
```

The edge line already ends with "expand the study area in this direction
(expand_study_area)". The two kinds of open item now each name a different
action in the same form.

### 2f. The skill text (all three)

Find the sentence that introduces the expansion action (added on
2026-10-19; it begins "A direction open at the study-area edge"). Append:

```
expand_study_area applies only to a direction the progress block marks "open at the edge"; a direction marked open with an area named needs query_area_coverage of that area. The action list offers expand_study_area only when some direction is open at the edge.
```

---

## 3. Reuse the saved OSM payload (`run_case.py`, `langgraph_runner.py`)

### 3a. The option

In `run_case.py`, `_arguments`, add:

```python
    parser.add_argument("--reuse-osm", type=Path, default=None,
                        help="Raw Overpass payload (osm_landuse.raw.json) of an earlier run of the same site; "
                             "initialisation reads it instead of calling Overpass, so every package starts "
                             "from the same State 0")
```

and pass it through: in the `run_case_langgraph(...)` call add
`reuse_landuse_artifact=arguments.reuse_osm,`.

### 3b. The runner

In `langgraph_runner.py`, `run_case_langgraph`, add the keyword
`reuse_landuse_artifact: Path | None = None` after `point_query`, and
pass it to the graph builder: `build_investigation_graph(..., reuse_landuse_artifact=reuse_landuse_artifact)`.
In `build_investigation_graph` add the same keyword, and in
`initialize_node` find:

```python
            case_state, initial_observations = initialize_state0(
                case_state["task"], client, output_dir,
            )
```

Replace with:

```python
            case_state, initial_observations = initialize_state0(
                case_state["task"], client, output_dir, reuse_landuse_artifact=reuse_landuse_artifact,
            )
```

`initialize_state0` already accepts the keyword and checks that the saved
payload's bounding box covers the study square. The observation it records
says `source: saved_openstreetmap_artifact`, so provenance stays honest.

### 3c. How to run the three packages on one case

```
python -m outage_harness_langgraph.run_case --condition rendered ... --output runs/ARL02850_rendered
python -m outage_harness_codex_state.run_case --condition concat ... \
    --reuse-osm runs/ARL02850_rendered/artifacts/osm_landuse.raw.json --output runs/ARL02850_concat
python -m outage_harness_concat_checked.run_case --condition concat_checked ... \
    --reuse-osm runs/ARL02850_rendered/artifacts/osm_landuse.raw.json --output runs/ARL02850_concat_checked
```

(The raw payload path is the `raw_osm_file` named in the rendered run's
`osm_result.json`; use that path if it differs.) Expansion wedges still
call Overpass, because their boxes are new; they go through the same
fetcher with its retries.

---

## 4. Check

1. On the State of round 12 of the failed run (`steps/step_12/state_before.json`),
   the rendered context's action list has no `expand_study_area`, and the
   progress block's open lines end with "Next action: query_area_coverage(area_id=R13)"
   and "(area_id=S06)".
2. A scripted `expand_study_area` decision on that State is rejected with
   the message that names the two coverage queries.
3. A concat run started with `--reuse-osm` has `state_00.json` identical to
   the rendered run's in `geography.areas` (same ids, same `grid_count`),
   and its `init_obs_02` result says `saved_openstreetmap_artifact`.
