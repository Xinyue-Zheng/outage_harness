# Copilot baseline: changes to `SKILL.md`

Three edits. They replace the outage prefix rule with exact down cell
IDs. Make each edit in the workspace copy and in the package copy of
`SKILL.md`.

## 1. In "What the data means"

Replace this bullet:

```
- A cell ID with three letters and five digits is LTE; with four
  letters and six digits it is NR. Every observed cell that matches a
  supplied outage prefix is an outage cell and is never a backup. An
  LTE outage cell has LTE backups only; an NR outage cell has NR
  backups only.
```

with these two bullets:

```
- The outage cells are exactly the down cells that the case lists, and
  no others. An outage cell is never a backup. Another cell of the same
  site that the case does not list stays in service and can be a
  backup.
- A cell ID with three letters and five digits is LTE; with four
  letters and six digits it is NR. An LTE outage cell has LTE backups
  only; an NR outage cell has NR backups only.
```

## 2. In "Purpose"

Replace this sentence:

```
A cell site is planned to go down. From stored measurements, find:
```

with:

```
Some cells are planned to go down. The case lists them. From stored
measurements, find:
```

## 3. In the header, the `description` line

Replace the start of the line:

```
description: Investigate where a planned cell site outage removes service,
```

with:

```
description: Investigate where a planned outage of cells removes service,
```

The rest of the line stays as it is.

## Also check the server

The skill only describes the rule. The classes come from the MCP
server. Confirm that the server passes the exact down cell IDs to the
classification function, with no prefix match.
