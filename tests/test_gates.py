"""Promotion gates (Goal 04): unsafe/non-reproducible/overfit candidates can't promote.

These tests use the real sandbox (offline, isolated) and the scripted model client so
the whole gate machinery runs without a model server or network.
"""

from siro.archive import JSONLArchive, ModelCallLedger
from siro.controller import Controller, load_task
from siro.gates import (
    code_integrity_gate,
    function_signatures,
    hidden_test_gate,
    promotion_gate,
    reproducibility_gate,
    safety_gate,
)
from siro.memory import ResearchMemory, failure_signature
from siro.model_client import ScriptedModelClient
from siro.sandbox import Sandbox, SandboxResult
from siro.schemas import AttemptStatus, Candidate, GateDecision

TASK_DIR = "tasks/code_improver/task_001"

SAFE = "def sum_list(values):\n    return sum(values)\n"


def _candidate(code: str) -> Candidate:
    return Candidate(candidate_id="c", task_id="task_001", code=code)


class _SequenceSandbox:
    """A stub sandbox that returns a fixed sequence of results (deterministic reruns)."""

    def __init__(self, results: list[SandboxResult]) -> None:
        self._results = results
        self.calls = 0

    def run(self, candidate, task, tests_path=None) -> SandboxResult:  # noqa: ANN001
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return result


def _sandbox_result(passed: int, failed: int) -> SandboxResult:
    return SandboxResult(
        returncode=0 if failed == 0 else 1,
        stdout="",
        stderr="",
        runtime_ms=1.0,
        passed_tests=passed,
        failed_tests=failed,
    )


def _make_double_task(tmp_path, *, with_hidden: bool = True):
    """A tiny self-contained task whose seed *fails* its visible tests.

    A failing seed means any candidate that passes the visible tests beats it by
    ~1000 points/test, so promotion is decided by correctness — not by pytest
    start-up runtime noise — which keeps these controller-level tests deterministic.
    """
    task_dir = tmp_path / "double"
    task_dir.mkdir()
    (task_dir / "prompt.md").write_text("# double\nImplement double(x) returning 2*x.\n")
    (task_dir / "seed_solution.py").write_text("def double(x):\n    return 0\n")
    (task_dir / "tests.py").write_text(
        "from seed_solution import double\n\n"
        "def test_one():\n    assert double(1) == 2\n\n"
        "def test_two():\n    assert double(2) == 4\n"
    )
    if with_hidden:
        hidden_dir = tmp_path / "hidden_tests"
        hidden_dir.mkdir()
        (hidden_dir / "double.py").write_text(
            "from seed_solution import double\n\n"
            "def test_five():\n    assert double(5) == 10\n\n"
            "def test_zero():\n    assert double(0) == 0\n"
        )
    return task_dir


# A general, correct double() (passes visible + hidden) and an overfit one
# (hard-codes the visible answers, fails the held-out suite).
DOUBLE_GENERAL = "def double(x):\n    return 2 * x\n"
DOUBLE_OVERFIT = "def double(x):\n    return {1: 2, 2: 4}[x]\n"


# --------------------------------------------------------------------------- #
# Safety gate — static scanning rejects unsafe candidates (acceptance #1).
# --------------------------------------------------------------------------- #


def test_safety_gate_passes_clean_candidate():
    result = safety_gate(SAFE)
    assert result.decision is GateDecision.PASSED


def test_safety_gate_flags_network_library():
    result = safety_gate("import socket\n\ndef sum_list(values):\n    return sum(values)\n")
    assert result.decision is GateDecision.FAILED
    assert any("network" in f for f in result.findings)


def test_safety_gate_flags_env_var_read():
    code = "import os\n\ndef sum_list(values):\n    os.environ['X']\n    return sum(values)\n"
    result = safety_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("env_read" in f for f in result.findings)


def test_safety_gate_flags_subprocess():
    code = "import subprocess\n\ndef sum_list(values):\n    subprocess.run(['ls'])\n    return sum(values)\n"
    result = safety_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("subprocess" in f for f in result.findings)


def test_safety_gate_flags_fork_bomb():
    code = "import os\n\ndef sum_list(values):\n    while True:\n        os.fork()\n    return 0\n"
    result = safety_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("fork" in f for f in result.findings)


