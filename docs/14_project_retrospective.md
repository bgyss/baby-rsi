# 14 - Project Retrospective and Refinement Backlog

This document is a practical retrospective on the current `siro` implementation after
Goals 01-27. It records what the project has actually proven, what remains fragile,
and what should be validated before treating the system as a serious research platform.

The core lesson is stable: `siro` is strongest when it is a bounded, auditable research
organization, not an unrestricted autonomy system. Models propose. The controller runs
fixed actions. Objective evaluators score. Governance decides whether high-risk or
external actions may happen.

## Project Arc

### Goals 01-06: local self-improvement testbed

The first stage established the load-bearing loop:

```text
task -> proposal -> sandbox -> evaluator -> gates -> archive -> memory
```

The loop began with code-improver tasks, then added research memory, promotion gates,
bounded meta-research, and a tiny training search. The important design decision was
that all improvement happens through attempts and archives. Negative results are kept,
promotion is metric-gated, and meta-changes stay reversible.

What worked:

- Typed schemas made attempts, metrics, gates, and ledgers inspectable.
- JSONL archives made early runs easy to audit.
- Scripted model clients let the control plane be tested without network or model spend.
- The execution plane stayed small enough to reason about.

What remains fragile:

- The local sandbox is a developer fallback, not a production isolation boundary.
- Early JSONL-only storage was easy to read but not enough for multi-worker operations.
- Tiny fixtures prove invariants, not research productivity.

### Goals 07-09: provider-agnostic research organization

The second stage generalized from a local loop to a role-based research organization:
Hypothesis, Literature, Implementation, Eval, Safety, Interpretation, and Memory.
The provider abstraction kept model choice in config, and Tier 1 added frontier providers
without giving candidate code network access or credentials.

What worked:

- Role-to-model binding is config-only.
- Budget enforcement and model-call ledgers make spend part of the audit trail.
- Cross-model safety review is a concrete Tier 1 invariant.
- Research tasks use controller-owned evaluators and hidden data.

What remains fragile:

- Provider quality is still mostly tested through scripted clients and small pilots.
- The benchmark suite is broad enough for regression tests, not enough for strategic
  model-selection claims.
- Provider pricing and operational behavior must be refreshed as model catalogs change.

### Goals 10-12: governed scale-up

The third stage added the governance machinery: default-deny approvals, governed compute
scale-up, and governed offline model training. This was the point where the architecture
became more than a local toy: a high-budget or high-risk action can be proposed by the org
but must be authorized by a human-controlled ledger.

What worked:

- Approvals are bound to exact payload hashes.
- Revocation, expiry, and single-use semantics are explicit.
- Higher compute requires a smaller-tier pass plus approval.
- Model deployment is distinct from model training.

What remains fragile:

- Any real scale-up still depends on the target isolation backend and operator process.
- Governance identity became strong only after Goal 19; older records must remain readable
  but should not be treated as production-grade approvals.

### Goals 13-20: hardening and operational evidence

The hardening stage converted several earlier risks into first-class machinery:
documentation checks, pricing audits, hard resource backends, SQLite storage, benchmark
expansion, provider observability, governance identity/policy, and the operational pilot
report.

What worked:

- Documentation drift is now mechanically checked against `docs/goal_prompts/goals.json`.
- Docs path privacy is a repository invariant.
- SQLite adds migrations, idempotency keys, hash-chained governance/artifact records, and
  JSONL import/export while preserving the readable archive path.
- The sandbox backend abstraction separates portable local development from Linux cgroup v2
  hard isolation.
- Provider errors, retries, request metadata, and pricing audits are inspectable.
- The pilot plan can compare Tier 0 and frontier arms by cost per objective promotion.

What remains fragile:

- A production deployment still needs a pinned Linux runner or container environment where
  hard-isolation tests pass.
- The pilot report is only meaningful after real arms have been run with preserved
  attempt/model-call ledgers.
- Cost estimates remain estimates until reconciled with provider dashboards.

