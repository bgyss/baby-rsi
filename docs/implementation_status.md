# Implementation status — per-goal detail

Detailed notes on each implemented goal, linked from the README's compact status index.
Every goal reuses the same lifecycle, gates, evaluator, and memory schema — only what fills
the roles changes, by **config not code**, as the tier rises. For how to *operate* the
system, see [`operating_guide.md`](operating_guide.md); for the build instructions, see the
goal prompts under [`goal_prompts/`](goal_prompts/).

## Tier 0 — local bounded testbed (Goals 01–06)

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

## Tier 1 — frontier research organization (Goals 07–09)

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

## Tier 2 — governed scale-up (Goals 10–12)

- **Goal 10 — Governance gate** (`governance`, `config/tier2.governed.yaml`): the Tier 2
  human-approval workflow that makes the self-improvement bounds an enforced, auditable
  artifact. A default-deny `GovernanceGate` over an append-only `runs/approvals.jsonl` ledger
  of typed `ApprovalRequest`/`ApprovalDecision`/`ApprovalRevocation` records. A governed
  action (the bounds of `13_self_improvement_loop.md` — budget/tier/evaluator/egress/
  permission/deploy changes) proceeds only with a recorded, human-issued approval **bound to
  the exact change by content hash**; absent one it records a pending request and raises
  `GovernanceDenied` (halt + escalate). Approvals are single-use or standing, expiring, and
  revocable; `approve` / `deny` / `revoke` are human-only CLI verbs — no agent tool grants
  approval. Enabled only at Tier ≥ 2 by config; lowering the tier disables the capability
  with no code change.
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

## Cross-tier hardening and production refinements (Goals 13–20)

- **Goal 13 — Documentation consistency contract** (`docs/goal_prompts/goals.json`,
  `docs_check`, CLI): machine-readable goal manifest and docs consistency/privacy
  checker so README status, goal prompts, and Self-improvement sections cannot drift
  silently. CLI: `check-docs`; task: `mise run check-docs`.
- **Goal 14 — Pricing audit and budget calibration** (`providers/pricing`, `config`,
  CLI): config-level model price overrides with reviewed dates and source notes, pricing
  metadata recorded in model-call ledgers, and `pricing-audit` reporting for configured
  providers, stale/missing prices, budget ceilings, and representative cycle costs.
- **Goal 15 — Hard resource isolation backend** (`backends`, `sandbox.run_guarded`,
  `scale`): a sandbox backend abstraction behind the guarded execution path. The portable
  `local` backend (the developer fallback) now sums the whole process group's RSS and
  process count, so a forked child cannot dodge the memory/process ceiling; the
  `linux_guarded` backend lets the Linux cgroup v2 kernel enforce `memory.max` (OOM-kill),
  `pids.max`, and peak accounting where available. A config `compute` backend policy can
  require a hard backend above a chosen tier (`hard_backend_above_tier`), with an explicit
  `allow_local_dev` override. CLI: `sandbox-backends`, `run-scaled --backend`.
- **Goal 16 — Durable research store and query layer** (`storage`, `schemas`, CLI): a
  storage interface over every append-only stream (attempts, research/training attempts,
  model calls, memory, meta-changes, governance, artifacts, deployments). JSONL stays the
  default transparent backend; an opt-in SQLite backend adds schema migrations, idempotency
  keys (repeated writes dedupe), hash-chained tamper-evidence for governance/artifact
  records, and byte-compatible JSONL export/import. `summarize-runs`/`summarize-research`
  read through either backend. CLI: `storage-migrate`, `storage-import`, `storage-export`,
  `storage-verify`.
- **Goal 17 — Research benchmark suite expansion** (`tasks/research/`, `research`): expands
  the fixed suite to at least 10 tasks each for algorithm, training, and policy work, adds
  data-cleaning and parser/validator families, tags adversarial variants, keeps hidden data
  held out of prompts and candidate working directories, and reports richer per-family
  summary fields including mixed/failed outcomes, hidden/reproducibility failures, and
  cost per promotion.
- **Goal 18 — Provider operations and observability** (`providers/ops`, `providers/_http`,
  CLI): classified provider errors, bounded retry policy with no retries for auth/config or
  budget failures, provider request metadata on ledger rows, per-provider ops config, failed
  call records in the single-agent loop, and `provider-report` for spend, latency, retry,
  error, family-spend, and cost-per-promotion summaries.
- **Goal 19 — Governance identity and policy hardening** (`governance`, `schemas`, CLI,
  `config/tier2.governed.yaml`): typed operator identities, local signing proofs over
  canonical approval payloads, per-action policy templates, two-person approval where
  required, governance packet export, and identity/policy ledger verification. Existing
  Goal 10 ledgers remain readable as legacy records; new hardened approvals validate active
  operators, roles, signatures, requester/approver separation, expiry, and exact content
  hashes. Human-only CLI verbs manage operators and approvals; the agent tool surface still
  has no approval, signing, operator-management, or policy-mutation tool.
- **Goal 20 — Bounded operational pilot and cost-per-promotion report** (`pilot`,
  `docs/17_operational_pilot_plan.md`, `config/tier1.cheap_frontier.yaml`, CLI): a fixed,
  budget-capped Tier 0 vs cheap-frontier vs strong-frontier pilot plan with immutable task
  list, per-arm configs, stop conditions, command transcript generation, and a Markdown
  report rendered from archived research attempts plus model-call ledgers. The report
  separates accepted/promoted, mixed/escalated, and failed results; computes estimated spend,
  cost per accepted promotion, cost per family, hidden/reproducibility/safety rates, common
  failure signatures; flags budget breaches or missing evidence; and emits a
  continue/revise/stop recommendation without approving any scale-up.

## Conversational operations (Goal 21)

- **Goal 21 — Conversational operating interface in Claude Code** (`.claude/skills/`,
  `docs/operating_guide.md`, `src/siro/cli.py`): operate the system as a dialogue hosted
  inside Claude Code through the repo-local skills (intent → plan → confirm → act), rather
  than a memorized sequence of commands — explicitly **not** a separate REPL or `siro chat`
  process. Adds only thin, non-interactive CLI affordances: a global `--json` that makes the
  read-only summaries (`summarize-runs`, `summarize-research`, `provider-report`,
  `list-approvals`) emit machine-readable output the skills parse, and a global `--dry-run`
  that prints the exact command, tier, and governance implications and exits **without** any
  state change, spend, or ledger write. Every governed or irreversible action stays
  human-confirmed and the plane/governance bounds are unchanged.
