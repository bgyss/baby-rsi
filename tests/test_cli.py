"""The CLI surface exists: --help, --version, and the documented subcommands run."""

import pytest

from siro.archive import JSONLArchive
from siro.cli import build_parser, main
from siro.schemas import Attempt, AttemptStatus, Candidate, EvaluationResult


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "siro" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_subcommands_registered():
    parser = build_parser()
    # argparse stores the subparser choices; all three must be present.
    choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    assert {"run-task", "summarize-runs", "propose-meta-change"} <= set(choices)


def test_summarize_runs_reads_archive(tmp_path, capsys):
    path = tmp_path / "attempts.jsonl"
    JSONLArchive(path).append(
        Attempt(
            attempt_id="a1",
            task_id="t",
            candidate=Candidate(candidate_id="a1", task_id="t", code="pass"),
            evaluation=EvaluationResult(passed_tests=4, failed_tests=0, score=4000.0),
            status=AttemptStatus.PROMOTED,
        )
    )
    assert main(["summarize-runs", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Attempts: 1" in out
    assert "Best score: 4000.0" in out


def test_summarize_runs_empty(tmp_path, capsys):
    assert main(["summarize-runs", str(tmp_path / "none.jsonl")]) == 0
    assert "No attempts" in capsys.readouterr().out
