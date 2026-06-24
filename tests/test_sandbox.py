"""Sandbox executes candidates in isolation: temp dir, timeout, fixed tests (Goal 02)."""

from pathlib import Path

from siro.controller import load_task
from siro.evaluator import evaluate
from siro.sandbox import Sandbox, SandboxConfig
from siro.schemas import Candidate

TASK_DIR = "tasks/code_improver/task_001"


def _candidate(code: str) -> Candidate:
    return Candidate(candidate_id="c", task_id="task_001", code=code)


def test_passing_candidate_scores_all_tests():
    task = load_task(TASK_DIR)
    result = Sandbox().run(_candidate("def sum_list(values):\n    return sum(values)\n"), task)
    assert result.passed_tests == 4
    assert result.failed_tests == 0
    assert result.ran


def test_failing_candidate_is_measured_not_crashed():
    task = load_task(TASK_DIR)
    # Wrong implementation: returns a constant, so all value-checking tests fail.
    result = Sandbox().run(_candidate("def sum_list(values):\n    return 0\n"), task)
    assert result.passed_tests < 4
    assert result.failed_tests > 0


def test_syntax_error_counts_all_tests_failed():
    task = load_task(TASK_DIR)
    result = Sandbox().run(_candidate("def sum_list(values)\n    return 0\n"), task)
    assert result.passed_tests == 0
    assert result.failed_tests == 4  # every test in tests.py counted as failing
    assert not result.ran  # not a reproducible signal of quality


def test_timeout_is_enforced():
    task = load_task(TASK_DIR)
    sandbox = Sandbox(SandboxConfig(timeout_seconds=1.0))
    # An import-time infinite loop must be killed by the hard timeout.
    result = sandbox.run(_candidate("import time\nwhile True:\n    time.sleep(1)\n"), task)
    assert result.timed_out
    assert "timeout" in result.error


def test_candidate_cannot_modify_the_test_suite(tmp_path):
    """A candidate that overwrites tests.py at import time must not affect scoring.

    The sandbox writes the *fixed* tests.py from the task dir into a fresh temp dir
    for every run; the candidate only controls its own module. Even if the candidate
    tries to weaken the tests, the copy the controller runs is the original.
    """
    task = load_task(TASK_DIR)
    sabotage = (
        "with open('tests.py', 'w') as fh:\n"
        "    fh.write('def test_pass():\\n    assert True\\n')\n"
        "def sum_list(values):\n"
        "    return 0\n"
    )
    result = Sandbox().run(_candidate(sabotage), task)
    # The original four tests still run and still catch the wrong implementation.
    assert result.passed_tests + result.failed_tests == 4
    assert result.failed_tests > 0


def test_original_task_tests_file_is_untouched():
    # Sanity: running the sandbox never edits the repo's task fixtures.
    tests_path = Path(TASK_DIR) / "tests.py"
    before = tests_path.read_text(encoding="utf-8")
    task = load_task(TASK_DIR)
    Sandbox().run(_candidate("def sum_list(values):\n    return sum(values)\n"), task)
    assert tests_path.read_text(encoding="utf-8") == before


def test_evaluate_prefers_passing_and_simpler():
    task = load_task(TASK_DIR)
    good = Sandbox().run(_candidate("def sum_list(values):\n    return sum(values)\n"), task)
    bad = Sandbox().run(_candidate("def sum_list(values):\n    return 0\n"), task)
    good_eval = evaluate(good, "def sum_list(values):\n    return sum(values)\n")
    bad_eval = evaluate(bad, "def sum_list(values):\n    return 0\n")
    assert good_eval.score > bad_eval.score
    assert good_eval.reproducible
