"""Goal 08 — agent tools are control-plane-only: no shell, no network, allow-listed I/O."""

from __future__ import annotations

from siro.memory import ResearchMemory
from siro.schemas import Attempt, AttemptStatus, Candidate, EvaluationResult
from siro.tools import (
    DATA_PREFIX,
    Toolbox,
    list_references_tool,
    propose_patch_tool,
    query_memory_tool,
    read_allowed_file_tool,
)


def _attempt(task_id="t", code="def f():\n    return 1\n", status=AttemptStatus.REJECTED):
    return Attempt(
        attempt_id="a1",
        task_id=task_id,
        candidate=Candidate(candidate_id="c1", task_id=task_id, code=code),
        evaluation=EvaluationResult(passed_tests=1, score=900.0, reproducible=True),
        status=status,
        reason="1 test(s) failing",
    )


def test_no_shell_or_network_tool_exists():
    """The whole tools surface is control-plane functions — by name, none reach shell/net."""
    box = Toolbox(
        tools=[
            read_allowed_file_tool([]),
            propose_patch_tool(),
            list_references_tool("docs/12_references.md"),
        ]
    )
    banned = {"shell", "exec", "bash", "run", "fetch", "http", "request", "socket", "network"}
    assert not (set(box.names()) & banned)


def test_read_allowed_file_only_reads_allowlisted(tmp_path):
    allowed = tmp_path / "module.py"
    allowed.write_text("X = 1\n", encoding="utf-8")
    outside = tmp_path / "secret.py"
    outside.write_text("SECRET = 2\n", encoding="utf-8")

    tool = read_allowed_file_tool([allowed])
    ok = tool.invoke({"path": str(allowed)})
    assert "X = 1" in ok and ok.startswith(DATA_PREFIX)

    blocked = tool.invoke({"path": str(outside)})
    assert "not an allowed edit surface" in blocked
    assert "SECRET" not in blocked


def test_read_allowed_file_refuses_evaluator_and_tests(tmp_path):
    # Even if (mistakenly) allow-listed, evaluator/test/safety/gate surfaces are refused.
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text("score = 0\n", encoding="utf-8")
    tests = tmp_path / "test_thing.py"
    tests.write_text("def test_x(): pass\n", encoding="utf-8")

    for forbidden in (evaluator, tests):
        tool = read_allowed_file_tool([forbidden])
        out = tool.invoke({"path": str(forbidden)})
        assert "read-only to agents" in out


def test_query_memory_returns_data_not_instructions(tmp_path):
    mem = ResearchMemory(tmp_path / "m.jsonl")
    mem.record(_attempt())
    tool = query_memory_tool(mem, task_id="t")
    out = tool.invoke({"limit": 5})
    assert out.startswith(DATA_PREFIX)
    assert "score=" in out


def test_propose_patch_normalizes_fenced_code():
    tool = propose_patch_tool()
    out = tool.invoke({"code": "```python\ndef g():\n    return 2\n```"})
    assert "def g()" in out
    assert "```" not in out
    assert tool.invoke({"code": "   "}).endswith("empty patch")


def test_toolbox_invoke_unknown_is_safe_data():
    box = Toolbox(tools=[propose_patch_tool()])
    out = box.invoke("definitely_not_a_tool", {})
    assert "not available" in out and out.startswith(DATA_PREFIX)
