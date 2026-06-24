# Goal Prompt 01 — Project Scaffold

## Goal

Create the initial repository scaffold for a bounded self-improving research organization testbed.

## Context

The project is not intended to create an unrestricted autonomous self-improving AI. It should implement a local, auditable, evaluator-grounded research automation loop.

## Requirements

Create a Python package named `siro` with:

```text
src/siro/
  __init__.py
  controller.py
  schemas.py
  model_client.py
  sandbox.py
  evaluator.py
  archive.py
  memory.py
  safety.py
  prompts.py
```

Create directories:

```text
tasks/
runs/
prompts/
tests/
```

Use:

- **Nix** flake (`flake.nix`) for a reproducible dev shell providing `mise` and native deps; `.envrc` (`use flake`) for direnv auto-entry
- **mise** (`mise.toml`) to pin Python 3.11 and `uv`, and to define task wrappers (`sync`, `test`, `lint`, `run-task`)
- **uv** for dependency management (`pyproject.toml` + checked-in `uv.lock`)
- `pytest` for tests
- Pydantic for schemas
- JSONL for the first archive implementation

## Acceptance criteria

- `nix develop` (or `direnv allow`) enters a working shell with `mise` available.
- `mise install` materializes Python 3.11 and `uv`; `mise run sync` resolves deps.
- `mise run test` (i.e. `uv run pytest`) passes.
- Package imports successfully.
- CLI stub exists: `uv run siro --help`.
- README explains the bounded local testbed purpose.
- No network, cloud, or fine-tuning functionality is implemented yet.

## Constraints

- Keep implementation minimal.
- Favor explicit schemas and auditability.
- Do not add autonomous package installation.

## Self-improvement

This goal lays the **substrate** every later self-improvement cycle runs on (`../13_self_improvement_loop.md`). It introduces no loop yet, but it must make the cycle *possible*:

- **Records**: create `runs/` (attempt archive + `model_calls.jsonl` audit ledger) and the `memory`/`archive` module stubs so later goals can *observe* and *record*.
- **Reflects / proposes**: stub the CLI surface the cycle uses — `siro summarize-runs` and `siro propose-meta-change` — even if they no-op for now.
- **Validated / gated**: `mise run test` is the standing gate; nothing promotes without it.
- **Bounds**: per `../13_self_improvement_loop.md` — no autonomous install, no network, no self-expanding permissions.
