# 14 - Project Retrospective and Refinement Backlog

This document is a practical retrospective on the current `siro` implementation:
what is strong, what is still fragile, and what should be refined before treating the
system as a serious scaled research platform.

It is intentionally operational. The design documents define the desired safety model;
this file records the project-level lessons from implementing Goals 01-12 and the
next work that would make the testbed more robust.

## Current strengths

### The core abstraction is sound

The project keeps one loop across all capability tiers:

```text
proposal -> sandboxed execution -> objective evaluation -> gates -> archive -> memory
```

That uniformity is the main architectural win. Tier 0, Tier 1, and Tier 2 change the
models and governance around the loop, not the lifecycle itself. This keeps lowering
capability tiers a config change instead of a code fork.

### Safety boundaries are explicit

The implementation has concrete boundaries rather than only policy language:

- Candidate execution runs in a sandboxed execution plane.
- Model-backed agents stay in the control plane.
- Candidate code does not receive model clients or credentials.
- Agent tools are control-plane-only helpers, not raw shell or network tools.
- Frontier-provider egress goes through an allowlist check.
- Promotion goes through gates, not model self-judgment.

This is the right direction for a self-improving system: the model can propose, but the
controller decides what is run, what is scored, and what can promote.

### Auditability is first-class

The project consistently records:

- Attempts, including failures and negative results.
- Model calls and estimated spend.
- Memory entries.
- Meta-change proposals.
- Governance requests, decisions, and revocations.
- Tier 2 model-training artifacts and deployment decisions.

For a research organization, this is more important than raw agent sophistication. It
means failures can become data rather than disappearing into logs or chat history.

### Cheap tests cover most invariants

The test suite uses deterministic scripted model clients to exercise the organization
without network, credentials, or model-server availability. That is a strong testing
shape for this kind of system because it decouples control-plane correctness from model
quality and API availability.

The existing tests already cover important invariants:

- Cross-model review is enforced at Tier 1+.
- Same-provider safety review is refused when cross-model review is required.
- Safety disagreement escalates instead of promoting.
- Budget breaches halt and escalate.
- Hidden research data is not exposed through relative candidate paths.
- Candidate attempts that read environment paths are blocked before execution.
- Governance approvals are default-deny and hash-bound.

## Current weak points

### Documentation drift already appeared

`README.md` had an inconsistent status summary: the detailed implementation section
said Goals 01-12 were implemented, while the earlier goal-map paragraph still said
Goals 10-12 were specs not yet built.

That is a small example of a serious project risk. In this repo, documentation is part
of the contract. When docs drift from implementation, future agents will make wrong
assumptions because they are explicitly told to treat docs as authoritative.

Refinement:

- Keep `README.md` in the same change as any implementation-status change.
- Add a narrow docs consistency check for goal status.
- Consider a small generated status table sourced from a machine-readable manifest.

### Pricing defaults can become stale

The provider pricing table is intentionally an estimate, not billing truth. That is a
reasonable MVP choice, but stale estimates undermine budget gates, run summaries, and
scale planning.

Current public pricing checked on 2026-06-25 differs from the baked-in defaults for at
least some configured models. For example, Anthropic lists Claude Opus 4.8 at lower
standard token prices than the default table currently uses, while OpenAI's GPT-5.4
pricing is also lower than the local default estimate.

Refinement:

- Prefer explicit per-model price overrides in `config/tier1.frontier.yaml` and
  `config/tier2.governed.yaml`.
- Add a `siro pricing-audit` command that reports configured model names, default
  rates, overrides, and last-reviewed dates.
- Treat changing pricing defaults as a docs + config update, not a hidden code tweak.

### Memory enforcement is not yet production-hard

The current guarded sandbox uses a controller-side `ps` RSS poll to detect memory
breaches. That is useful for a local macOS-friendly testbed, but it can miss short
allocation spikes and may not account for process-tree memory correctly.

The full test suite currently exposes this issue: the memory-breach test for governed
scale-up did not raise the expected `BudgetExceeded` on this machine.

Refinement:

- On Linux, enforce memory ceilings with cgroups rather than RSS polling.
- Track process-tree RSS, not only the parent process.
- Keep the current `ps` monitor as a portable fallback, but document it as best-effort.
- Split local portability tests from hard isolation tests that run only on Linux or in
  containers.
