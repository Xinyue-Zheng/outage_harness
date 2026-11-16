# Reply to the Copilot after the `fastmcp` error in the quick results table

Send this in the same chat.

```
Do not import outage_harness_copilot in quick_table.py; its modules need
fastmcp. For a Copilot baseline run, read the record files directly
with json:
- locations and classes from records/reads.jsonl;
- seconds from records/calls.jsonl: the time of the last call plus its
  seconds, minus the time of the first call;
- end_reason: "report submitted" if records/report.json holds an
  accepted report, else "no report".
Then run the tables again.
```
