"""The JSONL archive round-trips attempts and the audit ledger."""

from siro.archive import JSONLArchive, ModelCallLedger
from siro.schemas import (
    Attempt,
    AttemptStatus,
    Candidate,
    EvaluationResult,
    ModelCall,
)


def _attempt(attempt_id: str, score: float, status: AttemptStatus) -> Attempt:
    return Attempt(
        attempt_id=attempt_id,
        task_id="task_001",
        candidate=Candidate(candidate_id=attempt_id, task_id="task_001", code="pass"),
        evaluation=EvaluationResult(passed_tests=4, failed_tests=0, score=score),
        status=status,
        reason="" if status is AttemptStatus.PROMOTED else "lower score",
    )


def test_attempt_round_trip(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    archive.append(_attempt("a1", 4000.0, AttemptStatus.PROMOTED))
    archive.append(_attempt("a2", 100.0, AttemptStatus.REJECTED))

    loaded = archive.read_all()
    assert [a.attempt_id for a in loaded] == ["a1", "a2"]
    assert loaded[0].evaluation.score == 4000.0
    assert len(archive) == 2


def test_negative_results_are_kept(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    archive.append(_attempt("err", 0.0, AttemptStatus.ERROR))
    loaded = archive.read_all()
    assert loaded[0].status is AttemptStatus.ERROR
    assert loaded[0].reason  # failure reason recorded, not discarded


def test_model_call_ledger_round_trip(tmp_path):
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    ledger.append(
        ModelCall(provider="local", model="qwen", prompt_hash="abc", input_tokens=10)
    )
    rows = ledger.read_all()
    assert rows[0].provider == "local"
    assert rows[0].input_tokens == 10
