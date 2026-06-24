"""Scoring is deterministic arithmetic matching the documented formula."""

from siro.evaluator import compute_score, score_result
from siro.schemas import EvaluationResult


def test_score_formula():
    # 1000*passed - 100*failed - runtime_ms - complexity_penalty
    assert compute_score(4, 0, 0, 0) == 4000.0
    assert compute_score(3, 1, 12.0, 5.0) == 3000 - 100 - 12 - 5


def test_passing_dominates_failing():
    assert compute_score(4, 0) > compute_score(3, 1)


def test_score_result_fills_score():
    result = EvaluationResult(passed_tests=4, failed_tests=0, runtime_ms=2.0)
    scored = score_result(result)
    assert scored.score == 4000.0 - 2.0
