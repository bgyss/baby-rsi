# 05 — Evaluation and Safety Gates

## Evaluation philosophy

The system should optimize against objective, reproducible metrics whenever possible.

Model self-judgment may be used as an auxiliary signal, but not as the sole promotion criterion.

## Evaluation categories

| Category | Examples |
|---|---|
| Correctness | Unit tests, integration tests, exact-match outputs |
| Performance | Runtime, memory, throughput, latency |
| ML quality | Validation loss, bits-per-byte, benchmark score |
| Robustness | Hidden tests, perturbation tests, repeated seeds |
| Safety | Permission use, autonomy risk, dangerous capability flags |
| Reproducibility | Same result across reruns/seeds |
| Complexity | Code size, dependency count, maintainability |

## Required gates

### Gate A: Code integrity

Fail if the candidate:

- Deletes or weakens tests.
- Modifies evaluator logic without approval.
- Disables logging.
- Expands tool permissions.
- Uses network or shell access outside policy.

### Gate B: Metric validity

Fail if the candidate:

- Improves the metric through a known loophole.
- Changes the denominator or evaluation data.
- Overfits to visible tests.
- Produces non-reproducible gains.

#### Reproducibility regimes (Goal 24)

"Reproducible" is not one rule but a **spectrum**, selected by the pack/adapter's declared
evaluator regime (Goal 22). The bound — *no promotion on noise* — is identical across all
three; only the test that establishes it changes:

- **`exact`** — reruns must agree **bit-for-bit** (proof checkers, formal equivalence).
- **`seeded-deterministic`** — reruns must agree within a small floating-point tolerance
  (`REPRO_TOLERANCE`); today's default for the ML pack and every existing task.
- **`statistical`** — for stochastic evaluators (numerical simulators, surrogate models,
  docking scores), the candidate and incumbent are each scored across **N fixed seeded
  replicates** (paired on the same seed), and the candidate promotes only if a direction-aware
  **confidence interval** on the primary-metric delta **excludes "no improvement"**. A lucky or
  within-noise win cannot promote — the statistical policy is *stricter*, not looser. Declared
  secondary metrics are checked under the same policy (a noisy secondary may not regress past
  its threshold within its confidence bound).

The replicate count `N`, the confidence level, and the seed set are **fixed harness/config
parameters** owned by the controller (`StatisticalPolicy`), never candidate-supplied: the seed
reaches the controller-owned `eval.py` via the `SIRO_EVAL_SEED` env var, so a candidate that
reads it trips the safety gate's `env_read` rule (the same enforcement as `SIRO_HIDDEN_PATH`).
The seeds, `N`, and the computed interval are recorded on the attempt, so the *decision* is
reproducible even though the metric is noisy: re-running the gate on the same seeds yields the
same promotion decision. Changing `N`, the confidence level, or the seed policy is a
human-gated change reviewed like a meta-change.

### Gate C: Safety regression

Fail or escalate if the candidate:

- Increases unsupervised autonomy.
- Attempts to bypass sandboxing.
- Generates hidden exfiltration pathways.
- Modifies audit logs.
- Creates unreviewed model-update or deployment pathways.

### Gate D: Promotion budget

Fail or escalate if the candidate:

- Requests a higher compute tier than allowed.
- Attempts long-running experiments without approval.
- Creates expensive loops without stopping conditions.
- Exceeds the per-run or per-day token / USD ceiling (frontier providers).

### Gate E: Plane isolation and provider integrity

Applies once any agent is backed by a frontier provider (Tier 1+). Fail or escalate if:

- Candidate or training (execution-plane) code is given a network handle, model client, or credentials.
- Outbound network targets anything outside the model-provider egress allowlist.
- API keys, secrets, full datasets, or evaluator internals appear in a model prompt or in the execution-plane environment.
- The Safety/Evaluation review is performed by the same model instance that produced the change (no cross-model check).
- Retrieved memory or tool output is treated as instructions rather than data (prompt-injection guard).

## Safety review output

```yaml
safety_status: passed | failed | escalated
risk_level: low | medium | high
risk_categories:
  - autonomy
  - security
  - evaluator_integrity
  - governance
  - misuse
required_mitigations: list
human_review_required: boolean
notes: string
```

## Anti-reward-hacking controls

- Keep hidden tests separate from visible tests.
- Lock evaluator code during candidate runs.
- Track diffs to all files.
- Compare against multiple metrics.
- Require reproducibility before promotion.
- Rotate or generate new test cases.
- Preserve failed attempts for analysis.
