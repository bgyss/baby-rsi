# Implementation Status

Detailed status for the compact README index. The invariant across all goals: same
lifecycle, gates, evaluator contracts, and memory model; tier changes happen by config.

## Tier 0 — Local Bounded Testbed

| Goal | Modules | Status |
|---|---|---|
| 01 — Project scaffold | `schemas`, `archive`, `safety`, `evaluator`, `cli` | Typed records, JSONL archive/audit ledger, plane-isolation primitives, scoring, CLI. |
| 02 — Code-improver loop | `controller`, `sandbox` | Offline propose-run-evaluate-archive-select loop for code tasks. |
| 03 — Research memory | `memory` | Durable positive/negative records distilled into future proposer context. |
| 04 — Promotion gates | `gates` | Code-integrity, safety, reproducibility, and hidden-test gates. |
| 05 — Meta-research loop | `meta` | Reflects on archives, proposes reversible prompt/retrieval/process changes, A/B-tests on a fixed benchmark, writes rollback plans. Durable application remains human-gated. |
| 06 — Tiny-training autoresearch | `training`, `training_task` | Candidate `TrainConfig` search for a fixed pure-Python MLP under a wall-clock budget; results in `runs/training_attempts.jsonl`. |

## Tier 1 — Frontier Research Organization

| Goal | Modules | Status |
|---|---|---|
| 07 — Provider abstraction | `providers/`, `config`, `budget` | One `ModelClient` over local llama.cpp/LlamaBarn, OpenAI, and Anthropic backends; role binding by config; per-run/per-day USD and token ceilings; calls logged to `runs/model_calls.jsonl`. |
| 08 — Frontier research org | `orchestrator`, `agents/`, `tools` | Full role chain from hypothesis through memory update, using typed role outputs and control-plane-only tools. Tier >= 1 requires Safety/Evaluation review on a different provider than Implementation. |
| 09 — Research-shaped task suite | `research`, `packs/ml/tasks/` | Algorithm, training, and policy task families with `brief.md`, baseline edit surface, controller-owned `eval.py`, optional hidden data, reproducibility checks, and archive summaries. Hidden data stays outside candidate cwd via `SIRO_HIDDEN_PATH`. |

## Tier 2 — Governed Scale-Up

| Goal | Modules | Status |
|---|---|---|
| 10 — Governance gate | `governance`, `config/tier2.governed.yaml` | Default-deny approval ledger with typed requests, decisions, revocations, expiry, single-use approvals, and content-hash binding. Agents can request; only humans approve/deny/revoke. |
| 11 — Governed compute scale-up | `scale`, `sandbox.run_guarded` | Higher compute tiers require both a smaller-tier pass and bound approval. Guarded runs enforce wall-clock, memory, and process ceilings; breaches are archived as negative attempts. |
| 12 — Governed model-training | `model_training` | Offline deterministic weight update only at Tier 2, after stability checks and `MODEL_TRAIN` approval. Deployment is separate, requires `MODEL_DEPLOY` approval and cross-model review. |

## Cross-Tier Hardening

| Goal | Modules | Status |
|---|---|---|
| 13 — Documentation consistency contract | `docs/goal_prompts/goals.json`, `docs_check`, CLI | Manifest-backed checks for README status, goal prompts, required self-improvement sections, and path privacy. CLI: `check-docs`; task: `mise run check-docs`. |
| 14 — Pricing audit and budget calibration | `providers/pricing`, `config`, CLI | Dated model price overrides, pricing metadata in ledgers, strict stale/missing-price checks, and representative cycle-cost reporting. |
| 15 — Hard resource isolation backend | `backends`, `sandbox.run_guarded`, `scale` | Sandbox backend abstraction; portable process-group ceilings; optional Linux cgroup v2 `linux_guarded` backend; backend policy in config. |
| 16 — Durable research store and query layer | `storage`, `schemas`, CLI | JSONL remains default. SQLite adds migrations, idempotency keys, hash-chained governance/artifact records, and JSONL import/export. |
| 17 — Research benchmark suite expansion | `packs/ml/tasks/`, `research` | At least 10 tasks each for algorithm, training, and policy work; added data-cleaning and parser/validator families; adversarial variants; richer summaries. |
| 18 — Provider operations and observability | `providers/ops`, `providers/_http`, CLI | Classified provider errors, bounded retries, request metadata, provider ops config, failed-call records, and `provider-report`. |
| 19 — Governance identity and policy hardening | `governance`, `schemas`, CLI | Operators, signatures, policy templates, two-person approval, requester/approver separation, packet export, and ledger verification. Legacy Goal 10 records stay readable. |
| 20 — Bounded operational pilot and cost-per-promotion report | `pilot`, `docs/17_operational_pilot_plan.md`, CLI | Fixed Tier 0 vs frontier pilot, budget caps, command transcript, archived evidence, cost-per-promotion report, and continue/revise/stop recommendation. |

