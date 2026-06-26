---
name: siro-watch
description: Monitoring snapshot for siro from Codex. Use when the user asks for status, health, spend, what's failing, what needs approval, or when you need to read system state before recommending an action. Runs read-only summaries and reports archive health, gate/safety/reproducibility failures, spend vs budget, and pending governance.
---

# Watch siro

A read-only health snapshot. Everything here is safe to run any time and never mutates
state. Use it to answer "how's the system doing?" and to decide what to do next.

## Gather

Run these and read the output. Add the global `--json` flag when you want to parse precise
state rather than prose:

```zsh
uv run siro --json summarize-research
uv run siro --json summarize-runs runs/attempts.jsonl
uv run siro --json provider-report --model-calls runs/model_calls.jsonl
uv run siro --json list-approvals --status pending
```

Drop `--json` for a quick human-readable glance; keep it when you need to compare numbers,
compute deltas across ticks, or drive a decision from exact values.

If a SQLite store is in use, add `--store runs/siro.db` to the summarize commands and run
`uv run siro storage-verify --store runs/siro.db` to confirm the governance/artifact hash
chains are intact.

## Report signal

Summarize into a short status, organized by what the user can act on:

- **Suite health**: accepted/promoted vs mixed vs failed; median cycles to success;
  strategy diversity. Call out families that are stuck or regressing.
- **Integrity failures**: safety-gate, hidden-test, and reproducibility failure counts.
- **Spend**: token + USD totals and cost per promotion vs configured budget ceilings.
- **Pending governance**: list anything awaiting a human decision and route to `siro-govern`.

Lead with anomalies and deltas. If everything is green, say so in one line.

## Looped monitoring

When asked to watch on a cadence:

- Each tick, gather the read-only summaries and report only deltas since last tick.
- Never act on a human-gated item autonomously: escalate it with the exact request id and
  what it asks for.
- Suggest a concrete next action, usually a `siro-run` or `siro-govern` step, but let the
  user trigger anything irreversible.
