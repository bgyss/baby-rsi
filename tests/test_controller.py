"""Candidate selection + the full code-improver loop (Goal 02), fully offline."""

from siro.archive import JSONLArchive, ModelCallLedger
from siro.controller import Controller, load_task, select_best
from siro.model_client import ScriptedModelClient
from siro.schemas import Attempt, AttemptStatus, Candidate, EvaluationResult

TASK_DIR = "tasks/code_improver/task_001"

# A correct replacement the scripted "model" proposes — passes all four tests and is
# simpler/faster than the seed (so it should be promoted over the baseline).
GOOD_CODE = "def sum_list(values):\n    return sum(values)\n"
# A broken replacement — fails to import / run, so every test counts as failed.
BAD_CODE = "def sum_list(values)\n    return sum(values)\n"  # syntax error


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


def test_load_task_reads_fixture():
    task = load_task(TASK_DIR)
    assert task.task_id == "task_001"
    assert task.module_name == "seed_solution"
    assert "sum_list" in task.seed_code
    assert task.tests_path.name == "tests.py"


def test_run_task_five_generations(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    model = ScriptedModelClient([f"```python\n{GOOD_CODE}```"])
    controller = Controller(archive=archive, ledger=ledger)

    result = controller.run_task(TASK_DIR, model=model, generations=5)

    # Acceptance: 5 generations + the seed baseline are all recorded.
    assert len(result.attempts) == 6
    assert len(archive.read_all()) == 6
    # Acceptance: every model call is logged to the audit ledger (one per generation).
    assert len(ledger.read_all()) == 5
    # The best candidate passes all four tests.
    assert result.best is not None
    assert result.best.evaluation.passed_tests == 4
    assert result.best.evaluation.failed_tests == 0


def test_best_candidate_selected_by_score(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    # First proposal is broken, second is correct: the loop must end on the good one.
    model = ScriptedModelClient([f"```python\n{BAD_CODE}```", f"```python\n{GOOD_CODE}```"])
    controller = Controller(archive=archive, ledger=ledger)

    result = controller.run_task(TASK_DIR, model=model, generations=2)

    assert result.best.evaluation.failed_tests == 0
    # The broken candidate is kept as a negative result, not discarded.
    statuses = [a.status for a in result.attempts]
    assert AttemptStatus.ERROR in statuses or AttemptStatus.REJECTED in statuses


def test_negative_results_are_archived(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    model = ScriptedModelClient([f"```python\n{BAD_CODE}```"])
    controller = Controller(archive=archive, ledger=ledger)

    result = controller.run_task(TASK_DIR, model=model, generations=3)

    # Seed baseline + 3 failing attempts, none dropped.
    assert len(archive.read_all()) == 4
    failing = [a for a in result.attempts if a.evaluation.failed_tests > 0]
    assert failing, "broken candidates must be recorded with their failure reason"
    assert all(a.reason for a in failing)
