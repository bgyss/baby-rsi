# 04 — Experiment Lifecycle

## Experiment record

Every experiment should have a durable record:

```yaml
experiment_id: exp_YYYYMMDD_HHMMSS_slug
parent_experiment_id: optional
hypothesis: string
owner_agent: string
budget_tier: integer
allowed_edit_surfaces: list
baseline_commit: string
candidate_commit: string
status: proposed | running | passed | failed | promoted | rejected
primary_metric: string
secondary_metrics: list
safety_status: pending | passed | failed | escalated
created_at: timestamp
completed_at: timestamp
```

## Lifecycle states

### 1. Proposed

An agent proposes a falsifiable idea.

Required fields:

- Hypothesis
- Mechanism
- Proposed metric
- Expected failure mode

### 2. Triaged

The controller decides whether the proposal is worth a small experiment.

Triage criteria:

- Cheap to test
- Clear metric
- Low safety risk
- Non-duplicate
- Relevant to current objective

### 3. Planned

The experiment plan specifies:

- Code surface
- Dataset or task fixture
- Baseline
- Evaluation command
- Time/resource budget
- Promotion criteria

### 4. Implemented

Implementation Agent creates a patch.

Required checks:

- Diff limited to allowed files
- Tests not weakened
- Logging preserved
- No permission expansion

### 5. Running

Experiment Runner executes the experiment.

Required controls:

- Timeout
- Resource cap
- Sandboxed process
- Captured stdout/stderr
- Artifact hashing

### 6. Evaluated

Evaluation Agent compares result to baseline.

Required output:

- Metric table
- Pass/fail decision
- Regression notes
- Reproducibility status

### 7. Interpreted

Interpretation Agent explains result and proposes next action.

Possible outcomes:

- Promote
- Reject
- Retry with fix
- Run ablation
- Add test
- Archive as negative result

### 8. Archived

Memory Curator writes the final structured record.

## Promotion policy

An experiment can be promoted only when:

```text
primary_metric improves
AND required secondary metrics do not regress beyond threshold
AND safety gate passes
AND result is reproducible
AND implementation did not violate edit constraints
```

## Rollback policy

Every promoted change must include:

- Original baseline reference
- Candidate reference
- Reproduction command
- Revert command
- Responsible agent trace
- Human approval record if applicable
