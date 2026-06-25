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
    assert {"run-task", "run-org", "summarize-runs", "propose-meta-change"} <= set(choices)


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


def test_summarize_runs_shows_top_failure_modes(tmp_path, capsys):
    path = tmp_path / "attempts.jsonl"
    archive = JSONLArchive(path)
    for i in range(2):
        archive.append(
            Attempt(
                attempt_id=f"f{i}",
                task_id="t",
                candidate=Candidate(candidate_id=f"f{i}", task_id="t", code="pass"),
                evaluation=EvaluationResult(passed_tests=0, failed_tests=3, score=-300.0),
                status=AttemptStatus.REJECTED,
                reason=f"{i + 1} test(s) failing",
            )
        )
    assert main(["summarize-runs", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Top failure modes:" in out
    assert "test_failures: 2" in out  # numbers clustered into one signature


def test_summarize_runs_empty(tmp_path, capsys):
    assert main(["summarize-runs", str(tmp_path / "none.jsonl")]) == 0
    assert "No attempts" in capsys.readouterr().out


def test_propose_meta_change_records_proposal(tmp_path, capsys):
    archive_path = tmp_path / "attempts.jsonl"
    store_path = tmp_path / "meta_changes.jsonl"
    JSONLArchive(archive_path).append(
        Attempt(
            attempt_id="a1",
            task_id="t",
            candidate=Candidate(candidate_id="a1", task_id="t", code="pass"),
            evaluation=EvaluationResult(passed_tests=0, failed_tests=3, score=-300.0),
            status=AttemptStatus.REJECTED,
            reason="3 test(s) failing",
        )
    )
    # No --validate: proposes and records without needing a model server.
    assert main(["propose-meta-change", str(archive_path), "--store", str(store_path)]) == 0
    out = capsys.readouterr().out
    assert "Proposed meta-change" in out
    assert "Rollback:" in out
    assert "human-gated" in out
    # The proposal is recorded in the separate meta-change archive.
    assert store_path.exists()
