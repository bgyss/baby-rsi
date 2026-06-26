# Session Tutorial

Example dialogue for operating `siro` through repo-local skills (Claude Code slash commands
or Codex skills) instead of typing commands. Exact ids and metrics will differ; the control
flow should not.

Both hosts expose the same five workflows: Claude Code as slash commands
([`.claude/skills/`](../.claude/skills/)) and Codex as repo-local skills with the same names
([`.codex/skills/`](../.codex/skills/)). The `/siro-*` notation below is the Claude Code <!-- docs-privacy-allow -->
form; in Codex invoke the same skill by name.

Skills:

| Skill | Use |
|---|---|
| `/siro` | Router and control-plane overview. |
| `/siro-run` | Run an experiment. |
| `/siro-watch` | Read current state. |
| `/siro-govern` | Request or inspect approvals. |
| `/siro-pilot` | Run the bounded pilot. |

Standing rules:

- Tier 0 is default: local, offline, free.
- Money, governance, or durable state changes are previewed with `--dry-run`.
- Approvals are human decisions.
- Results are reported from evaluator/gate records, not model self-assessment.

## 1. Observe

> **You:** How is the research org doing?

The operator uses `/siro-watch`:

```zsh
uv run siro --json summarize-research
uv run siro --json provider-report --model-calls runs/model_calls.jsonl
uv run siro --json list-approvals --status pending
```

Expected response shape:

```text
Suite: algorithm 7/10 promoted, training 6/10, policy 3/10.
Integrity: 0 safety failures, 1 reproducibility failure.
Spend: $0.00.
Pending approvals: none.
Next best action: inspect the policy reproducibility failure or run one policy cycle.
```

## 2. Run A Tier 0 Experiment

> **You:** Try to make `pair_count` faster.

Preview:

```zsh
uv run siro --dry-run run-research tasks/research/algorithm/pair_count \
    --config config/tier0.local.yaml
```

Expected preview:

```text
Command: run-research tasks/research/algorithm/pair_count
Tier: 0
Effects: writes a research attempt archive row
Governance: none
```

Run after confirmation:

```zsh
uv run siro run-research tasks/research/algorithm/pair_count \
    --config config/tier0.local.yaml
```

Expected report:

```text
Outcome: promoted or rejected.
Primary metric: evaluator value and direction.
Gates: safety, reproducibility, hidden data, edit surface.
Archive: row written to runs/research_attempts.jsonl.
```

## 3. Request Governed Compute

> **You:** Run it with a larger compute budget.

Preview:

```zsh
uv run siro --dry-run run-scaled tasks/research/algorithm/pair_count --compute-tier 1
```

If approval is missing, request it:

```zsh
uv run siro request-approval budget_increase \
    --target "pair_count@tier1" \
    --payload '{"experiment":"pair_count","tier":1}' \
    --rationale "confirm the speedup under a larger compute budget"
```

Human approval:

```zsh
uv run siro approve <request_id> --by <operator_id>
```

Run after approval:

```zsh
uv run siro run-scaled tasks/research/algorithm/pair_count --compute-tier 1
```

Expected report:

```text
Outcome: completed or halted.
Ceilings: wall-clock, memory, process count.
Governance: approval id and exact target.
Archive: positive or negative attempt recorded.
```

## 4. Run The Pilot

> **You:** Is frontier spend worth it?

Use `/siro-pilot`:

```zsh
uv run siro pilot-init
uv run siro pilot-run
uv run siro pilot-report
```

If the optional strong-frontier arm is in scope:

```zsh
uv run siro pilot-run --include-conditional
```

Expected report:

```text
Arms: Tier 0, cheap frontier, optional strong frontier.
Evidence: promoted/mixed/failed counts, hidden/reproducibility/safety failures, spend.
Decision: continue, revise, or stop.
Boundary: the report does not authorize scale-up.
```

## 5. Monitor

> **You:** Keep an eye on it.

Use `/siro-watch` on a cadence. Report deltas only:

- new failures
- new pending approvals
- spend crossing a threshold
- safety, hidden-test, or reproducibility regressions
- pilot recommendation changes

## Underlying References

- Commands and flags: [`operating_guide.md`](operating_guide.md)
- Self-improvement bounds: [`13_self_improvement_loop.md`](13_self_improvement_loop.md)
- Safety gates: [`05_evaluation_and_safety_gates.md`](05_evaluation_and_safety_gates.md)
