# Goal Prompt 25 — Chip-Design Pack

## Goal

Ship a **chip-design domain pack** whose candidates are RTL/HDL or synthesis recipes and whose
evaluator is an open-source EDA flow. Correctness is checked by **formal equivalence** against a
controller-owned reference (Regime A); power/performance/area (PPA) is measured by synthesis
(Regime B). This exercises the full generalization stack — the Goal 22 pack interface plus the
Goal 24 statistical gate — on a domain whose toolchain is heavier but still fully offline
(`../18_generalizing_to_sciences.md`).

Depends on Goal 22 (the pack interface), Goal 24 (the statistical reproducibility gate, for noisy
PPA), and Goal 09 (the research task shape).

## Requirements

- **A `packs/chip/` pack** conforming to the Goal 22 layout. Its tasks declare regime `exact` for
  the correctness metric and `statistical` for the PPA metrics (or split a correctness gate from a
  PPA objective).
- **An EDA evaluator adapter.** `evaluator.py` runs an open-source flow offline under a hard
  timeout: a **formal-equivalence check** (e.g. Yosys + SymbiYosys / an equivalence engine)
  against a controller-owned reference design — a candidate that is not equivalent fails outright,
  so a fast-but-wrong design cannot win — and a **synthesis pass** (e.g. Yosys / OpenROAD) that
  reports PPA. It emits a `MetricRecord`: primary = a PPA objective (e.g. area or delay, with the
  correct direction), gated on equivalence; secondary = the other PPA terms.
- **The reference and testbench are read-only to agents.** The candidate edits only the design
  surface declared in `task.json`; the equivalence reference, the synthesis constraints, and any
  held-out vectors are controller-owned (`SIRO_HIDDEN_PATH`), never editable.
- **Offline, pinned toolchain.** The EDA tools are provisioned by nix/mise, never installed by the
  loop; the execution plane has no network. Synthesis runtime noise is handled by the Goal 24
  statistical policy (promote PPA on a confidence bound, not a single noisy run).
- **Seed task families** with stable, objective metrics — at minimum: reduce area/delay of a small
  combinational or sequential block while remaining formally equivalent; and improve a synthesis
  recipe for a fixed design. Each ships `task.json`, `brief.md`, `baseline/`, and held-out checks.
- **Role-prompt specialization** for hardware (Implementation reasons about RTL and timing,
  Literature cites the pinned references), with the org roles and lifecycle otherwise unchanged.
- **Document** the pack in `../18_generalizing_to_sciences.md`, the README status entry, and
  `../implementation_status.md`.

## Acceptance criteria

- The org runs a full lifecycle on each chip task family and writes structured memory entries
  (improved designs and negatives).
- A candidate that is **not** formally equivalent to the reference never promotes, regardless of
  its PPA (covered by a test).
- PPA improvements promote only when they clear the Goal 24 confidence bound; a within-noise
  synthesis fluctuation does not promote.
- The reference, testbench, and constraints are read-only to agents; editing one requires human
  approval (edit-surface enforcement covered by a test).
- The pack runs by config only at the configured tiers, with no core-loop code change.
- `uv run siro check-docs` passes.

## Constraints

- **No network or package installation in the execution plane.** EDA tools are pinned and offline;
  no eval-time fetch of cells, PDKs, or libraries.
- **Correctness gates performance.** Equivalence is a hard precondition for any PPA credit — a
  loophole that wins PPA by changing behavior must fail.
- **Read-only reference and constraints.** The candidate edits only its declared design surface.
- **Config-only selection; no bound moves.** Selecting the pack or its tier is config; the gates,
  budgets, and sandbox are inherited unchanged.

## Self-improvement

This goal runs the bounded loop (`../13_self_improvement_loop.md`) on hardware design, combining a
formal correctness gate with a noise-aware PPA objective.

- **Records**: each candidate's equivalence result and PPA metrics (with Goal 24 replicate
  intervals) and a failure signature; negatives are first-class.
- **Reflects / proposes**: the meta-loop may propose chip-pack-local heuristics (which
  transformations to try), reviewed like any meta-change.
- **Validated / gated**: equivalence + the statistical PPA gate are the authority for promotion;
  no design promotes on model judgment or a single noisy synthesis run.
- **Bounds**: expanding the design set, swapping the reference flow, or raising the budget is a
  human-gated change; references and constraints are read-only to agents.
