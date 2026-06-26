---
name: siro-watch
description: Monitoring snapshot for siro — the simple control plane. Use when the user asks for status / health / "how's it doing" / spend / what's failing / what needs approval, or when you need to read system state before recommending an action. Runs the read-only summaries and reports archive health, gate/safety/reproducibility failures, spend vs budget, and pending governance.
---

# Watch siro (monitoring control plane)

A read-only health snapshot. Everything here is safe to run any time and never mutates
state. Use it to answer "how's the system doing?" and to decide what to do next.

## Gather (read-only)

Run these and read the output:

```zsh
uv run siro summarize-research                                # per-family suite health
uv run siro summarize-runs runs/attempts.jsonl               # code-loop archive
uv run siro provider-report --model-calls runs/model_calls.jsonl   # spend / latency / retries / errors
uv run siro list-approvals --status pending                  # outstanding human-gated requests
```

If a SQLite store is in use, add `--store runs/siro.db` to the summarize commands and run
`uv run siro storage-verify --store runs/siro.db` to confirm the governance/artifact hash
chains are intact.

## Report — surface signal, not raw dumps

Summarize into a short status, organized by what the user can act on:

- **Suite health** (per family): accepted/promoted vs mixed vs failed; median cycles to
  success; strategy diversity. Call out families that are stuck or regressing.
- **Integrity failures**: safety-gate, hidden-test, and reproducibility failure counts.
  These are the ones that matter most — a rising count is a real problem, not noise.
- **Spend**: token + USD totals and cost per promotion vs the configured budget ceilings.
  Flag anything approaching a ceiling *before* it halts a run.
- **Pending governance**: list anything awaiting a human decision and route to
  **/siro-govern**.

Lead with anomalies and deltas. If everything is green, say so in one line.

## Autonomous / looped monitoring

This skill is the "monitored via a simpler control plane" surface. When asked to watch on
a cadence (e.g. under `/loop`):

- Each tick, gather the read-only summaries and report **only deltas** since last tick
  (new failures, new pending approvals, spend that crossed a threshold).
- **Never** act on a human-gated item autonomously — escalate it with the exact request id
  and what it's asking for.
- Suggest a concrete next action (usually a **/siro-run** or a **/siro-govern** step), but
  let the user trigger anything irreversible.
