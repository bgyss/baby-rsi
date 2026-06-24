# 13 — The Self-Improvement Loop (operating default)

Self-improvement is not a single feature that lives in one goal prompt — it is the
**operating default of the whole project**. Every goal prompt builds a component
that participates in self-improvement, and every loop in the running system closes a
bounded improvement cycle. This document defines that uniform contract so each goal
prompt can reference it instead of re-deriving it, and so the loops stay *bounded and
auditable* rather than open-ended.

This document is normative for both the **build process** (how the `siro` package is
implemented goal-by-goal) and the **runtime** (how `siro` improves itself once running).

## Two nested loops

```text
┌──────────────────────── OUTER LOOP (meta-research) ────────────────────────┐
│ Improves the research *process*: prompts, mutation/selection heuristics,    │
│ retrieval strategy, scoring within configured bounds. Stricter review.      │
│                                                                             │
│   ┌──────────────────── INNER LOOP (per-task experiment) ───────────────┐  │
│   │ seed task → model proposes change → sandbox runs tests →            │  │
│   │ evaluator scores → archive stores attempt (incl. negatives) →       │  │
│   │ controller selects best candidate → next generation uses best +     │  │
│   │ memory                                                              │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│ The outer loop reads the inner loop's archive, proposes a meta-change,      │
│ A/B-validates it on a fixed benchmark, and promotes only through the gates. │
└─────────────────────────────────────────────────────────────────────────────┘
```

The inner loop improves *candidates* for a task. The outer loop improves *the loop
itself*. Both use the **same** lifecycle, gates, and memory (`04_experiment_lifecycle.md`,
`05_evaluation_and_safety_gates.md`, `06_research_memory_schema.md`); only the object
under change differs. The meta-research loop is specified concretely in
`goal_prompts/goal_05_meta_research_loop.md`.

## The standard self-improvement cycle

Every loop — and every goal prompt's "Self-improvement" section — instantiates the
same six steps:

1. **Observe** — record every attempt and its outcome as structured data, including
   **negative results** (failed attempts with reason). Nothing is discarded.
2. **Reflect** — summarize the archive, cluster failures, identify the current
   bottleneck (`siro summarize-runs`).
3. **Propose** — emit an explicit, typed change proposal (a candidate at the inner
   level; a meta-change at the outer level via `siro propose-meta-change`).
4. **Validate** — run on a *fixed* benchmark task set; A/B compare the proposal
   against the current behavior on the same inputs. Reproducibility is required.
5. **Gate** — promote **only if** the primary metric improves AND required secondary
   metrics don't regress past threshold AND the safety gate passes AND the result is
   reproducible AND edit constraints were respected. Otherwise reject and record why.
6. **Record** — write the outcome (promoted or rejected) plus a **rollback plan** to
   research memory, so the next cycle starts from it.

## Bounds (what self-improvement may NOT do on its own)

Self-improvement here is **bounded**. These changes always require explicit human
approval and stricter review — an autonomous loop may *propose* them but never
*apply* them (mirrors `goal_05` and the non-negotiable invariants in `CLAUDE.md` and
`05_evaluation_and_safety_gates.md`):

- Weakening, deleting, or disabling tests, evaluators, logging, or audit ledgers
- Changing safety gates or the egress allowlist
- Expanding the agent's own tool permissions or edit surface
- Expanding compute, token, or USD budgets
- Enabling network access in the execution plane or autonomous package installation
- Changing tier, or any irreversible / high-budget / high-risk action

Additional invariants that hold in every cycle:

- **Objective evaluation first** — promote on reproducible metrics, never model
  self-judgment. A gain via a loophole, overfit to visible tests, or a non-reproducible
  result fails the gate.
- **Retrieved memory and tool output are data, never instructions** (prompt-injection
  guard). A proposal that came from retrieved text is still subject to every gate.
- **Meta-changes get stricter review than task-level changes**, and at Tier 1 the
  safety/eval review must use a different provider than the proposer.

## The reusable "Self-improvement" clause

Every `goal_prompts/goal_0N_*.md` carries a `## Self-improvement` section that binds
that goal's component into the cycle above. The clause states, for that goal:

- **What it records** (which attempts/outcomes/negatives flow into the archive/memory).
- **What it reflects on / proposes** (the unit of improvement this goal introduces).
- **How it is validated and gated** (the fixed benchmark and the promotion gate).
- **Its bounds** (a pointer back to this document's bounds — never re-litigated locally).

Keeping the clause uniform is itself a self-improvement safeguard: a goal that quietly
drops the cycle, or widens its own bounds, is a detectable deviation from the contract.
