# Goal Prompt 04 — Evaluation and Safety Gates

## Goal

Implement gates that prevent the system from promoting candidates that improve scores through evaluator manipulation, unsafe behavior, or non-reproducible results.

## Required gates

### Code integrity gate

Fail candidates that:

- Modify tests.
- Modify evaluator code.
- Disable logging.
- Add suspicious subprocess/network behavior.
- Change function signatures unless allowed.

### Reproducibility gate

Before promotion, rerun the winning candidate at least twice.

Promotion requires consistent pass/fail and compatible timing behavior.

### Hidden test gate

Support optional hidden tests stored outside the task directory.

### Safety gate

Flag candidates that:

- Use network libraries.
- Read environment variables.
- Access files outside the sandbox.
- Spawn uncontrolled subprocesses.
- Attempt long sleeps or fork bombs.

## Acceptance criteria

- Unsafe candidate examples are rejected.
- Non-reproducible candidates are not promoted.
- Hidden tests can be run without exposing them in the model prompt.
- Gate results are logged in the archive.

## Constraints

- Safety checks should be conservative.
- The first implementation may use static scanning plus sandbox limits.
- Do not rely only on model-based safety review.
