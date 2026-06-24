# Goal Prompt 03 — Research Memory

## Goal

Add structured research memory so the system can learn from past successful and failed attempts.

## Requirements

Implement a memory module that stores:

- experiment ID
- task ID
- hypothesis or repair strategy
- candidate summary
- score
- failure mode
- evaluator output
- promoted/rejected status
- follow-up recommendations

Use SQLite or JSONL. Prefer SQLite if the archive is already stable.

## Retrieval

Implement retrieval functions for:

- prior successes by task type
- prior failures by error signature
- common repair strategies
- highest-scoring candidates
- negative results

## Prompt integration

Modify the candidate-generation prompt to include a compact memory summary:

```text
Relevant prior lessons:
- Handle empty inputs explicitly.
- Avoid changing function signatures.
- Do not special-case visible tests.
```

## Acceptance criteria

- Memory entries are created after each run.
- The model prompt receives relevant prior lessons.
- A summary command shows the top recurring failure modes.
- Negative results are preserved.

## Constraints

- Do not let the model edit memory directly.
- All memory writes go through typed schemas.
- Include timestamps and source experiment IDs.
