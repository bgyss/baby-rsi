# Self-Improving Research Organization

This directory codifies a practical, bounded version of a **self-improving research organization**: a multi-agent system that can propose research hypotheses, implement experiments, evaluate results, preserve structured scientific memory, and improve its own research process under explicit safety and governance gates.

The design is inspired by several public research directions:

- Karpathy's `autoresearch`: an agent edits a training script, runs fixed-budget experiments, and optimizes validation bits-per-byte.
- Anthropic's public framing of recursive self-improvement: AI systems increasingly assisting in building future AI systems, with humans still needed for oversight, judgment, and governance.
- DeepMind's AlphaEvolve: evolutionary LLM-driven algorithm/code improvement with evaluator feedback.
- Sakana AI's AI Scientist: automated idea generation, implementation, experimentation, paper writing, and review.

This is **not** a blueprint for unrestricted autonomous model self-replication or uncontrolled frontier training. The intended implementation is a constrained local or lab-scale testbed with objective evaluators, sandboxing, audit logs, and human approval gates.

## Document map

All design docs live under [`docs/`](docs/).

| File | Purpose |
|---|---|
| `docs/00_principles.md` | Core principles, assumptions, tiers, and non-goals. |
| `docs/01_system_architecture.md` | End-to-end architecture; control plane vs execution plane. |
| `docs/02_research_operating_model.md` | How research work flows through the organization. |
| `docs/03_agent_roles.md` | Agent role definitions, interfaces, and model assignment. |
| `docs/04_experiment_lifecycle.md` | Experiment states, promotion rules, and rollback. |
| `docs/05_evaluation_and_safety_gates.md` | Capability, safety, regression, and governance gates. |
| `docs/06_research_memory_schema.md` | Schema for structured scientific memory. |
| `docs/07_model_providers_and_tiers.md` | Provider abstraction (local + Claude + GPT) and capability tiers. |
| `docs/08_frontier_prototype_architecture.md` | Tier 1: the full org prototyped with frontier LLMs. |
| `docs/09_local_testbed_architecture.md` | Tier 0: minimal local implementation with local models and code evaluators. |
| `docs/10_repo_structure.md` | Suggested repository layout. |
| `docs/11_risks_and_controls.md` | Main failure modes and controls (incl. frontier-provider risks). |
| `docs/12_references.md` | Public references used to ground this draft. |
| `docs/13_self_improvement_loop.md` | The uniform, bounded self-improvement contract every goal prompt and loop follows. |
| `docs/14_project_retrospective.md` | Retrospective on the implemented system and refinement backlog. |
| `docs/15_scale_cost_model.md` | Source-backed deployment cost model and scale bands. |
| `docs/16_low_cost_validation_plan.md` | Cheap local-to-frontier validation ladder. |

Goal prompts live in `docs/goal_prompts/`: `01`–`06` build the local Tier 0 testbed; `07`–`09` generalize the model layer and stand up the Tier 1 frontier organization; `10`–`12` build Tier 2 governed scale-up — the governance gate + human-approval workflow (`10`), governed compute scale-up (`11`), and governed model-training experiments (`12`). Goals `01`–`12` are implemented. Goals `13`–`20` are post-Tier-2 refinement specs: docs consistency (`13`), pricing audit (`14`), hard resource isolation (`15`), durable storage (`16`), benchmark expansion (`17`), provider operations (`18`), governance identity (`19`), and the bounded operational pilot (`20`). Every goal prompt carries a `## Self-improvement` section that binds its component into the bounded self-improvement cycle defined in `docs/13_self_improvement_loop.md`.

## Capability tiers

The same loop, gates, and memory run at every tier — only the models behind the agents and the governance around them change (`docs/07_model_providers_and_tiers.md`):

- **Tier 0** — fully local and offline; validates the machinery.
- **Tier 1** — frontier LLMs (Claude / GPT) prototype the full research organization; network egress is allow-listed to model providers only, and candidate execution stays offline.
- **Tier 2** — governed scale-up; human-gated.

Lowering the tier is always config-only and safe.

