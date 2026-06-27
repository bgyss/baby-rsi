# Self-Improving Research Organization

`baby-rsi` specifies and implements `siro`: a bounded research loop that proposes changes,
runs them in an offline sandbox, scores them with fixed evaluators, records the result, and
uses that memory for the next attempt.

It is a lab-scale system with explicit gates, not an unrestricted autonomy blueprint. Models
propose. The controller runs vetted commands. Humans approve budget, tier, egress, evaluator,
deployment, and other high-risk changes.

## Start Here

```zsh
nix develop        # or: direnv allow
mise install
mise run sync
mise run test

uv run siro --help
uv run siro --json summarize-research
uv run siro --dry-run run-scaled --compute-tier 1
uv run siro run-research packs/ml/tasks/training/tiny_mlp --config config/tier0.local.yaml
uv run siro run-research packs/math/tasks/lemma/add_zero --config config/tier0.math.yaml
```

Canonical interface: `uv run siro ...`. `mise` tasks are thin wrappers.

## Read Next

| Need | File |
|---|---|
| Operate the system | [`docs/operating_guide.md`](docs/operating_guide.md) |
| See a conversational workflow | [`docs/session_tutorial.md`](docs/session_tutorial.md) |
| Per-goal implementation detail | [`docs/implementation_status.md`](docs/implementation_status.md) |
| Core architecture | [`docs/01_system_architecture.md`](docs/01_system_architecture.md) |
| Safety and promotion gates | [`docs/05_evaluation_and_safety_gates.md`](docs/05_evaluation_and_safety_gates.md) |
| Self-improvement contract | [`docs/13_self_improvement_loop.md`](docs/13_self_improvement_loop.md) |
| References | [`docs/12_references.md`](docs/12_references.md) |

Goal prompts live in [`docs/goal_prompts/`](docs/goal_prompts/). They are the staged build
contract and each keeps a `## Self-improvement` section.

## Core Model

```text
task -> propose -> sandbox -> evaluate -> archive -> select -> remember
```

- **Control plane:** orchestrator, agents, model calls, audit ledgers. Network is
  allow-listed to model providers.
- **Execution plane:** candidate and training code. Offline, temp-dir based, bounded, and
  credential-free.
- **Promotion rule:** objective metric improves, required secondary metrics hold, safety
  passes, result reproduces, edit surface is respected.

## Capability Tiers

| Tier | Scope | Network | Governance |
|---|---|---|---|
| 0 | Local/offline machinery | none for candidates | local gates |
| 1 | Frontier-model research org | provider allowlist only | cross-model review |
| 2 | Governed scale-up | provider allowlist only | human approvals |

Tier and pack selection are config-only (`config/tier0.local.yaml`, `config/tier1.frontier.yaml`,
`config/tier2.governed.yaml`, plus pack-specific profiles such as `config/tier0.math.yaml`).
Lowering tier must not require a code change.

## Implementation Status

Goals 01-27 are implemented. Keep this
section grouped by tier; put detailed notes in
[`docs/implementation_status.md`](docs/implementation_status.md).

### Tier 0 — Local Bounded Testbed (Goals 01-06)

- **Goal 01 — Project scaffold** (schemas, archive, safety, evaluator, CLI): typed records,
  JSONL ledgers, plane-isolation primitives, scoring, and command surface.
- **Goal 02 — Code-improver loop** (controller, sandbox): propose, run, evaluate, archive,
  and select code candidates offline.
- **Goal 03 — Research memory** (memory): durable positive and negative records for future
  proposals.
- **Goal 04 — Promotion gates** (gates): code-integrity, safety, reproducibility, and hidden
  tests.
- **Goal 05 — Meta-research loop** (meta): bounded process-change proposals with fixed A/B
  validation and rollback plans.
- **Goal 06 — Tiny-training autoresearch** (training): candidate `TrainConfig` search for a
  fixed pure-Python MLP under a wall-clock budget.

### Tier 1 — Frontier Research Organization (Goals 07-09)

- **Goal 07 — Provider abstraction** (providers, config, budget): local/OpenAI/Anthropic
  clients behind one interface, role binding by config, token/USD ceilings, call ledger.
