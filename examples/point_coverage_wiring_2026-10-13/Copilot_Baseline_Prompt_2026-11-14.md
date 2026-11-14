# Copilot baseline: the prompt

Paste the text in the box into the Copilot chat (agent mode, only the
`outage-baseline` tools enabled). Fill in the three values first. They
must equal the case the MCP server uses.

```
Use the outage-investigation skill and the tools of the
`outage-baseline` MCP server.

Case: a planned cell site outage.
- Down cells: <cell IDs, comma separated>
- Outage prefixes supplied: <prefixes>
- Planned outage interval: <start> to <end>, <time zone>

The tool `get_case` returns the KPI baseline windows and the limits of
this run.

Investigate the case as the skill describes, and submit the report.

This run is unattended. Do not ask a question and do not wait for an
answer. Before each tool call, write one line: what you want to learn,
and why this call answers it. After the report is accepted, reply with
your summary and stop.
```

Send it once and type nothing else.
