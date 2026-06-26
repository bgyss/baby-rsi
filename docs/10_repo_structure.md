# 10 — Suggested Repository Structure

```text
baby-rsi/
  README.md
  CLAUDE.md
  flake.nix            # nix: reproducible bootstrap shell (mise + native deps)
  .envrc               # direnv: `use flake` + mise activation
  mise.toml            # mise: pinned python/uv versions + task runner
  pyproject.toml       # uv: Python project + dependencies
  uv.lock              # uv: resolved lockfile (checked in)
  config/
    tier0.local.yaml   # local-only config (Tier 0)
    tier1.frontier.yaml# frontier prototype config (Tier 1)
  docs/                # all design docs + goal prompts (no code)
    00_principles.md
    01_system_architecture.md
    02_research_operating_model.md
    03_agent_roles.md
    04_experiment_lifecycle.md
    05_evaluation_and_safety_gates.md
    06_research_memory_schema.md
    07_model_providers_and_tiers.md
    08_frontier_prototype_architecture.md
    09_local_testbed_architecture.md
    10_repo_structure.md
    11_risks_and_controls.md
    12_references.md
    goal_prompts/
      goal_01_project_scaffold.md
      goal_02_code_improver_loop.md
      goal_03_research_memory.md
      goal_04_eval_and_safety_gates.md
      goal_05_meta_research_loop.md
      goal_06_local_training_autoresearch.md
      goal_07_provider_abstraction.md
      goal_08_frontier_research_org.md
      goal_09_research_task_suite.md
  src/
    siro/
      __init__.py
      controller.py
      orchestrator.py      # multi-agent routing, budget + tier policy (control plane)
      schemas.py
      model_client.py      # provider abstraction (Protocol)
      providers/
        __init__.py
        local.py           # llama.cpp / LlamaBarn (OpenAI-compatible)
        anthropic.py       # Claude
        openai.py          # GPT
      agents/
        __init__.py        # role wiring: prompt + output schema + tools per role
      tools.py             # control-plane tools agents may call (no shell/network)
      sandbox.py           # execution plane: no network, timeouts, temp dir
      evaluator.py
      archive.py
      memory.py
      safety.py            # gates incl. plane-isolation + provider integrity
      budget.py            # compute + token/USD accounting and ceilings
      prompts.py
  tasks/
    code_improver/
      task_001/
        prompt.md
        seed_solution.py
        tests.py
    research/             # Tier 1 research-shaped tasks
      research_001/
        brief.md
        baseline/
        eval.py
  prompts/
    orchestrator.md
    hypothesis_agent.md
    literature_agent.md
    implementation_agent.md
    evaluation_agent.md
    safety_agent.md
    interpretation_agent.md
    meta_research_agent.md
  runs/
    attempts.jsonl
    experiments.sqlite
    model_calls.jsonl    # audit ledger: provider, model, tokens, cost, latency
    artifacts/
  tests/
    test_controller.py
    test_sandbox.py
    test_evaluator.py
    test_archive.py
    test_providers.py
    test_plane_isolation.py
```

## Package goals

The repository should support entering a reproducible shell and driving the loop
through mise tasks (which wrap `uv run`):

```zsh
nix develop                          # or `direnv allow` once, then auto-enter
mise install                         # python + uv at pinned versions
mise run sync                        # uv sync

mise run run-task -- tasks/code_improver/task_001
mise run summarize
uv run siro propose-meta-change runs/attempts.jsonl
```

The underlying `uv run siro ...` commands remain the canonical interface; mise
tasks are thin, discoverable wrappers (`mise tasks`).

## Configuration

Ship checked-in example configs per tier. `tier0.local.yaml` is the offline default; `tier1.frontier.yaml` adds the providers / budget / egress blocks documented in `07_model_providers_and_tiers.md`. Selecting a tier is config-only — never a code change.

`config/tier0.local.yaml`:

```yaml
tier: 0

providers:
  local:
    backend: llamacpp                       # OpenAI-compatible llama.cpp / LlamaBarn server
    base_url: http://127.0.0.1:2276/v1
    name: unsloth/Qwen3.6-27B-GGUF:Q8_0
    timeout_seconds: 120

agent_models:        # every role local at Tier 0
  default: local

sandbox:
  timeout_seconds: 10
  network: disabled       # execution plane is always offline
  max_attempts_per_task: 20

evaluation:
  primary_metric: pytest_pass_rate
  require_reproducibility: true

safety:
  allow_network: false    # control-plane egress; off at Tier 0
  allow_package_install: false
  allow_evaluator_edits: false
```

For `tier1.frontier.yaml`, keep the `sandbox` and `safety.allow_evaluator_edits`/`allow_package_install` blocks identical, set `tier: 1`, add the `providers` (anthropic/openai), `agent_models` per-role bindings, `budget` (token/USD ceilings), and `network.egress: allowlist` blocks from `07_model_providers_and_tiers.md`. The execution-plane `sandbox.network` stays `disabled` at every tier.

## Durable storage: migration, export, backup (Goal 16)

JSONL under `runs/` is the **default, transparent** audit format and the source of truth for Tier 0 local work — nothing about it changes. The `siro.storage` layer adds a uniform interface over every append-only stream (`attempts`, `research_attempts`, `training_attempts`, `model_calls`, `memory`, `meta_changes`, `governance`, `artifacts`, `deployments`) with two backends, selected by an optional `storage` config block:

```yaml
storage:
  backend: jsonl        # jsonl (default) | sqlite
  path: runs/siro.db    # SQLite database path when backend=sqlite
```

The SQLite backend keeps one append-only `events` table with schema migrations (`schema_migrations`), an idempotency key per record (`UNIQUE(stream, idempotency_key)` — a repeated write with the same key is a no-op), and per-stream hash chaining for `governance` and `artifacts` (each row links to the previous via a SHA-256 chain, so post-hoc edits are detectable).

Operational workflow (all `uv run siro`):

- **Migrate** — create or upgrade the schema: `storage-migrate --store runs/siro.db`. Safe to run repeatedly; it applies only pending migrations (empty DB → latest, or an older schema version → latest, preserving existing rows).
- **Import** — load the existing JSONL archives into SQLite (idempotent): `storage-import --store runs/siro.db`. Re-running imports only new records.
- **Export / backup** — write SQLite back to JSONL files byte-compatible with the existing readers: `storage-export --store runs/siro.db --to-dir runs/export`. This is the backup/restore path: the exported `*.jsonl` files load unchanged through `JSONLArchive`/`summarize-*`. For a raw backup, copy the SQLite file (WAL mode) or keep the JSONL export under version control.
- **Verify** — check tamper-evident hash chains: `storage-verify --store runs/siro.db` (all chained streams) or `--stream governance`.

Summaries read through the interface: `summarize-runs --store runs/siro.db` and `summarize-research --store runs/siro.db` query SQLite, while the default (no `--store`) reads JSONL exactly as before. The SQLite store is **never** a hidden dependency for Tier 0 — it is opt-in — and migrations and tamper-evidence policy are human-gated, never agent-editable.