- **Goal 08 — Frontier research org** (orchestrator, agents, tools): model-backed roles,
  control-plane-only tools, cross-model safety review, config-only Tier 1 to Tier 0 fallback.
- **Goal 09 — Research-shaped task suite** (research, packs/ml/tasks): algorithm, training,
  and policy task families with controller-owned evaluators and hidden-data isolation.

### Tier 2 — Governed Scale-Up (Goals 10-12)

- **Goal 10 — Governance gate** (governance): default-deny approval ledger with requests,
  decisions, revocations, expiry, and exact-change hashes.
- **Goal 11 — Governed compute scale-up** (scale, sandbox): larger compute only after a
  smaller-tier pass plus bound approval; breaches are archived as negative attempts.
- **Goal 12 — Governed model-training** (model_training): bounded offline weight updates
  behind stability checks, `MODEL_TRAIN` approval, and separately approved deployment.

### Cross-Tier Hardening (Goals 13-20)

- **Goal 13 — Documentation consistency contract** (docs_check): manifest-backed README,
  goal-prompt, self-improvement, and privacy checks.
- **Goal 14 — Pricing audit and budget calibration** (pricing): dated price overrides,
  ledger pricing metadata, and `pricing-audit`.
- **Goal 15 — Hard resource isolation backend** (backends): process-group ceilings plus
  optional Linux cgroup v2 enforcement.
- **Goal 16 — Durable research store and query layer** (storage): JSONL default plus opt-in
  SQLite with migrations, dedupe, hash chains, import, and export.
- **Goal 17 — Research benchmark suite expansion** (packs/ml/tasks): broader fixed suite,
  adversarial variants, hidden data, and richer summaries.
- **Goal 18 — Provider operations and observability** (providers/ops): classified errors,
  bounded retries, request metadata, and `provider-report`.
- **Goal 19 — Governance identity and policy hardening** (governance): operators,
  signatures, policy templates, two-person approval, packet export, verification.
- **Goal 20 — Bounded operational pilot and cost-per-promotion report** (pilot): fixed
  Tier 0 vs frontier pilot with budget caps and a continue/revise/stop report.

### Conversational Operations (Goal 21)

- **Goal 21 — Conversational operating interface in Claude Code and Codex**
  ([`.claude/skills`](.claude/skills), [`.codex/skills`](.codex/skills), CLI): host-specific <!-- docs-privacy-allow -->
  repo-local skills drive the non-interactive CLI; global `--json` and `--dry-run` support
  precise summaries and previews without side effects.

### Generalization to the Sciences (Goals 22-27)

See [`docs/18_generalizing_to_sciences.md`](docs/18_generalizing_to_sciences.md) for the
evaluator-regime taxonomy and design rationale behind these goals.

- **Goal 22 — Domain-pack interface and evaluator adapter** (packs, packs/ml): formalizes the
  task/evaluator convention into a typed `EvaluatorAdapter` plus a config-selected domain-pack
  layout; `packs/ml/` is the built-in default pack and preserves existing ML research behavior.
- **Goal 23 — Mathematics proof-search pack (Lean)** (packs/math): first non-ML pack; exact
  Regime-A proof tasks run a controller-owned `lake build` evaluator with hidden theorem checks,
  proof-length/dependency metrics, and math-specific prompt/reference surfaces.
- **Goal 24 — Statistical reproducibility gate** (research): generalizes the promotion gate to
  `exact` / `seeded-deterministic` / `statistical`, the last promoting noisy evaluators only when
  the oriented gain clears a confidence bound across fixed seeded replicates — unlocks Regime B
  without relaxing "no promotion on noise". Seeds, replicate count, and confidence are
  controller-owned, recorded on the attempt, and unreachable by a candidate.
- **Goal 25 — Chip-design pack** (packs/chip): RTL/synthesis candidates scored by an offline
  Yosys flow — a formal-equivalence proof against a controller-owned reference (Regime A) gates a
  synthesis area objective (Regime B) promoted under the Goal 24 statistical gate. A
  non-equivalent design never promotes; the candidate edits only its declared design surface
  (RTL or an allowlisted synthesis recipe), with the reference held out. Selected by
  `config/tier{0,1}.chip.yaml`.
