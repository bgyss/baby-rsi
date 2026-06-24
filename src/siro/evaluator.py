"""Objective evaluation — scoring is reproducible arithmetic, not model judgment.

Goal 01 implements the pure scoring function (the contract from ``CLAUDE.md`` and
``docs/05_evaluation_and_safety_gates.md``). Goal 02 connects it to real sandbox
test results; Goal 04 adds the full promotion gate around it.

    score = 1000*passed_tests - 100*failed_tests - runtime_ms - complexity_penalty

Higher is better. The weights make passing tests dominate, then penalize failures,
then prefer faster and simpler solutions.
"""

from __future__ import annotations

from .schemas import EvaluationResult

PASS_WEIGHT = 1000.0
FAIL_WEIGHT = 100.0


def compute_score(
    passed_tests: int,
    failed_tests: int,
    runtime_ms: float = 0.0,
    complexity_penalty: float = 0.0,
) -> float:
    """Return the objective score for a candidate's measured results."""
    return (
        PASS_WEIGHT * passed_tests
        - FAIL_WEIGHT * failed_tests
        - runtime_ms
        - complexity_penalty
    )


def score_result(result: EvaluationResult) -> EvaluationResult:
    """Return a copy of ``result`` with ``score`` filled from its measurements."""
    return result.model_copy(
        update={
            "score": compute_score(
                result.passed_tests,
                result.failed_tests,
                result.runtime_ms,
                result.complexity_penalty,
            )
        }
    )


__all__ = ["compute_score", "score_result", "PASS_WEIGHT", "FAIL_WEIGHT"]
