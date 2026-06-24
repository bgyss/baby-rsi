# 06 — Research Memory Schema

## Purpose

Research memory is the system's institutional memory. It should preserve not only what worked, but also what failed, what was ambiguous, and what should be tried next.

## Memory entry schema

```yaml
memory_id: mem_YYYYMMDD_HHMMSS_slug
entry_type: hypothesis | experiment | result | lesson | failure | meta_change
created_at: timestamp
created_by: agent_or_human
related_experiments: list
related_code_refs: list
summary: string

hypothesis:
  statement: string
  mechanism: string
  expected_result: string
  confidence: low | medium | high

experiment:
  objective: string
  baseline: string
  candidate: string
  budget_tier: integer
  environment: string
  command: string

metrics:
  primary:
    name: string
    baseline: number
    candidate: number
    delta: number
    direction: higher_is_better | lower_is_better
  secondary: list

interpretation:
  result: success | failure | mixed | inconclusive
  explanation: string
  confidence: low | medium | high
  known_limitations: list

safety:
  status: passed | failed | escalated
  notes: string

follow_up:
  recommended_next_steps: list
  blocked_by: list
  priority: low | medium | high

tags:
  - optimizer
  - data
  - architecture
  - eval
  - agent_policy
  - safety
```

## Retrieval patterns

Agents should retrieve memory by:

- Similar task type
- Similar failure mode
- Similar code surface
- Similar metric behavior
- Prior successful strategies
- Prior rejected ideas

## Memory quality requirements

Each entry should be:

- Specific
- Reproducible
- Searchable
- Linked to artifacts
- Honest about uncertainty

## Negative results

Negative results should not be discarded. They prevent repeated wasted work and help train better experiment selection.

A useful negative result includes:

```yaml
attempted_change: string
why_it_seemed_promising: string
observed_failure: string
likely_reason: string
conditions_under_which_it_might_still_work: string
```