- **Goal 26 — Governed external-experiment boundary** (external, schemas): an
  `EXTERNAL_EXPERIMENT` GovernedAction with a propose → approve → execute → ingest lifecycle so
  Regime-C sciences (wet-lab assays, fabrication, instruments, paid compute) feed signed,
  human-approved results back into the loop while the execution plane never reaches the outside
  world. An `ExternalOracleAdapter` scores a candidate on the ingested, approved, signed result
  instead of running code; a result promotes only when bound (by `governed_action_hash`) to a
  live, matching approval — an unapproved / expired / revoked / hash-mismatched / unsigned
  result is rejected and logged. CLI: `propose-external-experiment`, `list-external-experiments`,
  `ingest-external-result`, `external-audit`.
- **Goal 27 — Drug and life-science pack** (packs/life_science, life_science): two-stage capstone
  combining both new regimes on one life-science workflow. Cheap offline **in-silico screening**
  (Regime B — pinned surrogate docking/ADMET/synthesizability proxies in `hidden/`) ranks
  candidate molecules and promotes under the Goal 24 statistical gate; drug-likeness and
  synthesizability are hard preconditions, so a candidate that inflates predicted affinity by
  stacking lipophilic groups fails outright. A screened candidate may then be **proposed** (never
  agent-authorized) for a rare, governed **wet-lab confirmation** (Regime C via the Goal 26
  boundary): promotion to *confirmed* requires an ingested, signed assay result bound to a live
  human approval — never an in-silico score. `propose_confirmation` enforces
  screening-before-confirmation so costly, irreversible assays stay few and high-value; the
  execution plane runs no synthesis or assay and holds no lab credentials. Selected by
  `config/tier{0,1}.life_science.yaml`.

## Document Map

| File | Purpose |
|---|---|
| [`docs/00_principles.md`](docs/00_principles.md) | Principles, assumptions, tiers, non-goals. |
| [`docs/01_system_architecture.md`](docs/01_system_architecture.md) | Control plane, execution plane, end-to-end architecture. |
| [`docs/02_research_operating_model.md`](docs/02_research_operating_model.md) | Research workflow. |
| [`docs/03_agent_roles.md`](docs/03_agent_roles.md) | Roles, interfaces, model assignment. |
| [`docs/04_experiment_lifecycle.md`](docs/04_experiment_lifecycle.md) | States, promotion, rollback. |
| [`docs/05_evaluation_and_safety_gates.md`](docs/05_evaluation_and_safety_gates.md) | Gates and controls. |
| [`docs/06_research_memory_schema.md`](docs/06_research_memory_schema.md) | Structured memory schema. |
| [`docs/07_model_providers_and_tiers.md`](docs/07_model_providers_and_tiers.md) | Providers and tier config. |
| [`docs/08_frontier_prototype_architecture.md`](docs/08_frontier_prototype_architecture.md) | Tier 1 architecture. |
| [`docs/09_local_testbed_architecture.md`](docs/09_local_testbed_architecture.md) | Tier 0 architecture. |
| [`docs/10_repo_structure.md`](docs/10_repo_structure.md) | Repository layout. |
| [`docs/11_risks_and_controls.md`](docs/11_risks_and_controls.md) | Risks and mitigations. |
| [`docs/12_references.md`](docs/12_references.md) | Source references. |
| [`docs/13_self_improvement_loop.md`](docs/13_self_improvement_loop.md) | Bounded improvement contract. |
| [`docs/14_project_retrospective.md`](docs/14_project_retrospective.md) | Retrospective and backlog. |
| [`docs/15_scale_cost_model.md`](docs/15_scale_cost_model.md) | Cost model and scale bands. |
| [`docs/16_low_cost_validation_plan.md`](docs/16_low_cost_validation_plan.md) | Validation ladder. |
| [`docs/17_operational_pilot_plan.md`](docs/17_operational_pilot_plan.md) | Pilot plan and report contract. |
| [`docs/18_generalizing_to_sciences.md`](docs/18_generalizing_to_sciences.md) | Design exploration: generalizing the loop to math, chip, physics, and life sciences. |
