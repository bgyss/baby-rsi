# 11 — Risks and Controls

Risks below apply at every tier. The final section adds risks that appear only once frontier providers and network egress are introduced (Tier 1+); see also `08_frontier_prototype_architecture.md`.

## Risk: Reward hacking

The system may find ways to improve the score without solving the task.

Controls:

- Hidden tests
- Locked evaluator files
- Metric diversity
- Reproducibility checks
- Human review of surprising wins

## Risk: Evaluation contamination

The candidate may gain access to hidden test data or alter the evaluation setup.

Controls:

- Separate candidate workspace from evaluator workspace
- Read-only evaluator mounts
- Artifact hashing
- Diff scanning

## Risk: Unsafe autonomy expansion

The system may attempt to gain broader permissions, longer runtime, or network access.

Controls:

- Static policy checker
- Tool allowlists
- Subprocess timeouts
- No network by default
- Human approval for permission changes

## Risk: Scientific overclaiming

The system may generate persuasive but unsupported interpretations.

Controls:

- Require metric tables
- Require reproduction commands
- Label uncertainty
- Preserve failed runs
- Separate Interpretation Agent from Evaluation Agent

## Risk: Local optimum collapse

The system may repeatedly exploit one narrow strategy.

Controls:

- Maintain population diversity
- Track novelty
- Use multiple task families
- Penalize duplicate hypotheses
- Periodically sample from failed-but-interesting ideas

## Risk: Meta-process corruption

The system may modify its own prompts, memory retrieval, or experiment selection in ways that degrade reliability.

Controls:

- Treat meta-changes as high-risk
- Require A/B testing
- Require rollback plans
- Require human approval for durable meta-changes

## Risk: Expensive runaway experiments

The system may loop indefinitely or consume too much compute.

Controls:

- Fixed budgets
- Maximum generations
- Queue quotas
- Cost accounting
- Human approval for budget tier escalation

## Frontier-provider risks (Tier 1+)

These appear only when agents are backed by frontier APIs and the control plane has network egress.

### Risk: Prompt injection

Untrusted task content, retrieved memory, or tool output may try to steer an agent into unsafe actions.

Controls:

- Treat all retrieved/tool content as data, never as instructions.
- Keep credentials and high-permission tools off agents that read untrusted content.
- Constrain action space with structured outputs and a fixed control-plane tool set.

### Risk: Data exfiltration via API calls

The control plane can reach the network, creating an outbound channel.

Controls:

- Egress allowlist to model-provider endpoints only; deny by default.
- Never put secrets, full datasets, or evaluator internals in prompts.
- Log every outbound model call to the audit ledger.
- No credentials or network handles in the execution plane.

### Risk: Persuasive overclaiming

Frontier models produce convincing prose that may outrun the evidence.

Controls:

- Objective evaluator is authoritative; models never decide promotion.
- Require metric tables and reproduction commands.
- Separate Interpretation from Evaluation; use cross-model review.

### Risk: Cost runaway

Token spend can loop or spike.

Controls:

- Per-run and per-day token / USD ceilings with halt-and-escalate.
- Per-role model assignment so expensive models are used sparingly.
- Cache identical deterministic calls.

### Risk: Single-model blind spots

One model's failure modes (or reward-hacking tendencies) may go unchecked.

Controls:

- Safety/Evaluation review uses a different provider than implementation.
- Mix providers for hypothesis generation to preserve diversity.
- Treat cross-model disagreement on promotion as an escalation signal.
