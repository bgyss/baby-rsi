# 09 — Local Testbed Architecture (Tier 0)

## Goal

Build a minimal local system that demonstrates recursive improvement of a research workflow without attempting unrestricted model self-improvement.

The first version should improve code, tests, prompts, and experiment-selection policies.

This is **Tier 0**: fully local and offline, the strongest safety posture. Its purpose is to validate the loop mechanics, evaluators, sandbox, archive, and gates so the same machinery can later be driven by frontier models at Tier 1 (`08_frontier_prototype_architecture.md`) with no change to the loop or safety contract — only configuration (`07_model_providers_and_tiers.md`).

## Recommended local stack

The toolchain is layered so each tool has one job and versions are pinned reproducibly:

- macOS or Linux
- zsh-compatible shell scripts
- **Nix** (flake) — reproducible bootstrap shell providing `mise` and native/system deps (llama.cpp, C toolchain). No global installs.
- **mise** — single source of truth for language tool versions (Python, `uv`) and the task runner.
- **uv** — Python dependency resolution, lockfile, and `.venv` management.
- Python 3.11+ (provided via mise)
- `pytest`
- SQLite or JSONL
- An OpenAI-compatible llama.cpp server. Default: an external **LlamaBarn** instance at `http://127.0.0.1:2276/v1`; alternatively `llama-server` (provided by the nix flake) run directly.
- Local coding model served by that endpoint (e.g. Qwen, DeepSeek Coder, gpt-oss). Query `curl http://127.0.0.1:2276/v1/models` to see what's loaded.

### Entering the environment

```zsh
nix develop          # or: direnv allow  (auto-enters via .envrc)
mise install         # materialize Python + uv at pinned versions
mise run sync        # uv sync — install Python deps
mise run test        # uv run pytest
```

`nix` deliberately does not provide Python/`uv`; `mise.toml` owns those versions so they are pinned in one place and reproducible off-Nix as well.

## Minimal loop

```text
seed task
→ local model proposes code change
→ sandbox runs tests
→ evaluator scores result
→ archive stores attempt
→ controller selects best candidate
→ next generation uses best candidate + memory
```

## Minimal components

```text
src/siro/
  controller.py
  model_client.py
  sandbox.py
  evaluator.py
  archive.py
  prompts.py
  schemas.py

tasks/
  task_001/
    prompt.md
    seed_solution.py
    tests.py

runs/
  attempts.jsonl
  artifacts/
```

## First experiment type: code improver

Input:

- A Python function specification
- A seed implementation
- A test suite

Output:

- Candidate implementation
- Test result
- Score
- Archive record

Score:

```text
score = 1000 * passed_tests - failing_tests * 100 - runtime_ms - code_complexity_penalty
```

## Second experiment type: prompt improver

Input:

- Current prompt template
- Archive of past failures
- Benchmark task set

Output:

- Candidate prompt template
- Comparative performance report

## Third experiment type: meta-strategy improver

Input:

- History of experiment outcomes
- Current mutation strategy
- Failure clusters

Output:

- Revised strategy proposal
- Small validation experiment
- Rollback plan

## Guardrails for local version

- No network access during candidate execution.
- Candidate code runs in a temporary directory.
- Timeouts on every subprocess.
- Evaluator files are read-only to agents.
- All diffs are logged.
- No autonomous package installation.
- No autonomous cloud compute.