def test_safety_gate_flags_long_sleep():
    code = "import time\n\ndef sum_list(values):\n    time.sleep(99)\n    return sum(values)\n"
    result = safety_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("long_sleep" in f for f in result.findings)


def test_safety_gate_flags_file_access_outside_sandbox():
    code = "def sum_list(values):\n    open('/etc/passwd').read()\n    return sum(values)\n"
    result = safety_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("filesystem" in f for f in result.findings)


# --------------------------------------------------------------------------- #
# Code-integrity gate.
# --------------------------------------------------------------------------- #


def test_code_integrity_flags_test_tampering():
    code = (
        "def sum_list(values):\n"
        "    with open('tests.py', 'w') as fh:\n"
        "        fh.write('def test_pass():\\n    assert True\\n')\n"
        "    return 0\n"
    )
    result = code_integrity_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("modify_tests" in f for f in result.findings)


def test_code_integrity_flags_disabling_logging():
    code = "import logging\n\ndef sum_list(values):\n    logging.disable()\n    return sum(values)\n"
    result = code_integrity_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("disable_logging" in f for f in result.findings)


def test_code_integrity_flags_evaluator_import():
    code = "from siro.evaluator import compute_score\n\ndef sum_list(values):\n    return sum(values)\n"
    result = code_integrity_gate(code)
    assert result.decision is GateDecision.FAILED
    assert any("modify_evaluator" in f for f in result.findings)


def test_code_integrity_flags_signature_change():
    allowed = {"sum_list": ("values",)}
    changed = "def sum_list(values, sneaky=1):\n    return sum(values)\n"
    result = code_integrity_gate(changed, allowed_signatures=allowed)
    assert result.decision is GateDecision.FAILED
    assert any("signature_change" in f for f in result.findings)


def test_code_integrity_allows_matching_signature():
    allowed = {"sum_list": ("values",)}
    result = code_integrity_gate(SAFE, allowed_signatures=allowed)
    assert result.decision is GateDecision.PASSED


def test_function_signatures_reads_top_level_only():
    code = "def sum_list(values):\n    def helper(a, b):\n        return a + b\n    return sum(values)\n"
    sigs = function_signatures(code)
    assert sigs == {"sum_list": ("values",)}


# --------------------------------------------------------------------------- #
# Reproducibility gate (acceptance #2).
# --------------------------------------------------------------------------- #


def test_reproducibility_gate_passes_deterministic_candidate():
    task = load_task(TASK_DIR)
    result = reproducibility_gate(_candidate(SAFE), task, Sandbox(), runs=3)
    assert result.decision is GateDecision.PASSED


def test_reproducibility_gate_fails_nondeterministic_candidate():
    task = load_task(TASK_DIR)
    # A candidate whose reruns disagree on pass/fail must not be promotable. We model
    # the non-determinism with a stub sandbox so the test itself stays deterministic.
    sandbox = _SequenceSandbox([_sandbox_result(4, 0), _sandbox_result(0, 4), _sandbox_result(4, 0)])
    result = reproducibility_gate(_candidate(SAFE), task, sandbox, runs=3)
    assert result.decision is GateDecision.FAILED
    assert any("non-reproducible" in f for f in result.findings)


# --------------------------------------------------------------------------- #
# Hidden-test gate (acceptance #3).
# --------------------------------------------------------------------------- #


def test_hidden_tests_are_discovered_outside_task_dir():
    task = load_task(TASK_DIR)
    assert task.hidden_tests_path is not None
    # The hidden suite lives outside the task directory.
    assert TASK_DIR not in str(task.hidden_tests_path.parent)


def test_hidden_tests_not_exposed_in_model_prompt():
    task = load_task(TASK_DIR)
    hidden_text = task.hidden_tests_path.read_text(encoding="utf-8")
    # Nothing from the hidden suite leaks into the prompt text the model receives.
    assert "test_large_range" in hidden_text
    assert "test_large_range" not in task.prompt
    assert "499500" not in task.prompt


def test_hidden_gate_passes_general_solution():
    task = load_task(TASK_DIR)
    result = hidden_test_gate(_candidate(SAFE), task, Sandbox())
    assert result.decision is GateDecision.PASSED