## Development environment

The toolchain is layered: **nix** (`flake.nix`) provides a reproducible bootstrap shell with `mise` and native deps; **mise** (`mise.toml`) pins the Python/`uv` versions and runs tasks; **uv** manages Python dependencies. See `docs/09_local_testbed_architecture.md`.

```zsh
nix develop        # or: direnv allow  (auto-enters via .envrc)
mise install       # python 3.11 + uv at pinned versions
mise run sync      # uv sync
mise run test      # uv run pytest
mise tasks         # list available tasks
```

## Implementation status

Goals 01–12 are implemented, including the Tier 2 governance, compute scale-up, and
model-training testbed work that landed in Goals 10–12. Goals 13–20 are specified, not yet
implemented. Every implemented goal reuses the same lifecycle, gates, evaluator, and memory
schema — only what fills the roles changes, by **config not code**, as the tier rises. Each
entry below names its goal, the modules/artifacts it added or will add, and what it does.

### Tier 0 — local bounded testbed (Goals 01–06)

- **Goal 01 — Project scaffold** (`schemas`, `archive`, `safety`, `evaluator`, `cli`):
  explicit Pydantic schemas, an append-only JSONL archive + audit ledger, plane-isolation
  primitives, the objective scoring function, and the CLI surface.
- **Goal 02 — Code-improver loop** (`controller`, `sandbox`): the per-task inner loop
  (propose → sandbox → evaluate → archive → select) with isolated, offline candidate
  execution.
- **Goal 03 — Research memory** (`memory`): durable structured records — negatives
  included — distilled into the proposer prompt.
- **Goal 04 — Promotion gates** (`gates`): code-integrity, safety, reproducibility, and
  hidden-test gates that bound what the loop may promote.
- **Goal 05 — Meta-research loop** (`meta`): the bounded outer loop — reflect on the
  archive, propose a reversible process change (prompts/retrieval), A/B-test it on a fixed
  benchmark, recommend promote/reject; separate `runs/meta_changes.jsonl` archive, generated
  rollback plan, durable application held behind a human-approval flag.
- **Goal 06 — Tiny-training autoresearch** (`training`, `training_task`): the same inner
  loop applied to *training* — a candidate proposes a bounded `TrainConfig`, the sandbox
  trains a fixed pure-Python MLP under a fixed wall-clock budget, and the best reproducible
  validation-loss improvement is promoted; deltas in `runs/training_attempts.jsonl`.

### Tier 1 — frontier research organization (Goals 07–09)

- **Goal 07 — Provider abstraction** (`providers/`, `config`, `budget`): one `ModelClient`
  interface behind local llama.cpp/LlamaBarn, Claude, and GPT backends (structured output,
  tool use, per-call token/cost/latency accounting); tier + per-role provider binding from
  `config/tierN.*.yaml`; per-run/per-day USD and per-call token ceilings that halt-and-
  escalate. The Goal 02 loop runs Tier 0 (local) or Tier 1 (frontier) by config only; every
  call logged to `runs/model_calls.jsonl`, no credential in the execution plane.
- **Goal 08 — Frontier research org** (`orchestrator`, `agents/`, `tools`): one human
  objective routed through model-backed roles (Hypothesis → Literature → triage →
  Implementation → gates → offline sandbox → objective evaluator + Evaluation narrative →
  cross-model Safety review → Interpretation → promotion gate → Memory Curator → agenda).
  Each role is a provider-bindable agent with a typed `output_schema` and a **control-plane-
  only** toolset (`read_allowed_file`, `query_memory`, `list_references`, `propose_patch` —
  never shell/network). Safety binds to a *different* provider than Implementation (required
  at Tier ≥ 1); safety-vs-gate disagreement escalates rather than tie-breaks; `tier: 1 → 0`
  returns to fully-local with no code change.