### Goal 21: conversational operation

Goal 21 made the CLI operable from Claude Code and Codex without inventing a REPL. The
right abstraction is still the CLI; the host-specific skills are thin operator layers that
read state, dry-run, explain implications, and then call the same commands a human would.

What worked:

- `--json` makes read-only summaries scriptable.
- `--dry-run` makes governance and tier implications visible before side effects.
- Host skills did not bypass the approval model.

What remains fragile:

- Conversational operation is only as safe as the underlying commands and docs.
- Any new command that changes state should get a dry-run path before becoming a
  conversational affordance.

### Goals 22-27: generalization to sciences

The final stage changed the project from "ML/software research testbed" to a domain-pack
research substrate. The central move was to classify domains by evaluator regime:

- `exact`: formal proof or deterministic checker.
- `seeded-deterministic`: offline computation reproducible within tolerance.
- `statistical`: noisy offline evaluator promoted only by a confidence-bound gate.
- `external-oracle`: real-world action ingested through governed external results.

Goal 22 formalized domain packs. Goal 23 added Lean proof search. Goal 24 added the
statistical reproducibility gate. Goal 25 added a chip-design pack. Goal 26 added the
governed external-experiment boundary. Goal 27 added the life-science pack with offline
screening plus governed wet-lab confirmation.

What worked:

- Domain specificity now lives in packs: tasks, evaluator adapter, prompts, references,
  and narrowed tool whitelists.
- The same lifecycle spans ML, math, chip design, and life science.
- The statistical gate preserves the "no promotion on noise" invariant for Regime B tasks.
- External experiments are proposed, approved, executed outside `siro`, and ingested as
  signed, hash-bound results.
- The life-science pack enforces screening-before-confirmation. A candidate cannot jump
  straight from an in-silico score to a wet-lab request.

What remains fragile:

- The life-science evaluator is a toy pinned surrogate, not a scientific model.
- The current wet-lab path is an integration boundary, not a lab automation stack.
- Real assay validation, biosafety, chain of custody, instrument qualification, and data
  integrity are outside the repo and must be owned by qualified humans and institutions.
- External data ingestion proves governance semantics, not scientific truth.

## Current Strengths

### The architecture has one loop

The project avoided separate designs for local code tasks, frontier research, governed
compute, math proofs, chip design, and drug-discovery screening. All of them use the same
proposal, evaluation, gate, archive, and memory lifecycle. This is the main architectural win.

### Safety boundaries are concrete

The implementation has executable boundaries rather than only policy language:

- Candidate execution is offline and credential-free.
- Model-backed agents stay in the control plane.
- Candidate code never receives model clients.
- Agent tools are control-plane helpers, not raw shell or arbitrary network.
- Promotion goes through objective evaluators and gates.
- External actions require governed approval and signed result ingestion.

### Auditability is first-class

The project records attempts, failures, model calls, memory entries, meta-change proposals,
governance packets, pricing metadata, storage hashes, and pilot evidence. That matters more
than a flashy agent demo: a research system that cannot explain failed attempts cannot improve
reliably.

### Domain packs are the right extension point

The pack interface keeps science-specific logic out of the controller. A new domain should be
reviewed as a pack: evaluator regime, tasks, hidden data, prompts, references, tool whitelist,
and promotion policy. A pack that widens the global safety invariants is a contract violation.

## Current Weak Points

### The evidence is mostly structural

The test suite strongly verifies invariants, but it does not yet prove that the organization
regularly discovers valuable improvements. The honest current claim is:

- The machinery, boundaries, and ledgers exist.
- The toy and fixture tasks exercise the intended failure modes.
- Scientific productivity remains unproven until larger benchmark and pilot evidence exists.

### Real deployment is environment-dependent

The portable local backend is useful for development. Production claims require a target
runner where cgroup, process, filesystem, and network isolation are enforced by the platform,
not merely sampled by a controller process.

### The life-science pack is a capstone scaffold

