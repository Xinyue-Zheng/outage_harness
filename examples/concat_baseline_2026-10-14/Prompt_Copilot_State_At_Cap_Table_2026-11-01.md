# Prompt for Copilot: state-at-cap comparison of two capped runs

Paste the text below to Copilot as is.

---

The rule run and the model run of the 4-site, 17-cell case both ended
`time_cap` at 2 hours. Build one comparison table from the two run
directories (run.json, step records, geometry, pictures). Read stored
files only; do not rerun anything, do not change code, do not read the
ground truth. One column per core. Every value names the file and field
it comes from. If a field is missing, write "missing: <field>" in the
cell; do not estimate.

Rows, in this order:

1. Time split, seconds: program, decision, coverage, KPI, OSM, idle,
   total. State whether the six parts sum to total.
2. Resources at the cap: locations charged, KPI executed calls and
   cell-queries, rounds, rejected rounds, and rejections by validation
   check.
3. Progress toward completion: per site, bins closed out of 12; open
   items by kind (inside, beyond, KPI); the floor's minimum locations to
   close at the last round.
4. Rate and shortfall: locations per minute excluding program time;
   the minutes each core would need for the floor at that rate. Mark
   this row as an estimate from the run's own rate.
5. Allocation: locations per site; per area and pattern (top ten areas
   by locations, the rest summed); the round at which each site first
   received a coverage query; sites that never received one.
6. Partial answer: observed backup cells with a fetched baseline,
   observed without one; whether the PRB map has content; the round of
   the first KPI call and the round the first backup cell appeared.
7. Decision cost (model column only): decision calls, total_s median
   and p95, ttft_s median and p95 or "not streamed", output_tokens and
   reasoning_tokens median and p95 or "not reported", retries total,
   context_chars median and maximum, and context_chars per round against
   the number of sites with open items at that round (give the two
   series, not a correlation).
8. Pictures: file names of the three pictures per run and the margin
   line of each.

After the table, write at most ten lines: which of the six time parts is
largest in each column, whether any site never received a query, and
whether the KPI accounting counted rejected calls (say how you checked).
No recommendations.
