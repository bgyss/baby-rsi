# Generalizing the Framework to the Sciences

This is a design exploration with the first packaging step now built. It proposes how `siro` — today
exercised on ML/software self-improvement — generalizes into a domain-agnostic research
organization that can run the same bounded, auditable loop over mathematics, chip design,
the physical sciences, drug discovery, and the life sciences. It motivates a small set of
future goal prompts (sketched in [Staging](#staging)); the Goal 22 domain-pack interface,
the Goal 23 mathematics pack, and the Goal 24 statistical reproducibility gate (Regime B)
have landed, while the chip-design pack and the external-experiment regime (Regime C) remain
staged work.

The thesis: **the core loop is already domain-agnostic, and the work is not a rewrite — it
is hardening four existing seams and generalizing two gates.** The non-negotiable invariants
([`05`](05_evaluation_and_safety_gates.md), [CLAUDE.md](../CLAUDE.md)) carry over unchanged;
in fact the Tier-2 governance machinery ([`10`](goal_prompts/goal_10_governance_gate.md)–[`12`](goal_prompts/goal_12_governed_model_training.md))
turns out to be exactly what the hardest sciences need.

## What is already domain-agnostic

Nothing in the controller, experiment lifecycle, gates, research memory, governance, or the
agent org names a domain. The agent roles (Hypothesis → Literature → Implementation → Eval →
Safety → Interpretation → Memory, [`03`](03_agent_roles.md)) are generic; the six-step
self-improvement cycle (observe → reflect → propose → validate → gate → record,
[`13`](13_self_improvement_loop.md)) is generic; the plane split (control plane reasons,
execution plane runs candidates offline, [`01`](01_system_architecture.md)) is generic.

The coupling to ML/software lives in exactly **four swappable seams**:

1. **Seeded task families** — `packs/ml/tasks/{algorithm,training,policy,...}/`. These happen
   to be in-silico Python; nothing requires that.
2. **The evaluator contract** — each task's `eval.py` prints a JSON `MetricRecord` on its last
   stdout line, run inside the offline sandbox (`Sandbox.run_research`, `siro.research`). This
   is the authority for promotion. It is already a clean, language- and domain-neutral boundary
   (a process that emits a metric), just not *formalized* as an interface.
3. **Role prompts and the reference corpus** — `prompts/` plus what the Literature role can cite.
4. **The execution-plane assumption** — that an "experiment" is a deterministic, offline,
   pure-Python computation bounded by a subprocess timeout.

Seams 1–3 are *content*: you swap them per domain without touching the core. Seam 4 is the one
real architectural constraint, and it is what decides how cleanly each science plugs in.

## The organizing idea: classify a science by its evaluator

Whether a science fits is entirely a question of **what its ground-truth oracle is** and how
that oracle interacts with the offline execution plane. Three regimes:

| Regime | Oracle | Fit today | Example sciences |
|---|---|---|---|
| **A — Formal / exact** | Deterministic checker, offline, reproducible bit-for-bit | Drop-in. Matches the existing reproducibility gate as-is. | **Mathematics** (Lean/Coq/Isabelle proof checking), **chip design** (formal equivalence, e.g. Yosys + SymbiYosys), SAT/combinatorics, formal verification |
| **B — Stochastic / in-silico** | Simulator or surrogate model, offline-able but noisy | Fits, but the reproducibility gate must move from *exact-match* to *noise-aware*. | **Computational physics** (numerical PDE / molecular-dynamics simulation), **chip PPA** (OpenROAD synthesis: power/performance/area), **in-silico drug** (docking scores, ADMET predictors, retrosynthesis feasibility) |
| **C — External-world oracle** | A real-world action: wet-lab assay, fab tape-out, instrument time, paid compute | Only through governance — the experiment *is* an irreversible, expensive, real action. | **Drug discovery / life sciences** (wet-lab validation), **experimental physics**, anything requiring physical fabrication or measurement |

The load-bearing realization: **Regime C is not a missing capability — it is precisely what the
Tier-2 governance gate was built for.** A wet-lab assay or a tape-out is a `GovernedAction`
([`10`](goal_prompts/goal_10_governance_gate.md)): agents *propose*, a human *approves*, it is
budget-bounded, logged to the append-only approval ledger, and irreversible. The bound "agents
request, humans approve" is already enforced. So supporting Regime C extends an existing
mechanism rather than inventing a new one — and the execution plane stays offline throughout.

### Per-domain mapping

- **Mathematics (Regime A).** Candidate = a proof term or a construction; `eval.py` = run a
  proof checker (Lean `lake build`, Coq, Isabelle) on the candidate against a fixed theorem
  statement and emit pass/fail plus secondary metrics (proof length, dependency count). Fully
  deterministic and offline. The initial `packs/math/` implementation uses Lean/Lake, hidden
  theorem checks, and exact reruns to stress only the domain-pack interface and nothing else.
- **Chip design (Regime A → B).** Candidate = RTL/HDL or a synthesis recipe; evaluator = an
  open-source EDA flow. Correctness via formal equivalence against a reference (Regime A);
  power/performance/area via synthesis (Regime B — tool runtime is noisy, so promote on a
  stable proxy or a confidence bound). The edit-surface / read-only-evaluator invariants map
  directly onto "the candidate may edit the design, never the testbench or the equivalence
  reference."
- **Physical sciences (Regime B, sometimes C).** Computational/theoretical physics — numerical
  simulation, symbolic derivation checked against a reference solver — fits Regime B. Bench
  experimental physics is Regime C.
- **Drug discovery / life sciences (Regime B for screening, C for truth).** In-silico screening
  (docking, property prediction, retrosynthesis feasibility) is Regime B and runs offline today
  with surrogate models shipped as fixtures. The actual ground truth — does the molecule bind,
  is it non-toxic — is a wet-lab assay, Regime C, and must route through governance. This is the
  canonical two-stage science: cheap in-silico proposal ranking, then a small number of
  human-approved expensive confirmations.

## What needs to be built — two seam-hardenings and one extension

### 1. A formal domain-pack interface (hardening seams 1–3)

Goal 22 promotes the implicit "`eval.py` prints JSON" convention into a typed, registrable
**`EvaluatorAdapter`**, and bundles everything domain-specific into a **domain pack**:

```
packs/<domain>/
  pack.toml            # id, declared evaluator regime (A/B/C), required tools, tier floor
  evaluator.py         # an EvaluatorAdapter: how to score a candidate, emit a MetricRecord
  tasks/               # task families for this domain (same task.json + brief.md + baseline/ + hidden/ shape)
  prompts/             # role-prompt specializations for this domain
  references/          # the citable corpus for the Literature role
  tools.allow          # the per-domain control-plane tool whitelist
```

The core loop loads a pack by config (`pack: ml` by default); it never hardcodes a domain.
"Add a science" becomes "ship a pack," reviewed as a unit. The adapter declares its regime so
the controller knows which reproducibility policy (below) to apply. The current ML families now
live in `packs/ml/`, proving the interface against known-good behavior before any new science is
added. A pack's `tools.allow` may narrow the control-plane toolset but cannot grant tools outside
the global allowlist.

### 2. Generalize the reproducibility / promotion gate (exact → statistical) — implemented (Goal 24)

Promotion previously required near-bit-exact rerun agreement (`REPRO_TOLERANCE = 1e-9` in
`siro.research`). Goal 24 generalized this into a spectrum, selected by the pack's declared
regime:

- **exact** — proof checkers, formal equivalence (Regime A): reruns must agree bit-for-bit.
- **seeded-deterministic** — the prior behavior (seeded in-silico) within `REPRO_TOLERANCE`.
- **statistical** — the candidate and incumbent are scored across N **fixed seeded replicates**
  (paired on the same seed via `SIRO_EVAL_SEED`), and the candidate promotes only if a
  direction-aware **confidence interval** on the primary-metric delta excludes zero; a lucky or
  noisy win cannot promote. Declared secondaries are checked the same way.

`research_improves` / `research_reproducibility_gate` now dispatch on the declared regime; the
`StatisticalPolicy` (seeds, N, confidence) is a controller/config bound a candidate cannot set
or read, and the seeds + computed interval are recorded on the attempt so the noisy *decision*
is itself reproducible. The invariant "no promotion on noise" is preserved — generalized, not
relaxed. Human approval is still required to widen N, the confidence level, the seed policy, or
any benchmark or budget. This unlocks **Regime B** for every pack that follows.

### 3. A governed external-experiment boundary (Regime C)

Add a clean lifecycle `propose → approve → execute (human / robotic) → ingest`:

- The org still only *reasons and proposes*; the execution plane stays offline.
- The external step is a new `GovernedAction` variant (e.g. `EXTERNAL_EXPERIMENT` with a typed
  payload: assay, fab submit, instrument run), authorized through the existing approval ledger
  and compute-budget tiers ([`11`](goal_prompts/goal_11_governed_compute_scaleup.md)).
- A human (or an instrument under human authority) executes the approved action and returns a
  **signed result record**; the controller ingests it as the metric for that candidate.
- Negative results are first-class, exactly as in-silico negatives are.

Every invariant holds: no candidate code touches the network or an instrument; the irreversible,
expensive action is human-approved and bound to the exact proposal via `governed_action_hash`;
the audit trail is end-to-end.

The agent org itself needs **no structural change** for any of this — only different prompts,
tools, and references per pack.

## Staging

A suggested goal-prompt sequence, ordered so each step is independently valuable and the
riskiest machinery comes only after the cheapest domain has proven the seam. Each new goal
prompt carries its own `## Self-improvement` section, per the [`13`](13_self_improvement_loop.md)
contract — the outer meta-loop improves *how packs propose and select*, bounded identically.

1. **Domain-pack interface + `EvaluatorAdapter`** — implemented in Goal 22; refactor only;
   reseats the existing ML families as `packs/ml/`. No new science.
2. **First non-ML pack: mathematics via Lean** — implemented in Goal 23; pure Regime A with
   hidden theorem checks, `lake build`, and proof-length/dependency metrics.
3. **Statistical reproducibility gate** — implemented in Goal 24; unlocks Regime B (confidence
   bound across fixed seeded replicates).
4. **Chip-design pack** — Yosys / OpenROAD; Regime A correctness + Regime B PPA.
5. **Governed external-experiment boundary** — the Regime-C `GovernedAction` lifecycle.
6. **Drug / life-science pack** — in-silico screening on (3), wet-lab confirmation on (5).

## Invariants this exploration must not break

The point of the project survives generalization unchanged ([CLAUDE.md](../CLAUDE.md),
[`05`](05_evaluation_and_safety_gates.md)): plane isolation (candidate execution offline, no
credentials, hard timeouts); read-only evaluator and safety code; objective, reproducible
evaluation over model self-judgment; cross-model review at Tier ≥ 1; budget ceilings that halt
and escalate; promotion only through the gates; humans approve every irreversible / high-budget /
external action; negative results retained. A domain pack is reviewed against these the same way
a meta-change is — and a pack that widens any of them is a contract deviation, not a feature.

## See also

- [`01_system_architecture.md`](01_system_architecture.md) — the plane split a pack must respect.
- [`05_evaluation_and_safety_gates.md`](05_evaluation_and_safety_gates.md) — the gates a pack inherits.
- [`10_governance_gate.md`](goal_prompts/goal_10_governance_gate.md) — the mechanism Regime C extends.
- [`13_self_improvement_loop.md`](13_self_improvement_loop.md) — the bounded cycle every pack runs.
