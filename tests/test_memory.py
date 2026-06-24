"""Research memory: recording, retrieval, lessons, and failure clustering (Goal 03)."""

from siro.archive import JSONLArchive, ModelCallLedger
from siro.controller import Controller
from siro.memory import (
    STANDING_LESSONS,
    ResearchMemory,
    entry_from_attempt,
    failure_signature,
)
from siro.model_client import ScriptedModelClient
from siro.schemas import Attempt, AttemptStatus, Candidate, EvaluationResult

TASK_DIR = "tasks/code_improver/task_001"
GOOD_CODE = "def sum_list(values):\n    return sum(values)\n"


def _attempt(attempt_id, *, reason, score, status, parent=None, code="def f():\n    pass\n"):
    return Attempt(
        attempt_id=attempt_id,
        task_id="t",
        candidate=Candidate(candidate_id=attempt_id, task_id="t", code=code, parent_id=parent),
        evaluation=EvaluationResult(passed_tests=1, score=score),
        status=status,
        reason=reason,
    )


def test_failure_signature_clusters_numbers():
    assert failure_signature("3 test(s) failing") == "test_failures"
    assert failure_signature("1 test(s) failing") == "test_failures"
    assert failure_signature("all tests passing") == "none"
    assert failure_signature("collection error: candidate could not be imported") == (
        "collection_error"
    )
    assert failure_signature("timeout after 10.0s") == "timeout"


def test_entry_from_attempt_carries_lineage_and_signature():
    attempt = _attempt(
        "a1", reason="2 test(s) failing", score=-200.0, status=AttemptStatus.REJECTED, parent="seed"
    )
    entry = entry_from_attempt(attempt)
    assert entry.experiment_id == "a1"
    assert entry.source_experiment_id == "seed"  # source experiment id preserved
    assert entry.failure_mode == "test_failures"
    assert entry.follow_up  # a repair recommendation is attached
    assert entry.created_at == attempt.created_at  # timestamp preserved


def test_record_and_retrieve_roundtrip(tmp_path):
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    mem.record(
        _attempt("a1", reason="all tests passing", score=900.0, status=AttemptStatus.PROMOTED)
    )
    mem.record(
        _attempt("a2", reason="2 test(s) failing", score=-200.0, status=AttemptStatus.REJECTED)
    )

    assert len(mem) == 2
    # Negative results are preserved, not discarded.
    negatives = mem.negative_results()
    assert [e.experiment_id for e in negatives] == ["a2"]
    # Prior successes retrievable.
    successes = mem.prior_successes()
    assert [e.experiment_id for e in successes] == ["a1"]


def test_retrieval_functions(tmp_path):
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    mem.record(
        _attempt("hi", reason="all tests passing", score=950.0, status=AttemptStatus.PROMOTED)
    )
    mem.record(
        _attempt("lo", reason="3 test(s) failing", score=-300.0, status=AttemptStatus.REJECTED)
    )
    mem.record(
        _attempt(
            "err",
            reason="collection error: candidate could not be imported",
            score=-400.0,
            status=AttemptStatus.ERROR,
        )
    )

    assert mem.highest_scoring(limit=1)[0].experiment_id == "hi"
    assert [e.experiment_id for e in mem.prior_failures("test_failures")] == ["lo"]
    assert [e.experiment_id for e in mem.prior_failures("collection_error")] == ["err"]
    # Common repair strategies surface follow-up recommendations.
    assert mem.common_repair_strategies()


def test_top_failure_modes_excludes_success(tmp_path):
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    mem.record(
        _attempt("ok", reason="all tests passing", score=900.0, status=AttemptStatus.PROMOTED)
    )
    for i in range(3):
        mem.record(
            _attempt(
                f"f{i}",
                reason=f"{i + 1} test(s) failing",
                score=-100.0,
                status=AttemptStatus.REJECTED,
            )
        )
    modes = dict(mem.top_failure_modes())
    assert modes == {"test_failures": 3}  # "none" excluded, numbers clustered


def test_lessons_include_guardrails_and_failure_derived(tmp_path):
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    mem.record(
        _attempt(
            "e",
            reason="collection error: candidate could not be imported",
            score=-400.0,
            status=AttemptStatus.ERROR,
        )
    )
    lessons = mem.lessons("t")
    for guardrail in STANDING_LESSONS:
        assert guardrail in lessons
    block = mem.lessons_block("t")
    assert block.startswith("Relevant prior lessons:")
    assert "import" in block.lower()  # derived from the collection-error history


def test_in_memory_store_when_path_none():
    mem = ResearchMemory(path=None)
    mem.record(
        _attempt("a1", reason="all tests passing", score=10.0, status=AttemptStatus.PROMOTED)
    )
    assert len(mem) == 1
    assert mem.all_entries()[0].experiment_id == "a1"


def test_controller_records_memory_and_injects_lessons(tmp_path):
    # Capture the prompt the model receives to confirm lessons are injected.
    seen = {}

    class CapturingModel(ScriptedModelClient):
        def generate(self, prompt):  # noqa: D401
            seen["prompt"] = prompt
            return super().generate(prompt)

    memory = ResearchMemory(tmp_path / "memory.jsonl")
    controller = Controller(
        archive=JSONLArchive(tmp_path / "attempts.jsonl"),
        ledger=ModelCallLedger(tmp_path / "model_calls.jsonl"),
        memory=memory,
    )
    model = CapturingModel([f"```python\n{GOOD_CODE}```"])
    result = controller.run_task(TASK_DIR, model=model, generations=1)

    # Acceptance: a memory entry is created after each run (seed + 1 generation).
    assert len(memory) == 2
    # Acceptance: the prompt received relevant prior lessons (guardrails always present).
    assert "Relevant prior lessons:" in seen["prompt"]
    assert STANDING_LESSONS[0] in seen["prompt"]
    # Negative-or-positive, the best is recorded with its evaluator output.
    assert result.best is not None
    assert memory.prior_successes(task_id="task_001")
