"""Objective evaluation — scoring is reproducible arithmetic, not model judgment.

Goal 02 connects the pure scoring function (the contract from ``CLAUDE.md`` and
``docs/05_evaluation_and_safety_gates.md``) to real sandbox test results; Goal 04
adds the full promotion gate around it.

    score = 1000*passed_tests - 100*failed_tests - runtime_ms - complexity_penalty

Higher is better. The weights make passing tests dominate, then penalize failures,
then prefer faster and simpler solutions. Scoring depends only on objective,
reproducible measurements — never on a model's self-judgment.
"""

from __future__ import annotations

import ast

from .sandbox import SandboxResult
from .schemas import EvaluationResult

PASS_WEIGHT = 1000.0
FAIL_WEIGHT = 100.0
#: Per-AST-node weight of the complexity penalty (kept tiny so it only breaks ties
#: between candidates that are otherwise equal on tests and runtime).
COMPLEXITY_WEIGHT = 0.1


def compute_score(
    passed_tests: int,
    failed_tests: int,
    runtime_ms: float = 0.0,
    complexity_penalty: float = 0.0,
) -> float:
    """Return the objective score for a candidate's measured results."""
    return PASS_WEIGHT * passed_tests - FAIL_WEIGHT * failed_tests - runtime_ms - complexity_penalty


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


def complexity_penalty(code: str) -> float:
    """A small, deterministic penalty for candidate complexity (AST node count).

    Syntactically invalid code can't be parsed; it returns ``0.0`` here because the
    test failures already dominate its (very negative) score.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0.0
    nodes = sum(1 for _ in ast.walk(tree))
    return COMPLEXITY_WEIGHT * nodes


def evaluate(result: SandboxResult, code: str) -> EvaluationResult:
    """Build a scored :class:`EvaluationResult` from raw sandbox output and code.

    Reproducibility is asserted for any run that actually executed the fixed test
    suite (timeouts/collection errors are not reproducible signals of quality).
    """
    evaluation = EvaluationResult(
        passed_tests=result.passed_tests,
        failed_tests=result.failed_tests,
        runtime_ms=result.runtime_ms,
        complexity_penalty=complexity_penalty(code),
        reproducible=result.ran,
    )
    return score_result(evaluation)


__all__ = [
    "compute_score",
    "score_result",
    "complexity_penalty",
    "evaluate",
    "PASS_WEIGHT",
    "FAIL_WEIGHT",
    "COMPLEXITY_WEIGHT",
]