The pack correctly models two-stage drug discovery at an architectural level: offline screen,
then governed confirmation. It does not yet include validated molecular modeling, qualified
assays, real compound logistics, or lab instrument integration. Those should be added only as
governed integrations, not by expanding candidate execution privileges.

### Governance depends on operator discipline

Hash-bound, signed approvals are necessary but not sufficient. Production use needs real
identity management, separation of duties, training, incident response, and external review.
The software can enforce some boundaries; it cannot replace institutional controls.

## Refined Backlog

### Milestone A - clean local release candidate

Goal: make the current 01-27 implementation internally consistent and locally green.

Work:

- Run `mise run check-docs`, `mise run lint`, and `mise run test`.
- Run focused external/life-science tests before any changes to Goals 26-27.
- Confirm README, implementation status, and document map all agree.
- Keep all docs project-relative and privacy-clean.

Exit criteria:

- Full tests pass, or any platform-specific skip/failure is recorded with scope and reason.
- Goal manifest and README both state Goals 01-27 as implemented.
- No accidental personal-machine paths appear in docs.

### Milestone B - benchmark and pilot evidence

Goal: answer whether models and meta-research improve objective outcomes.

Work:

- Run the fixed Goal 20 pilot arms.
- Preserve `research_attempts.jsonl`, `model_calls.jsonl`, config snapshots, and report output.
- Report accepted, mixed, failed, hidden-test, reproducibility, and safety outcomes separately.
- Compare local, cheap frontier, and strong frontier arms by cost per objective promotion.

Exit criteria:

- `runs/pilots/operational-pilot-v1/pilot_report.md` has enough evidence for a continue,
  revise, or stop decision.

### Milestone C - production isolation rehearsal

Goal: prove the deployment substrate enforces the invariants the code assumes.

Work:

- Run the hard-isolation tests in the target Linux/container environment.
- Verify execution-plane no-network policy outside Python.
- Confirm secrets are absent from candidate environments.
- Test wall-clock, memory, process-count, and filesystem breach recording.

Exit criteria:

- Hard isolation passes in the target runner.
- A failed breach is archived as a negative attempt with a clear reason.

### Milestone D - life-science dry run without wet lab

Goal: exercise the full Goal 27 workflow up to, but not including, a real assay.

Work:

- Run the offline screening task with `config/tier0.life_science.yaml`.
- Confirm non-drug-like or unsynthesizable candidates fail before affinity is considered.
- Generate a confirmation proposal only for a screen-clearing candidate.
- Leave the proposal pending; do not approve or ingest fabricated real-world data.

Exit criteria:

- Screening evidence is attached to the pending approval.
- An unscreened candidate cannot create a confirmation request.
- The confirmation adapter reports "awaiting" until a signed result is ingested.

### Milestone E - governed wet-lab integration pilot

Goal: connect `siro` to a qualified external assay process without letting `siro` run the lab.

Work:

- Define a laboratory result schema, operator identity process, and result-signing procedure.
- Map sample IDs, plate IDs, instrument run IDs, and assay batch IDs into the external result
  provenance.
- Run a mock integration with a lab-owned LIMS/ELN or instrument export file.
- Have a human approve one low-risk confirmation proposal.
- Ingest the signed result and verify hash binding, approval status, and audit packet export.

Exit criteria:

- `siro` never receives lab credentials or instrument control.
- A revoked, expired, unsigned, mismatched, or null result refuses promotion and is logged.
- A signed approved result resolves only for the exact candidate and proposal.

## Bottom Line

`siro` is now a coherent bounded research substrate with a credible path from local
experiments to governed external science. The project has implemented the right control
surfaces: plane isolation, objective gates, budget ceilings, provider abstraction, durable
records, governance, domain packs, statistical promotion, and external-oracle ingestion.

The next step is not broader autonomy. It is harder evidence: run the pilot, prove the target
isolation backend, expand benchmarks, and treat any wet-lab integration as a governed,
human-owned external oracle with validated assays and signed results.