- **Goal 09 — Research-shaped task suite** (`research`, `tasks/research/`): real work
  beyond single-function repair — three families (`algorithm/` scored by executed-line
  count, `training/` by held-out validation loss under a wall-clock budget, `policy/` by
  aggregate pass rate over a held-out benchmark). Each task has a `brief.md`, a `baseline/`
  edit surface, a controller-owned objective `eval.py` (returns a typed `MetricRecord`), and
  an optional `hidden/` set. `Orchestrator.run_research_cycle` runs the same lifecycle/gates;
  promotion is decided by the objective evaluator and requires a *reproducible* improvement.
  No-leakage is **enforced, not assumed** (held-out data handed to `eval.py` via
  `SIRO_HIDDEN_PATH`, outside the candidate cwd). Attempts in `runs/research_attempts.jsonl`;
  `summarize-research` reports per-family pass rate, median cycles to success, safety-gate
  failures, token/USD spend, and strategy diversity.

### Tier 2 — governed scale-up (Goals 10–12)

- **Goal 10 — Governance gate** (`governance`, `config/tier2.governed.yaml`): the Tier 2
  human-approval workflow that makes the self-improvement bounds an enforced, auditable
  artifact. A default-deny `GovernanceGate` over an append-only `runs/approvals.jsonl` ledger
  of typed `ApprovalRequest`/`ApprovalDecision`/`ApprovalRevocation` records. A governed
  action (the bounds of `docs/13` — budget/tier/evaluator/egress/permission/deploy changes)
  proceeds only with a recorded, human-issued approval **bound to the exact change by content
  hash**; absent one it records a pending request and raises `GovernanceDenied` (halt +
  escalate). Approvals are single-use or standing, expiring, and revocable; `approve` /
  `deny` / `revoke` are human-only CLI verbs — no agent tool grants approval. Enabled only at
  Tier ≥ 2 by config; lowering the tier disables the capability with no code change.
- **Goal 11 — Governed compute scale-up** (`scale`, `sandbox.run_guarded`): larger compute /
  longer experiments under governance. Compute budget tiers (`ComputeBudget` = a hard
  wall-clock + memory ceiling); a `ComputeAllocator` grants a tier only with **both** a
  recorded pass at the next-smaller tier (promotion-before-budget) **and** a Goal 10 approval
  bound to the exact `(experiment, tier)` — otherwise it refuses/escalates. The execution
  plane's ceilings are enforced by `Sandbox.run_guarded`: a hard wall-clock deadline plus a
  `ps`-based memory monitor that kills the process group on breach; a breach halts and
  escalates (`BudgetExceeded`) and is recorded as a negative attempt, leaving the archive
  consistent. `CheckpointStore` writes atomic per-experiment checkpoints so a halt loses no
  work and resumes. Plane isolation is unchanged at scale (offline, credential-free). CLI:
  `run-scaled --compute-tier`.
- **Goal 12 — Governed model-training** (`model_training`): the strongest loop, fully
  bounded. A `GovernedModelTrainer` produces model **weights** (a deterministic, offline,
  pure-Python trainer) only when (a) the capability is enabled at Tier 2, (b) the
  **stability precondition** is met — the evaluator/audit/gates are green, checked *before*
  and *independent of* any approval — and (c) a human-approved `MODEL_TRAIN` request is on
  record. Weights are stored as a `TrainedModelArtifact` with full reproducible lineage
  (base-model hash, data id + seed, config, code version) and archived (failures too). A
  trained model is **never** auto-bound to a role: `deploy_model` requires a *separate*
  `MODEL_DEPLOY` approval **and** cross-model review (reviewer provider ≠ the role's
  implementation provider), recorded in a `ModelRegistry`. Disabled entirely at Tier ≤ 1.
  CLI: `train-model`, `deploy-model`.

### Cross-tier hardening and production refinements (Goals 13–20) — specified, not yet implemented

- **Goal 13 — Documentation consistency contract** (`docs/goal_prompts/goals.json`,
  docs checker): specifies a machine-readable goal manifest and docs consistency/privacy
  checker so README status, goal prompts, and Self-improvement sections cannot drift
  silently.
- **Goal 14 — Pricing audit and budget calibration** (`pricing`, `config`, CLI): specifies
  config-level model price overrides, reviewed dates, pricing-audit reports, and stricter
  budget calibration so scale decisions use current source-backed estimates.
