"""Candidate selection picks the highest-scoring evaluated attempt."""

from siro.controller import Controller, select_best
from siro.schemas import Attempt, AttemptStatus, Candidate, EvaluationResult


def _attempt(attempt_id: str, score: float | None) -> Attempt:
    evaluation = None if score is None else EvaluationResult(passed_tests=1, score=score)
    return Attempt(
        attempt_id=attempt_id,
        task_id="t",
        candidate=Candidate(candidate_id=attempt_id, task_id="t", code="pass"),
        evaluation=evaluation,
        status=AttemptStatus.REJECTED,
    )


def test_select_best_empty():
    assert select_best([]) is None


def test_select_best_ignores_unevaluated():
    best = select_best([_attempt("a", 10.0), _attempt("err", None), _attempt("b", 50.0)])
    assert best is not None and best.attempt_id == "b"


def test_run_task_not_yet_implemented():
    # Goal 01 ships the surface; the loop lands in Goal 02.
    try:
        Controller().run_task("tasks/code_improver/task_001")
    except NotImplementedError:
        return
    raise AssertionError("run_task should be a Goal 02 stub")
