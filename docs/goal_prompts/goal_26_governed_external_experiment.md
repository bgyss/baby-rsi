# Goal Prompt 26 — Governed External-Experiment Boundary

## Goal

Add a **governed boundary for experiments whose ground truth is a real-world action** — a wet-lab
assay, a fabrication run, paid HPC, instrument time — so sciences in **Regime C — external-world
oracle** (`../18_generalizing_to_sciences.md`) can feed results back into the loop *without* the
execution plane ever reaching the outside world. The org still only reasons and proposes; an
approved, human-mediated action produces a signed result that the controller ingests as the
metric. This extends the Tier-2 governance machinery (Goals 10–12) rather than inventing a new
mechanism: an external experiment is a `GovernedAction`.

Depends on Goals 10 (the governance gate and approval ledger), 11 (compute-budget tiers and the
promotion-before-budget pattern), 19 (governance identity / two-person approval), and 22 (the pack
interface that declares a Regime-C evaluator).

## Requirements

- **A new `GovernedAction` variant** for external experiments (e.g. `EXTERNAL_EXPERIMENT`) with a
  typed payload describing the action class (assay / fabrication / instrument / external-compute),
  the exact proposal, and its cost/risk envelope. It is authorized through the existing
  append-only approval ledger and bound to the exact proposal via `governed_action_hash`.
- **A `propose → approve → execute → ingest` lifecycle:**
  - **Propose** — the org emits a typed external-experiment request (the candidate plus the
    measurement to run). No agent tool can authorize it (the bound: agents request, humans
    approve).
  - **Approve** — a human (with the Goal 19 identity/two-person rules where required) approves or
    denies; default-deny, expiry and revocation honored.
  - **Execute** — a human, or an instrument under human authority, performs the approved action
    **outside** `siro`. The execution plane runs no part of it and holds no credentials or network
    handle.
  - **Ingest** — the operator returns a **signed result record** (result value(s), provenance,
    operator id, timestamp) bound to the approved action hash; the controller validates the binding
    and ingests it as the candidate's `MetricRecord`.
- **A Regime-C evaluator adapter** (Goal 22) that, instead of running code, *blocks on an ingested
  signed result* for the approved action and returns its `MetricRecord`. Promotion is still decided
  by the objective ingested metric, under the appropriate Goal 24 reproducibility policy.
- **Negative results are first-class.** A failed or null external result is recorded with reason,
  never discarded — the expensive ones especially.
- **No auto-execution and no spoofing.** An ingested result is accepted only if it is bound to a
  live, matching approval; an unapproved, expired, revoked, or hash-mismatched result is rejected
  and logged.
- **Human-operated CLI verbs** to list pending external requests, attach a signed result, and view
  the audit trail — no agent tool performs the action or attaches a result on its own authority.
- **Document** the boundary in `../11_risks_and_controls.md`,
  `../18_generalizing_to_sciences.md`, the README status entry, and `../implementation_status.md`.

## Acceptance criteria

- The org can *propose* an external experiment but cannot execute it or self-approve it; approval
  requires an explicit human decision with a real approver id (covered by tests).
- An ingested result promotes a candidate only when bound to a live, matching approval; an
  unapproved / expired / revoked / hash-mismatched result is rejected and logged (covered by
  tests).
- The execution plane performs no external action and holds no credentials or network handle for
  one; the boundary is control-plane + human only.
- Negative and null external results are archived with reason.
- `uv run siro check-docs` passes.

## Constraints

- **Agents request, humans approve.** No agent tool authorizes an external experiment or attaches
  a result; `approve`/`deny`/`revoke` run only on explicit human instruction.
- **Plane isolation is absolute.** The execution plane never reaches an instrument, a lab, a fab,
  or paid compute, and never holds the credentials to. The external action happens entirely
  outside `siro`, under human authority.
- **Bound to the exact proposal.** An approval and its ingested result are bound by
  `governed_action_hash`; nothing else can satisfy them.
- **Default-deny, irreversible-aware.** External actions are treated as high-budget / irreversible
  and inherit the Goal 11 promotion-before-budget and Goal 19 identity rules.

## Self-improvement

This goal closes the **gate** and **record** steps of the bounded loop
(`../13_self_improvement_loop.md`) for real-world experiments: the loop may *propose* an expensive
external measurement but may only *apply* its result through human approval and an objective,
signed metric.

- **Records**: every external request, decision, and signed result lands in the approval ledger
  and the attempt archive with full provenance; negatives and nulls included.
- **Reflects / proposes**: the loop proposes which external experiment is worth its cost, ranked
  by cheaper in-silico screening (Regime B) first, so expensive confirmations are few and
  high-value.
- **Validated / gated**: promotion is decided by the ingested objective metric under governance,
  never by model judgment or an unbound result.
- **Bounds**: external experiments are human-gated, default-deny, irreversible-aware, and bound to
  the exact proposal; widening this boundary is itself a governed change.
