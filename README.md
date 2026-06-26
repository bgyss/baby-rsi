# Self-Improving Research Organization

A practical, **bounded** self-improving research organization: a multi-agent system that
proposes research hypotheses, runs experiments in a sandbox, scores them against objective
evaluators, preserves structured research memory, and improves its own process — all under
explicit safety and governance gates. It draws on public work (Karpathy's `autoresearch`,
Anthropic's framing of human-overseen recursive self-improvement, DeepMind's AlphaEvolve,
Sakana's AI Scientist); see [`docs/12_references.md`](docs/12_references.md).

This is **not** a blueprint for unrestricted autonomous self-replication or uncontrolled
frontier training — it is a constrained local/lab-scale testbed with objective evaluators,
sandboxing, audit logs, and human approval gates.

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
| `docs/17_operational_pilot_plan.md` | Fixed bounded Tier 0 vs frontier pilot plan and report contract. |

To **operate** the system (rather than read its design), see
[`docs/operating_guide.md`](docs/operating_guide.md) and the repo-local Claude Code skills
in [`.claude/skills/`](.claude/skills/). Build instructions are the staged goal prompts in
[`docs/goal_prompts/`](docs/goal_prompts/) (`01`–`06` Tier 0, `07`–`09` Tier 1, `10`–`12`
Tier 2 governance, `13`–`21` cross-tier hardening); each carries a `## Self-improvement`
section binding it to [`docs/13_self_improvement_loop.md`](docs/13_self_improvement_loop.md).

## Capability tiers

The same loop, gates, and memory run at every tier — only the models behind the agents and
the governance around them change ([`docs/07_model_providers_and_tiers.md`](docs/07_model_providers_and_tiers.md)).
Lowering the tier is always **config-only and safe**.

- **Tier 0** — fully local and offline; validates the machinery.
- **Tier 1** — frontier LLMs (Claude / GPT) prototype the full org; network egress is
  allow-listed to model providers only, and candidate execution stays offline.
- **Tier 2** — governed scale-up; human-gated.

## Development environment

Layered toolchain: **nix** (`flake.nix`) provides a reproducible shell with `mise` and
native deps; **mise** (`mise.toml`) pins the Python/`uv` versions and runs tasks; **uv**
manages Python dependencies. See [`docs/09_local_testbed_architecture.md`](docs/09_local_testbed_architecture.md).

```zsh
nix develop        # or: direnv allow  (auto-enters via .envrc)
mise install       # python 3.11 + uv at pinned versions
mise run sync      # uv sync
mise run test      # uv run pytest
```

## Implementation status

Goals 01-21 are implemented. Every goal reuses the same lifecycle, gates, evaluator, and
memory schema — only what fills the roles changes, by **config not code**, as the tier
rises. One line per goal below; **full per-goal detail is in
[`docs/implementation_status.md`](docs/implementation_status.md)**.

### Tier 0 — local bounded testbed (Goals 01–06)

- **Goal 01 — Project scaffold** — schemas, JSONL archive + audit ledger, plane-isolation primitives, objective scoring, and the CLI surface.
- **Goal 02 — Code-improver loop** — the per-task inner loop (propose → sandbox → evaluate → archive → select) with offline candidate execution.
- **Goal 03 — Research memory** — durable structured records (negatives included) distilled into the proposer prompt.
- **Goal 04 — Promotion gates** — code-integrity, safety, reproducibility, and hidden-test gates that bound what the loop may promote.
- **Goal 05 — Meta-research loop** — the bounded outer loop: reflect, propose a reversible process change, A/B-test on a fixed benchmark; durable application stays human-gated.
- **Goal 06 — Tiny-training autoresearch** — the inner loop applied to training a fixed pure-Python MLP under a wall-clock budget.

### Tier 1 — frontier research organization (Goals 07–09)

- **Goal 07 — Provider abstraction** — one `ModelClient` behind local/Claude/GPT; tier + per-role binding by config; token/USD ceilings; every call audited.
- **Goal 08 — Frontier research org** — one objective routed through model-backed roles with a control-plane-only toolset and cross-model safety review.
- **Goal 09 — Research-shaped task suite** — `algorithm`/`training`/`policy` families scored by controller-owned objective evaluators with enforced no-leakage.

### Tier 2 — governed scale-up (Goals 10–12)

- **Goal 10 — Governance gate** — default-deny human-approval workflow over an append-only ledger; approvals bound to the exact change by content hash.
- **Goal 11 — Governed compute scale-up** — hard compute-budget tiers granted only with promotion-before-budget *and* a bound approval.
- **Goal 12 — Governed model-training** — bounded offline weight-update behind a stability precondition + `MODEL_TRAIN` approval; deploy needs a separate approval + cross-model review.

### Cross-tier hardening and production refinements (Goals 13–19)

- **Goal 13 — Documentation consistency contract** — machine-readable goal manifest + docs/privacy checker (`check-docs`).
- **Goal 14 — Pricing audit and budget calibration** — dated price overrides, ledger pricing metadata, and `pricing-audit`.
- **Goal 15 — Hard resource isolation backend** — process-group memory/pid ceilings plus a Linux cgroup v2 `linux_guarded` backend.
- **Goal 16 — Durable research store and query layer** — opt-in SQLite backend with migrations, dedupe, hash-chained tamper-evidence, and JSONL round-trip.
- **Goal 17 — Research benchmark suite expansion** — ≥10 tasks/family plus data-cleaning and parser/validator families, adversarial variants, and richer per-family summaries.
- **Goal 18 — Provider operations and observability** — classified errors, bounded retries, ledger request metadata, and `provider-report`.
- **Goal 19 — Governance identity and policy hardening** — operator identities, signed approval proofs, policy templates, two-person approval, and packet export/verify.

### Cross-tier hardening and production refinements (Goal 20)

- **Goal 20 — Bounded operational pilot and cost-per-promotion report** — a fixed, budget-capped Tier 0 vs frontier pilot plus a Markdown report with a continue/revise/stop recommendation.

### Conversational operations (Goal 21)

- **Goal 21 — Conversational operating interface in Claude Code** — operate via the repo-local skills (no REPL), with global `--json` (machine-readable summaries) and `--dry-run` (preview command/tier/governance, no side effects) affordances.

## Operating the system

The canonical interface is `uv run siro` (mise tasks are thin wrappers), but rather than
memorize ~35 subcommands, use one of two entry points:

- **[`docs/session_tutorial.md`](docs/session_tutorial.md)** — a worked **conversational
  session**: what it looks like to operate the whole system in dialogue inside Claude Code
  (observe → run → governed scale-up → pilot → monitor), with the actual turns.
- **[`docs/operating_guide.md`](docs/operating_guide.md)** — the command reference: a
  task-oriented tutorial across the whole command surface (observe → run → meta-loop →
  governed scale-up → approvals → pilot → storage → maintenance), with exact flags.
- **Repo-local Claude Code skills** ([`.claude/skills/`](.claude/skills/)) — drive the system
  in dialogue with five verbs: **`/siro`** (control plane + router), **`/siro-run`** (run an
  experiment at the right tier), **`/siro-watch`** (monitoring snapshot), **`/siro-govern`**
  (approval workflow), **`/siro-pilot`** (the bounded pilot).

Two global flags (Goal 21) keep the dialogue honest: `--dry-run` previews any command's tier
and governance implications without acting, and `--json` makes the read-only summaries
machine-readable. The fastest first run is fully local and free:

```zsh
uv run siro --help
uv run siro --json summarize-research                 # read suite health as JSON (read-only, safe)
uv run siro --dry-run run-scaled --compute-tier 1     # preview a governed action — no state change
uv run siro run-research tasks/research/training/tiny_mlp --config config/tier0.local.yaml  # one cycle, local
```

## Suggested use

1. Read [`docs/00_principles.md`](docs/00_principles.md) and
   [`docs/01_system_architecture.md`](docs/01_system_architecture.md) for the design.
2. Operate the system in dialogue with the `.claude/skills/` skills, or follow
   [`docs/operating_guide.md`](docs/operating_guide.md); lowering a run from Tier 2 → 1 → 0
   is config-only.
3. For build context, read the goal prompts in order and the per-goal notes in
   [`docs/implementation_status.md`](docs/implementation_status.md).