- Before any real scale-up, require the hard isolation test suite to pass in the target
  deployment environment.

### JSONL is right for MVP, not enough for production

Append-only JSONL is excellent for readability and early auditability. It is not enough
for multi-worker operation, concurrent writes, querying, access control, retention, or
tamper evidence.

Refinement:

- Keep JSONL export as the human-readable interchange format.
- Add SQLite for local multi-run development.
- Add Postgres for production coordination and reporting.
- Add schema migrations and validation on read.
- Add run IDs, cycle IDs, lineage IDs, and idempotency keys everywhere.
- Add hash chaining or signed records for governance and artifact ledgers.

### The benchmark suite is still too small

The seeded research suite proves the lifecycle across algorithm, training, and policy
tasks. It does not yet prove that meta-research or frontier-model orchestration is
reliably improving research output.

Refinement:

- Expand each family from one task to many small tasks.
- Add adversarial evaluator-loophole tasks.
- Add noisy metrics that require repeated measurement.
- Add tasks with intentionally misleading visible tests.
- Add tasks where a correct change improves the primary metric but regresses a secondary
  metric.
- Add benchmark holdout splits that are never included in prompts or memory summaries.

### The provider layer needs production behavior

The stdlib HTTP provider layer is good for auditability and offline testability. Before
production, it needs more operational behavior.

Refinement:

- Add retry policy with bounded exponential backoff.
- Classify provider errors into retryable, budget, auth, rate-limit, and policy failures.
- Add provider-specific request IDs to the audit ledger.
- Add per-role concurrency limits.
- Add spend dashboards by provider, model, role, task family, and promotion outcome.
- Add key rotation and explicit secret-source documentation.

### Human governance needs stronger identity

The governance gate is structurally good: default-deny, human verbs only, exact-change
hash binding, expiry, revocation, and single-use approvals. For production, the identity
model needs to become stronger than a free-form `--by` string.

Refinement:

- Require authenticated operator identity.
- Sign approvals and revocations.
- Separate requesters, reviewers, and approvers.
- Add two-person approval for high-risk actions.
- Add policy templates for each governed action type.
- Export governance packets for external review.

## Recommended next milestones

### Milestone A - Hardening pass

Goal: make the implemented Goals 01-12 internally consistent and locally green.

Work:

- Fix README implementation-status drift.
- Refresh pricing defaults or add config-level price overrides.
- Fix or re-scope the macOS memory-breach test.
- Add a pricing audit command or documented pricing review procedure.
- Run and record the full test suite.

Exit criteria:

- Full local test suite passes or has a clearly documented platform-specific exception.
- README and docs agree on goal status.
- Budget estimates are clearly dated and source-backed.

### Milestone B - Benchmark expansion

Goal: make the research suite large enough to detect real improvements and regressions.

Work:

- Add 10-20 tasks per research family.
- Add hidden/adversarial tasks.
- Add repeated-run noise handling.
- Add benchmark summary reports that separate accepted, mixed, and failed results.

Exit criteria:

- `siro summarize-research` is meaningful across families.
- Meta-change A/B tests have enough cases to avoid one-task overfitting.

### Milestone C - Production sandbox prototype

Goal: validate hard resource and network isolation in the target deployment environment.

Work:

- Add a Linux/container sandbox backend.
- Enforce memory with cgroups.
- Block execution-plane network with container/firewall policy.
- Preserve the current local sandbox as the developer fallback.

Exit criteria:

- Hard isolation tests pass in CI or a documented Linux runner.
- Memory and wall-clock breaches are reliably recorded as negative attempts.

### Milestone D - Operational pilot

Goal: run a bounded Tier 1 pilot with actual spend tracking.

Work:

- Run 50-100 frontier cycles against the expanded suite.
- Keep strict per-run and per-day budget ceilings.
- Compare local-model, cheaper frontier-model, and strongest frontier-model performance.
- Report cost per passing attempt, cost per promotion, safety escalation rate, and
  benchmark-family win rate.

Exit criteria:

- The project can answer whether frontier spend buys measurable improvement over local
  Tier 0 for this benchmark suite.

## Bottom line

The project is strongest as a bounded research testbed. The architecture is credible
because it centers objective evaluation, auditability, and explicit governance. The next
step is not broader autonomy; it is harder measurement: more benchmarks, stronger
resource isolation, current pricing, and production-quality operational records.
