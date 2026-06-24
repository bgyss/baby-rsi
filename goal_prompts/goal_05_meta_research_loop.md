# Goal Prompt 05 — Meta-Research Loop

## Goal

Add a controlled meta-research loop that proposes improvements to the research process itself, such as prompt templates, mutation strategies, or experiment selection policies.

## Scope

Allowed meta-changes:

- Candidate-generation prompt revisions
- Memory retrieval strategy changes
- Scoring heuristic changes within configured bounds
- Experiment selection heuristics
- Failure clustering methods

Forbidden meta-changes without human approval:

- Safety gate changes
- Evaluator weakening
- Permission expansion
- Budget expansion
- Network access
- Autonomous package installation

## Required flow

```text
summarize experiment archive
→ identify bottlenecks
→ propose meta-change
→ create A/B validation plan
→ run on fixed benchmark tasks
→ compare against current process
→ recommend promote/reject
```

## Acceptance criteria

- Meta-change proposals are stored separately from ordinary candidate attempts.
- A/B testing compares old vs new process on the same task set.
- Meta-change promotion requires improvement on aggregate metrics.
- Rollback plan is generated.
- Human approval flag is required before durable process changes.

## Metrics

Track:

- pass rate
- median generations to success
- number of invalid candidates
- safety gate failures
- score improvement per generation
- diversity of attempted strategies