- **Goal 15 — Hard resource isolation backend** (`sandbox`, `scale`): specifies a
  Linux/container hard-isolation backend with cgroup-backed memory/process limits,
  process-tree accounting, no execution-plane network, and portable local fallback tests.
- **Goal 16 — Durable research store and query layer** (`archive`, `memory`, `storage`):
  specifies a storage interface plus SQLite backend with migrations, idempotency,
  stable lineage IDs, JSONL export compatibility, and optional tamper-evident governance
  records.
- **Goal 17 — Research benchmark suite expansion** (`tasks/research/`, `research`):
  specifies a larger fixed benchmark with at least 10 tasks per existing family, new
  families, adversarial/noisy tasks, and richer per-family/cost-per-promotion summaries.
- **Goal 18 — Provider operations and observability** (`providers/`, `budget`, reports):
  specifies provider error taxonomy, bounded retries, request metadata, per-role
  concurrency limits, and spend/latency/error reports by provider, model, role, and task
  family.
- **Goal 19 — Governance identity and policy hardening** (`governance`, storage, CLI):
  specifies typed operator identities, signed approvals, policy templates, two-person
  approval where required, governance packet export, and ledger verification while keeping
  agents unable to approve.
- **Goal 20 — Bounded operational pilot and cost-per-promotion report** (`runs/pilots/`,
  reports): specifies a fixed, budget-capped Tier 0 vs cheap-frontier vs strong-frontier
  pilot that reports cost, promotion quality, safety escalations, and a continue/revise/stop
  recommendation before any serious scale-up.

The canonical interface is `uv run siro` (mise tasks are thin wrappers):

```zsh
uv run siro --help
uv run siro summarize-runs runs/attempts.jsonl        # reflect on the archive
uv run siro run-task tasks/code_improver/task_001     # per-task code inner loop (Goal 02), Tier 0
uv run siro run-task tasks/code_improver/task_001 --config config/tier1.frontier.yaml  # Tier 1 (Goal 07)
uv run siro run-training tasks/training/task_001      # per-task training inner loop (Goal 06)
uv run siro run-org tasks/code_improver/task_001 --objective "Make sum_list simpler"  # full Tier 1 org cycle (Goal 08)
uv run siro run-org tasks/code_improver/task_001 --config config/tier0.local.yaml     # same org, fully local — config-only
uv run siro run-research                              # org runs every research-suite task (Goal 09)
uv run siro run-research tasks/research/training/tiny_mlp --config config/tier0.local.yaml  # one family, fully local
uv run siro summarize-research                        # per-family suite summary (Goal 09)
uv run siro propose-meta-change runs/attempts.jsonl   # meta-research outer loop (Goal 05)
uv run siro request-approval budget_increase --target max_usd_per_run --payload '{"max_usd_per_run":20}'  # Tier 2 governance request (Goal 10)
uv run siro approve <request_id> --by <human>         # human-only grant; list-approvals/deny/revoke too (Goal 10)
uv run siro run-scaled --compute-tier 1               # eval under a governed compute budget (Goal 11)
uv run siro train-model exp1                          # governed weight-update experiment (Goal 12)
uv run siro deploy-model <artifact_id> implementation --implementation-provider anthropic --reviewer-provider openai  # gated deploy (Goal 12)
uv run pytest tests/test_cli.py::test_tier2_model_training_smoke_path_uses_separate_train_and_deploy_approvals  # cheap Tier 2 approval/deploy smoke
```

## Suggested use

1. Read `docs/00_principles.md` and `docs/01_system_architecture.md` for the design.
2. For historical build context, read the implemented goal prompts in order: `01`–`06` for
   Tier 0, `07`–`09` for Tier 1, and `10`–`12` for the Tier 2 governed testbed.
3. Use the command block above to exercise the current implementation by tier; lowering a
   run from Tier 2 → 1 → 0 is config-only.
4. Treat goals `13`–`20` as the post-Tier-2 hardening roadmap before any serious scale-up.
