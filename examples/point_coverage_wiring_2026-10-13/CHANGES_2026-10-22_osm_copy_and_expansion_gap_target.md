# Changes of 2026-10-22: the reused OSM payload is copied into the run; the expansion gap targets a direction

All three packages. Two harness defects from run
`ARL02850_rendered_repeat_off_20261019`, which ended as `rejection_cap`
after a KPI query was rejected for a path reason and two expansion
proposals were rejected for their gap target.

---

## 1. Why

**The KPI rejection.** With `--reuse-osm`, the initialisation observation
references the earlier run's raw OSM file by its original path. KPI
validation (`collect_observed_cell_ids` in `policy.py`) walks every
observation's file reference through `_run_path`, which confines paths to
the current run directory, and raised on the reused reference before it
reached the CSV filter. The confinement is right: a run must not read
outside itself. The reuse is wrong: a payload taken from another run must
become a file of this run. So initialisation copies it in and references
the copy; nothing in validation changes.

**The expansion rejection.** The model put the direction label in
`gap.targets`, which is the natural target of an expansion: the question is
about that direction. The gap check accepts only area ids and seen cell
ids, so it rejected the decision, and its message said what the target
was not, without saying what it could be. The model repeated the same
decision. Under the rule that a rejection names the wrong thing and the
right things, the fix is to accept the direction label as the target of an
expansion (an outage sector id stays accepted too) and to name both
choices in the message.

The Overpass failure in round 12 was a tool error, recorded as such, not a
rejection; it stands. Three consecutive rejections ending the run is the
designed outcome of a stuck model and also stands; with the two fixes the
sequence cannot recur for these reasons.

---

## 2. `initialize_case.py`: copy the reused payload into the run

In `initialize_state0`, find the `else:` branch that handles
`reuse_landuse_artifact`:

```python
    else:
        artifact = reuse_landuse_artifact.resolve()
        collection = _read_json(artifact)
        payload = collection
        if "elements" not in payload:
            raw_path = collection.get("raw_osm_file")
            if not raw_path:
                raise ValueError("Reuse requires raw overpass features, not a land-use-only GeoJSON")
            payload = _read_json(Path(raw_path))
```

Replace it with:

```python
    else:
        artifact = reuse_landuse_artifact.resolve()
        collection = _read_json(artifact)
        payload = collection
        source_path = artifact
        if "elements" not in payload:
            raw_path = collection.get("raw_osm_file")
            if not raw_path:
                raise ValueError("Reuse requires raw overpass features, not a land-use-only GeoJSON")
            source_path = Path(raw_path).resolve()
            payload = _read_json(source_path)
        # A payload from another run becomes a file of this run: every observation reference
        # must stay inside the run directory, and validation confines paths to it.
        artifacts_dir = output_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        copied = artifacts_dir / "osm_landuse_initialization.raw.json"
        copied.write_text(json.dumps({**payload, "reused_from": source_path.as_posix()}, allow_nan=False), encoding="utf-8")
        artifact = copied
```

Then, in the `summary = {...}` dict of that branch, the `output_file` and
the provenance read:

```python
        summary = {
            "status": "success", "tool": "query_osm_landuse",
            "output_file": artifact.as_posix(), "row_count": len(payload["elements"]),
            "columns": [], "source": "saved_openstreetmap_artifact",
            "details": {"reused_from": source_path.as_posix(), "raw_osm_file": artifact.as_posix()},
        }
```

(`artifact` is now the copy inside the run.) The bounding-box check of
the branch stays as it is. Add `import json` at the top of the file if it
is not there.

Check: a run started with `--reuse-osm` has
`artifacts/osm_landuse_initialization.raw.json` in its own directory, the
initialisation observation's `output_file` points at it, and a later KPI
query is not rejected for a path reason.

---

## 3. `gap_checks.py`: the expansion's gap target is a direction or an outage sector

### 3a. The result kind

In `RESULT_KIND`, make sure the entry exists:

```python
    "expand_study_area": "expansion",
```

### 3b. Valid targets for the expansion

Find the check that rejects a target as "neither a known area nor a cell
seen" (in `check_gap`, the loop over `targets` that calls `_kind_of`).
Before that loop, add:

```python
    if name == "expand_study_area":
        from .completion_point import edge_open_labels

        labels = edge_open_labels(state)
        outage = set(state.get("outage_cells") or [])
        for target in targets:
            if target not in labels and target not in outage:
                raise GapRejection(
                    "bad_parameter",
                    f'gap target "{target}" is neither a direction open at the study-area edge nor an observed '
                    f"outage sector; for expand_study_area use the direction label "
                    f"({', '.join(labels) or 'none open'}) or one of {', '.join(sorted(outage)) or 'no sector observed'}")
        direction = str(parameters.get("direction"))
        if direction not in targets and not (targets and all(t in outage for t in targets)):
            raise GapRejection(
                "action_cannot_answer_gap",
                f"expand_study_area expands {direction}; its gap targets must name that direction or the outage "
                f"sector it is open for, got {targets}")
        return
```

`parameters` and `targets` are the names `check_gap` already has for the
validated parameters and the gap's target list; `return` skips the
area-or-cell loop, which does not apply to this action.

### 3c. The skill text (all three)

Find the decision-format paragraph, the sentence that begins
"The program reads only gap.targets and rejects a decision when:". In its
list, find the item about coverage or inspection actions and add after it:

```
- an expand_study_area action has a gap target that is neither the direction it expands nor an observed outage sector;
```

---

## 4. Check

1. On the State of round 14 of the failed run, a scripted decision with
   `gap.targets = ["south 180-210 deg"]` and
   `expand_study_area(direction="south 180-210 deg", distance_m=1000)` is
   accepted by the gap check.
2. The same decision with `gap.targets = ["R07"]` is rejected, and the
   message lists the open direction labels and the outage sectors.
3. A run started with `--reuse-osm` reaches a KPI query without a path
   rejection.
