# Change of 2026-10-28: faster and resumable runs

Applies to the three packages and to `make_ground_truth.py`. Every step
starts with why, then the edit.

## 1. Why

A run spends almost all its time in point API calls, one per location,
made one after another, each with a long timeout; a ground-truth site is
thousands of them. A run that breaks part way starts again from nothing,
because fetched locations live only in that run's State. Two changes
address both: a per-site cache of point results shared by every run and
every pass, and parallel calls with short timeouts and retries. A third
makes every step of the ground-truth script restartable.

Nothing here changes what is fetched or what is reported. The cost figures
(locations fetched, point calls) keep their meaning: a cache hit is counted
separately from a call.

---

## 2. `point_coverage.py`: a per-site point cache

### 2a. Constants

After `PROBE_AREA_ID`, add:

```python
POINT_CACHE_NAME = "point_cache.jsonl"   # per site, under the results root, shared by every run of that site
POINT_WORKERS = 8                        # concurrent point calls; lower it if the API rate-limits
POINT_TIMEOUT_S = (10, 60)               # connect, read; was (15, 300)
POINT_RETRIES = 2
```

### 2b. The cache

Add after `grid_center`:

```python
def point_cache_path(run_dir: str | Path) -> Path:
    """<results root>/<site>/point_cache.jsonl: run_dir is <results root>/<site>/<run name>."""
    return Path(run_dir).resolve().parent / POINT_CACHE_NAME


def load_point_cache(run_dir: str | Path) -> dict[str, dict[str, Any]]:
    path = point_cache_path(run_dir)
    cache: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                cache[record["key"]] = record
    return cache


def append_point_cache(run_dir: str | Path, records: list[dict[str, Any]]) -> None:
    path = point_cache_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, allow_nan=False) + "\n")


def cache_key(grid_id: str, radius_m: float, epoch: str) -> str:
    return f"{grid_id}|{radius_m:g}|{epoch}"
```

The key is the grid location, the radius and the coverage epoch (the
task's `coverage_epoch`, or the outage start date for a ground-truth
run), so two runs of the same site with the same radius share results and
a different radius does not. The file is append-only; a later record for
the same key wins.

### 2c. `fetch_area_points` reads the cache first and writes to it

In `fetch_area_points`, after `to_fetch` is computed, add:

```python
    epoch = str((state.get("task") or {}).get("coverage_epoch") or (state.get("task") or {}).get("start_time", "")[:10])
    cache = load_point_cache(run_dir)
    hits = {g: cache[cache_key(g, radius_m, epoch)] for g in to_fetch if cache_key(g, radius_m, epoch) in cache}
    to_call = [g for g in to_fetch if g not in hits]
```

Replace the fetch loop so it runs over `to_call` only, in parallel:

```python
    with ThreadPoolExecutor(max_workers=min(workers, POINT_WORKERS) if workers > 1 else POINT_WORKERS) as pool:
        fetched = list(pool.map(fetch_one, to_call))
    points = [dict(hits[g]["point"], from_cache=True) for g in to_fetch if g in hits] + fetched
    append_point_cache(run_dir, [{"key": cache_key(p["grid_id"], radius_m, epoch), "point": p}
                                 for p in fetched if p["status"] != "error"])
```

and in `fetch_one`, call the API through a retry wrapper:

```python
        for attempt in range(POINT_RETRIES + 1):
            try:
                samples = query(lat, lon, radius_m)
                break
            except Exception as error:  # noqa: BLE001
                last = f"{type(error).__name__}: {error}"
                if attempt == POINT_RETRIES:
                    return {**record, "status": "error", "samples": [], "error": last}
```

The result summary gains two counts, `cache_hits` and `api_calls`, in its
`details`; `calls.json` and the run log print both. An error point stays
an error point: not cached, left unqueried, as before.

### 2d. The API timeout

In `point_by_point_cover.py`, `timeout=(15, 300)` becomes
`timeout=POINT_TIMEOUT_S` imported from `point_coverage`. A call that
takes longer than 60 s is retried, then recorded as an error; the run
continues.

---

## 3. OSM: cache by bounding box

In `osm_landuse.py`, `query_osm_landuse`, before the tiled requests: if a
file `<results root>/<site>/osm_cache/<min_lng>_<min_lat>_<max_lng>_<max_lat>.raw.json`
exists, read it instead of calling Overpass, and write the raw payload
there after a successful call. The bounding box in the name is rounded
to five decimals. An expansion wedge or a window enlargement with the same
box is then free on the second run.

---

## 4. KPI: one call per technology per step

Already the rule in the harness (the one-call line). In
`make_ground_truth.py`, steps 2, 6b and 8 pass every cell of a technology
in one `cell_ids` list, never one cell per call, and cache the rows per
cell and month under `<results root>/<site>/kpi_cache/<cell>_<month>.csv`.

---

## 5. `make_ground_truth.py`: every step restartable

Each step writes its output files only when complete (write to a
temporary name, then rename). On start, the script looks for each step's
output in order and skips a step whose output exists; `--restart` deletes
them and starts over. A broken run is therefore rerun with the same
command and continues from the last complete step, with the point cache
making the repeated step itself cheap. The README records which steps
were skipped as already complete.

---

## 6. Harness runs: resume

In the three packages, `run_case.py` gains `--resume <run dir>`: the
runner reads the last `state_NN.json` and `steps.json`, sets the step
index, and continues the loop. The point cache makes a repeated query
free. `run.json` records `resumed_from`.

---

## 7. Check

1. A ground-truth run interrupted after step 5 and started again with the
   same command skips steps 1 to 5 and finishes; its `calls.json` shows
   `cache_hits` for the repeated locations and `api_calls` only for new
   ones.
2. A harness run of the same site after the ground-truth run shows the
   large majority of its locations as cache hits in `calls.json`, and the
   same coverage entries as a run without the cache.
3. With `POINT_WORKERS = 8`, a 200-location area takes about an eighth of
   the sequential time, unless the API rate-limits, which shows as errors
   in `calls.json`; then lower the constant.
