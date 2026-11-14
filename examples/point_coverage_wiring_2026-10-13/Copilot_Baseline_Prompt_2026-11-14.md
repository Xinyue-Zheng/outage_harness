# Copilot baseline: the prompt

Paste the text in the box into the Copilot chat (agent mode, only the
`outage-baseline` tools enabled). Fill in the case and the limits first.
They must equal `case.json` in the run folder. The server enforces the
limits of `case.json`; the prompt only tells the agent what they are.

```
Use the outage-investigation skill and the tools of the
`outage-baseline` MCP server.

Case: a planned outage of cells.
- Down cells: <exact cell IDs, comma separated>. Only these cells are
  down.
- Planned outage interval: <start> to <end>, <time zone>

Limits of this run:
- Coverage: <n> locations
- KPI: <n> cell-queries
- Time: <n> seconds from your first tool call
- Tool calls: 200

The tool `get_case` returns the down sites and the KPI baseline
windows.

Investigate the case as the skill describes, and submit the report.

This run is unattended. Do not ask a question and do not wait for an
answer. Before each tool call, write one line: what you want to learn,
and why this call answers it. After the report is accepted, reply with
your summary and stop.
```

Send it once and type nothing else.