def test_hidden_gate_fails_overfit_solution():
    task = load_task(TASK_DIR)
    # Hard-codes only the visible-test answers; fails the held-out suite.
    overfit = (
        "def sum_list(values):\n"
        "    answers = {(): 0, (1, 2, 3): 6, (0.5, 1.5): 2.0, (-2, 2, -3): -3}\n"
        "    return answers[tuple(values)]\n"
    )
    result = hidden_test_gate(_candidate(overfit), task, Sandbox())
    assert result.decision is GateDecision.FAILED


def test_hidden_gate_passes_when_no_hidden_suite(tmp_path):
    task = load_task(TASK_DIR)
    object.__setattr__(task, "hidden_tests_path", None)
    result = hidden_test_gate(_candidate(SAFE), task, Sandbox())
    assert result.decision is GateDecision.PASSED


# --------------------------------------------------------------------------- #
# Combined promotion gate + controller integration (acceptance #4).
# --------------------------------------------------------------------------- #


def test_promotion_gate_passes_for_clean_general_candidate():
    task = load_task(TASK_DIR)
    report = promotion_gate(
        _candidate(SAFE),
        task,
        Sandbox(),
        allowed_signatures={"sum_list": ("values",)},
        hidden_tests_path=task.hidden_tests_path,
    )
    assert report.passed
    assert {r.gate for r in report.results} == {
        "safety",
        "code_integrity",
        "reproducibility",
        "hidden_tests",
    }


def test_unsafe_candidate_is_not_promoted_and_is_logged(tmp_path):
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    unsafe = (
        "import socket\n\n"
        "def sum_list(values):\n"
        "    return sum(values)\n"  # would beat the seed on score, but uses the network
    )
    model = ScriptedModelClient([f"```python\n{unsafe}```"])
    controller = Controller(
        archive=archive, ledger=ledger, memory=ResearchMemory(tmp_path / "memory.jsonl")
    )

    result = controller.run_task(TASK_DIR, model=model, generations=1)

    # The unsafe candidate did not win; the seed remains best.
    assert result.best.candidate.candidate_id == "seed"
    unsafe_attempt = result.attempts[-1]
    assert unsafe_attempt.status is AttemptStatus.REJECTED
    # Gate decision is recorded in the archive (acceptance: gate results logged).
    archived = archive.read_all()[-1]
    assert archived.gates is not None
    assert archived.gates.failed
    assert any(r.gate == "safety" and r.decision is GateDecision.FAILED for r in archived.gates.results)


def test_overfit_candidate_fails_promotion_via_hidden_tests(tmp_path):
    task_dir = _make_double_task(tmp_path)
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    model = ScriptedModelClient([f"```python\n{DOUBLE_OVERFIT}```"])
    controller = Controller(
        archive=archive, ledger=ledger, memory=ResearchMemory(tmp_path / "memory.jsonl")
    )

    result = controller.run_task(task_dir, model=model, generations=1)

    # It out-scores the failing seed on visible tests, but the hidden-test gate blocks it.
    assert result.best.candidate.candidate_id == "seed"
    overfit_attempt = result.attempts[-1]
    assert overfit_attempt.status is AttemptStatus.REJECTED
    assert "hidden_tests" in overfit_attempt.reason
    assert failure_signature(overfit_attempt.reason) == "gate_hidden_tests"


def test_clean_better_candidate_is_promoted_through_gates(tmp_path):
    task_dir = _make_double_task(tmp_path)
    archive = JSONLArchive(tmp_path / "attempts.jsonl")
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    model = ScriptedModelClient([f"```python\n{DOUBLE_GENERAL}```"])
    controller = Controller(
        archive=archive, ledger=ledger, memory=ResearchMemory(tmp_path / "memory.jsonl")
    )

    result = controller.run_task(task_dir, model=model, generations=1)

    winner = result.best
    assert winner.candidate.candidate_id != "seed"
    assert winner.status is AttemptStatus.PROMOTED
    # The promoted attempt carries the full four-gate report, all passing.
    assert winner.gates is not None and winner.gates.passed
    assert len(winner.gates.results) == 4
