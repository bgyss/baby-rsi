# Goal Prompt 22 — Domain-Pack Interface and Evaluator Adapter

## Goal

Turn the implicit "a research task is an offline `eval.py` that prints a `MetricRecord`"
convention into a **formal, registrable domain-pack interface**, so a new science is added by
*shipping a pack* rather than by editing the core loop. This is the foundation for generalizing
`siro` beyond ML/software (`../18_generalizing_to_sciences.md`): it hardens the four swappable
seams (task families, evaluator contract, role prompts/corpus, tool whitelist) into one bundled,
reviewable unit and reseats today's ML families as the first pack to prove the interface against
known-good behavior.

This is a refactor and an interface goal, **not** a new science and **not** a new capability. The
loop, lifecycle, gates, governance, memory, and bounds are unchanged; only the *packaging* of
domain content becomes explicit. No new domain is added here — Goals 23–27 ship the first
non-ML packs on top of this interface.

Depends on Goals 04 (the promotion gates a pack inherits), 08 (the org and its roles), 09 (the
research task shape and `Sandbox.run_research`), and 13 (the docs consistency contract).

## Requirements

- **A typed `EvaluatorAdapter`.** Define a Pydantic/Protocol contract (in a new
  `src/siro/packs.py`, or `src/siro/domains/`) that names how a candidate is scored: it takes a
  prepared sandbox working copy plus the controller-owned held-out path and returns the existing
  `MetricRecord` (primary + secondary + direction). The current research evaluator (`eval.py`
  printing JSON on its last stdout line, run via `Sandbox.run_research`) becomes the default
  adapter implementation, unchanged in behavior.
- **A declared evaluator regime.** Each adapter declares its regime — `exact`,
  `seeded-deterministic`, or `statistical` (`../18_generalizing_to_sciences.md`) — so the
  controller knows which reproducibility policy to apply. Goal 22 ships only `exact` and
  `seeded-deterministic` (the behavior that exists today); `statistical` is reserved for Goal 24
  and may be declared-but-unsupported until then.
- **A domain-pack layout.** Define and document a pack directory shape that bundles everything
  domain-specific:

  ```text
  packs/<domain>/
    pack.toml        # id, title, evaluator regime, required tools, tier floor, version
    evaluator.py     # the EvaluatorAdapter for this domain
    tasks/           # task families (the existing task.json + brief.md + baseline/ + hidden/ shape)
    prompts/         # role-prompt specializations for this domain (optional; falls back to defaults)
    references/      # the citable corpus for the Literature role (optional)
    tools.allow      # the per-domain control-plane tool whitelist (subset of the global toolset)
  ```

- **A pack registry / loader.** `load_pack(id)` discovers and validates a pack, and the
  controller/orchestrator select a pack by **config only** (a `pack:` key in `config/tierN.*.yaml`),
  never by hardcoding. An unknown or malformed pack fails closed with a clear error.
- **Reseat the ML families as `packs/ml/`.** Move the existing `tasks/research/{algorithm,
  training,policy,...}` families and their evaluators under a built-in `ml` pack, with the default
  config selecting it, so existing commands and results are unchanged. This is the conformance
  test for the interface.
- **The tool whitelist is per-pack and intersective.** A pack may *narrow* the control-plane
  toolset for its agents but may never grant a tool outside the global allowlist (no shell, no
  network). Widening the toolset is a human-gated change, reviewed like a meta-change.
- **Keep the surface documented.** Update `../18_generalizing_to_sciences.md`, the README
  "Implementation Status" entry, and `../implementation_status.md` to describe the pack interface
  and the `packs/ml/` reseating.

## Acceptance criteria

- Existing research commands (`run-research`, `summarize-research`) produce the same results
  through the `packs/ml/` pack as before the refactor (covered by tests; results reproducible).
- A pack is selected by config alone; switching packs requires no code change, and an unknown
  pack id fails closed.
- The `EvaluatorAdapter` contract is typed and tested, including its declared regime; the default
  adapter reproduces the current `eval.py`/`MetricRecord` behavior bit-for-bit on a fixture task.
- A pack's `tools.allow` can only narrow, never widen, the global control-plane toolset (covered
  by a test that a pack requesting a non-allowlisted tool fails closed).
- `uv run siro check-docs` passes: manifest, README status entry, and Self-improvement section
  stay consistent.

## Constraints

- **No new domain and no new capability.** Goal 22 only formalizes packaging; behavior is
  byte-for-byte preserved for the ML pack.
- **Plane isolation is unchanged.** A pack's evaluator runs in the existing offline execution
  plane (no network, scrubbed env, hard timeout, held-out data via `SIRO_HIDDEN_PATH`). A pack
  cannot relax the sandbox or reach the network.
- **Read-only evaluator to agents.** The pack evaluator is controller-owned; a candidate can
  never supply or rewrite the adapter that scores it. Edit surfaces stay allow-listed per task.
- **Config-only selection.** Choosing a pack, like choosing a tier, is config, never code.
- **Additive only.** Default behavior and existing command semantics are preserved; the only
  additions are the adapter interface, the pack layout, and the loader.

## Self-improvement

This goal makes the **unit of the self-improvement loop portable across sciences** without
moving any bound (`../13_self_improvement_loop.md`): the same observe → reflect → propose →
validate → gate → record cycle now runs against a *pack* instead of a hardcoded task family.

- **Records**: pack id and version are stamped onto every attempt and memory entry, so reflection
  can compare progress within and across packs; negatives included.
- **Reflects / proposes**: the meta-loop may propose pack-local changes (prompts, selection
  heuristics) the same way it proposes process changes today.
- **Validated / gated**: a pack's evaluator remains the authority for promotion; the promotion
  and safety gates are inherited unchanged, not re-implemented per pack.
- **Bounds**: a pack may *narrow* but never *widen* tools, budgets, or the execution-plane
  sandbox; widening any bound is a human-gated change reviewed like a meta-change.
