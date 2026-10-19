# Change of 2026-10-22: drop the repeated-query cap

All three packages. `policy.py` and `run_case.py`.

## Why

`RunGuard` ends a run as `repeated_query` when the same query signature
(tool name plus arguments) is about to run for the second time
(`max_identical_queries = 2`). The guard was written for the heatmap path,
where a repeated query re-downloaded the same rectangle. On the point path
a repeated coverage query costs nothing: every location already in the
coverage table is skipped, and a query that would fetch no location at all
is rejected by validation ("already fully queried") before any call. A
repeated KPI query does cost one tool call, but `apply_kpi` deduplicates
its rows, and the gap check already rejects a KPI query whose cells and
window the State holds ("State already answers a target"). So the guard
no longer protects anything the other checks do not, and it ends runs
that would otherwise continue. The step cap, the time cap, the tool-call
cap and the rejection cap still bound every loop.

The guard stays in the code, switched off by its own `None` value, so an
ablation can switch it back on with one argument.

## 1. `policy.py`, `RunLimits`

Find:

```python
    max_identical_queries: int | None = 2
```

Replace with:

```python
    max_identical_queries: int | None = None   # off: the point path skips fetched locations; validation rejects empty queries
```

`RunGuard.check` already does nothing when the value is `None`
(`if repeat_cap is not None:`). `record_tool_call` keeps counting
signatures into `query_counts`; that record is harmless and useful for the
run log.

## 2. `run_case.py`

Find:

```python
    parser.add_argument("--repeat-cap", type=int, default=2)
```

Replace with:

```python
    parser.add_argument("--repeat-cap", type=int, default=None,
                        help="End the run when a query signature repeats this many times; off by default")
```

The `RunLimits(... max_identical_queries=arguments.repeat_cap ...)` line
stays; it now passes `None` unless the option is given.

## 3. Check

In each package:

```
python -c "from <pkg>.policy import RunLimits; print(RunLimits().max_identical_queries)"
```

prints `None`. A run in which the model repeats a coverage query of a fully
fetched area ends with that step rejected ("already fully queried"), not
with `end_reason: repeated_query`; three such rejections in a row still end
the run as `rejection_cap`.