## Conversational Operations

| Goal | Modules | Status |
|---|---|---|
| 21 — Conversational operating interface in Claude Code and Codex | `.claude/skills/`, `.codex/skills/`, `docs/operating_guide.md`, `src/siro/cli.py` | Host-specific repo-local skills operate the existing CLI. No REPL. Global `--json` supports precise read-only summaries; global `--dry-run` previews command, tier, and governance implications without side effects. | <!-- docs-privacy-allow -->

## Generalization to the Sciences

| Goal | Modules | Status |
|---|---|---|
| 22 — Domain-pack interface and evaluator adapter | `packs`, `research`, `config`, `orchestrator`, `packs/ml/` | Typed `EvaluatorAdapter` and pack loader; config-selected `pack: ml`; existing research families reseated under `packs/ml/tasks/`; per-pack tool whitelists can only narrow the global control-plane toolset. |
| 23 — Mathematics proof-search pack (Lean) | `packs/math/`, `research`, `config/tier0.math.yaml`, `config/tier1.math.yaml` | First non-ML pack. Exact-regime Lean proof tasks run a controller-owned `lake build` evaluator with hidden theorem checks; metrics record proof verification plus proof length/dependency count; math prompts and references specialize the existing org roles. |
| 24 — Statistical reproducibility gate | `research`, `schemas`, `sandbox`, `orchestrator`, `packs` | `research_improves`/`research_reproducibility_gate` dispatch on the pack's declared regime (`exact` bit-for-bit, `seeded-deterministic` within `REPRO_TOLERANCE`, `statistical`). The statistical policy scores candidate and incumbent across fixed seeded replicates (`SIRO_EVAL_SEED`, paired) and promotes only when a direction-aware confidence interval on the primary-metric delta excludes zero; declared secondaries may not regress past tolerance within their own bound. Seeds, replicate count, and confidence are controller-owned `StatisticalPolicy` parameters, recorded on `ResearchAttempt.statistical` so the noisy decision is reproducible, and unreachable by a candidate (reading the seed env trips the safety gate). The ML and math packs keep their deterministic regimes unchanged. |
| 25 — Chip-design pack | `packs/chip/`, `config/tier0.chip.yaml`, `config/tier1.chip.yaml`, `flake.nix` | Second non-ML pack (regime `statistical`). Each task's controller-owned `eval.py` drives an offline Yosys flow: a formal-equivalence miter+SAT proof against a hidden reference (correctness is a hard precondition — a non-equivalent design fails regardless of area), then a synthesis pass reporting generic cell count as the area metric, governed by the Goal 24 confidence-bound gate. Two families: `rtl_area` (candidate edits `design.v`, reducing area while equivalent) and `synth_recipe` (candidate edits an allowlisted Yosys pass list for a fixed read-only design). The reference/constraints are controller-owned (`SIRO_HIDDEN_PATH`); the candidate edits only its declared surface. `yosys` + `sby` are provisioned by nix (`eqy` is not yet in nixpkgs; the pack uses Yosys built-in equivalence). Hardware-specialized Implementation/Literature prompts; org roles and lifecycle otherwise unchanged. |
