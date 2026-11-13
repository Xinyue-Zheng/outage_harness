# Reference script: KPI calls that fail with `NonRetryableTlsError` (instruction for the Copilot)

Apply to `outage_harness_evolution/reference.py` and the helpers beside
it. Do not edit a harness package or a concat package. Synthetic tests
only; they write under `tmp_path`. Do not run `uv sync` and do not add
dependencies. Report every change as file and line.

Why. The KPI steps of the reference script fail with
`NonRetryableTlsError`. The setting of 3 attempts does not bound the
failures: the script keeps failing after the third one. Two things can
cause that, and the code decides which. Either the setting counts per
call, and the script goes on to the next cell with the same broken
connection, so every later call fails 3 times as well. Or the client
does not apply the setting to this error class at all. A second risk is
worse than the lost time: if a failed call is stored the same way as a
call that returned no rows, a cell looks like it has no KPI data when it
was never read, and every label that depends on it is wrong.

## 0. Report first, from the code, before any edit

1. Where the reference script calls KPI: the function, how many cells
   one call names, and the window of one call.
2. The setting of 3: its name, file and line, what it counts (attempts
   of one call, or failures in the whole run), and whether
   `NonRetryableTlsError` is excluded from it.
3. Where `NonRetryableTlsError` is defined and raised, which exception
   it wraps, and in which phase it occurs: opening the connection,
   running the query, or downloading the rows.
4. Whether one connection is kept for the whole script or a new one is
   opened per call.
5. What the script writes today for a cell whose call failed, and
   whether any later step can read that as "no rows".

## 1. A failed call is not an empty result

Every (cell, window) the script asks for has exactly one of three
outcomes, as a `Literal`:

| outcome | meaning | stored |
|---|---|---|
| `rows` | the call succeeded and returned rows | the KPI cache, as today |
| `no_rows` | the call succeeded and returned zero rows | the KPI cache, with zero rows |
| `failed` | the call raised after its last attempt | `kpi_failed.json` only: cell, window, error name, attempts, time |

A `failed` cell is never written to the KPI cache and never enters
`kpi_availability.json`, the row share, the outage set decision, the
idle flag or any class. A step that needs a `failed` cell does not run
(part 3).

## 2. Attempts use a new connection

Constants at the top of the module: `KPI_ATTEMPTS = 3`,
`KPI_RETRY_WAIT_S = 30`, `KPI_CONSECUTIVE_FAILED = 3`.

One call gets at most `KPI_ATTEMPTS` attempts. After an attempt that
raises `NonRetryableTlsError`, close the connection, wait
`KPI_RETRY_WAIT_S` times the attempt number, open a new connection, and
send the same call. Never send an attempt on the connection that just
failed. Record the attempts and the error name of each in the call
record. Any other exception keeps today's handling.

If part 0 shows that the client opens a new connection per call
already, keep the wait and the attempt count, and say so in the report.

## 3. The script stops; it does not go on with a dead source

- A call that fails its last attempt is `failed`, and the script goes to
  the next call.
- When `KPI_CONSECUTIVE_FAILED` calls in a row are `failed`, the script
  stops at once with exit reason `kpi_source_down`, naming the three
  calls. Total failures are then bounded by 9 attempts.
- When the KPI step ends with any `failed` call left, the script stops
  with exit reason `kpi_incomplete` and the list. The later steps
  (outage set, backups, classes, report) do not run on an incomplete
  KPI set.
- A rerun asks only for the (cell, window) pairs that have no cached
  outcome. `rows` and `no_rows` are never asked again.

## 4. Smaller calls, only if part 0 shows the cause

If the error occurs while downloading rows, one call names at most
`KPI_CELLS_PER_CALL = 20` cells. If it occurs while opening the
connection or running the query, do not change the call size, and say
so.

## 5. Check what is already written

From the reference outputs that exist, with no new call, write
`kpi_recheck.md`: every cell whose stored KPI record has zero rows,
with whether a call record shows that the call succeeded. A cell with
zero rows and no record of a successful call is listed as `recheck`.
The rerun of part 3 asks for those again. Do not delete anything.

## 6. Tests, with a fake KPI client

1. Two TLS errors, then rows: the outcome is `rows`, the record shows 3
   attempts, and the fake saw 3 different connections.
2. Three TLS errors: the outcome is `failed`; the cell is in
   `kpi_failed.json`, not in the cache and not in
   `kpi_availability.json`.
3. Three calls in a row `failed`: the script stops `kpi_source_down`
   after 9 attempts and makes no tenth.
4. One `failed` call among successes: the script stops `kpi_incomplete`
   after the KPI step, and the class step did not run.
5. A success with zero rows is `no_rows`, is cached, and is not asked
   again on a rerun. A `failed` call is asked again on a rerun.
6. `kpi_recheck.md` on a fixture with one zero-row cell that has a
   success record and one that has none lists only the second as
   `recheck`.

Gate on the changed files: `uv run ruff format`,
`uv run ruff check --fix`, `uv run ty check`.

## 7. Report back

The answers of part 0, the change list, `kpi_recheck.md`, and after the
next real run: the number of calls, the attempts per call, the exit
reason, and `kpi_failed.json` if it exists. If the error appears on the
first attempt of a new process with a new connection, say so: the cause
is then outside the code (proxy, certificate, VPN), and no change here
removes it.
