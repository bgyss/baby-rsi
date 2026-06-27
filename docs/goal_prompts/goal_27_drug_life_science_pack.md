# Goal Prompt 27 — Drug and Life-Science Pack

## Goal

Ship the **two-stage drug/life-science pack**, the canonical science that combines both new
regimes: cheap **in-silico screening** (Regime B — docking scores, property/ADMET prediction,
retrosynthesis feasibility) ranks candidates offline, and a small number of human-approved
**wet-lab confirmations** (Regime C) provide ground truth
(`../18_generalizing_to_sciences.md`). It is the capstone of the generalization: it rides on the
pack interface (Goal 22), the statistical gate (Goal 24), and the governed external-experiment
boundary (Goal 26), demonstrating the whole stack on a life-science workflow.

Depends on Goals 22 (pack interface), 24 (statistical reproducibility gate), and 26 (governed
external-experiment boundary).

## Requirements

- **A `packs/life_science/` pack** conforming to the Goal 22 layout, with two evaluator stages:
  - **Screening (Regime B, offline).** `evaluator.py` scores a candidate molecule/sequence with
    surrogate models and physics-based proxies (docking, predicted properties, synthesizability),
    shipped as **pinned offline fixtures/weights** — no eval-time download. Emits a `MetricRecord`
    promoted under the Goal 24 statistical policy.
  - **Confirmation (Regime C, governed).** The highest-ranked screened candidates are proposed as
    Goal 26 external experiments (a wet-lab assay); promotion to "confirmed" requires an ingested,
    signed assay result bound to a human approval. The execution plane runs no wet-lab step.
- **Screening gates confirmation.** A candidate may only be *proposed* for a (costly, irreversible)
  wet-lab confirmation after it clears the in-silico screen, so expensive confirmations are few and
  high-value (promotion-before-budget, Goal 11 pattern).
- **The screen and its data are read-only to agents.** Surrogate weights, held-out targets, and
  assay protocols are controller-owned (`SIRO_HIDDEN_PATH`); a candidate edits only its declared
  surface (the molecule/sequence representation), never the scorer or the held-out target.
- **No real-world action in the execution plane.** All in-silico work is offline against pinned
  fixtures; the only outside-world step is the Goal 26 governed, human-executed assay.
- **Role-prompt specialization** for medicinal chemistry / biology (Implementation reasons about
  structure and properties, Literature cites the pinned corpus), with the org roles and lifecycle
  otherwise unchanged.
- **Safety framing.** The pack's `brief.md` and constraints state the dual-use posture explicitly:
  the loop proposes and screens in-silico; any physical synthesis or assay is human-gated through
  governance, default-deny.
- **Document** the pack in `../11_risks_and_controls.md`,
  `../18_generalizing_to_sciences.md`, the README status entry, and `../implementation_status.md`.

## Acceptance criteria

- The org runs the full two-stage lifecycle: in-silico screening promotes candidates under the
  Goal 24 statistical gate, and only screened candidates are proposed for a Goal 26 governed
  confirmation (covered by tests).
- A candidate promotes to "confirmed" only on an ingested, signed assay result bound to a live
  approval; no in-silico score alone yields a confirmation (covered by a test).
- The screen, its fixtures, and held-out targets are read-only to agents; editing one requires
  human approval (edit-surface enforcement covered by a test).
- The execution plane performs no synthesis or assay and holds no external credentials; all
  in-silico scoring is offline against pinned fixtures.
- Negative and null screening and assay results are archived with reason.
- `uv run siro check-docs` passes.

## Constraints

- **No network or package installation in the execution plane.** Surrogate models and data are
  pinned and offline; no eval-time download.
- **Screening before confirmation.** A wet-lab confirmation is proposed only for a candidate that
  cleared the in-silico screen; confirmations are governed, default-deny, irreversible-aware.
- **Agents request, humans approve.** No agent tool authorizes synthesis or an assay or attaches a
  result; the physical step is human-executed under Goal 26.
- **Read-only scorer and targets; config-only selection; no bound moves.** The pack inherits the
  existing gates, budgets, and sandbox; it may narrow its toolset but never widen it.

## Self-improvement

This goal runs the bounded loop (`../13_self_improvement_loop.md`) on a two-stage life-science
workflow: cheap offline screening drives the inner loop, and rare governed confirmations close it.

- **Records**: every screened and confirmed (or failed) candidate with its scores, replicate
  intervals, and — for confirmations — the signed assay provenance; negatives and nulls first-class.
- **Reflects / proposes**: the loop proposes which screened candidate is worth a costly assay,
  ranked by the in-silico screen, so confirmations are few and high-value.
- **Validated / gated**: in-silico promotion uses the Goal 24 statistical gate; confirmation
  requires a Goal 26 governed, signed objective result — never model judgment.
- **Bounds**: synthesis and assays are human-gated, default-deny, irreversible-aware; expanding the
  screen, the fixtures, or the assay scope is a governed change.
