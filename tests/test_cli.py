"""The CLI surface exists: --help, --version, and the documented subcommands run."""

import json
import re

import pytest

from siro.archive import JSONLArchive
from siro.cli import build_parser, main
from siro.model_training import ModelRegistry
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
    assert {
        "run-task",
        "run-org",
        "summarize-runs",
        "propose-meta-change",
        "check-docs",
        "pricing-audit",
        "provider-report",
        "run-scaled",
        "sandbox-backends",
        "storage-migrate",
        "storage-import",
        "storage-export",
        "storage-verify",
    } <= set(choices)


def test_sandbox_backends_lists_local_and_hard(capsys):
    assert main(["sandbox-backends"]) == 0
    out = capsys.readouterr().out
    assert "local: available" in out
    assert "linux_guarded" in out


def test_storage_migrate_import_export_verify_roundtrip(tmp_path, capsys):
    from siro.archive import JSONLArchive
    from siro.schemas import Attempt, AttemptStatus, Candidate

    runs = tmp_path / "runs"
    runs.mkdir()
    archive = JSONLArchive(runs / "attempts.jsonl")
    for i in range(3):
        archive.append(
            Attempt(
                attempt_id=f"a{i}",
                task_id="t",
                candidate=Candidate(candidate_id=f"c{i}", task_id="t", code="x = 1"),
                status=AttemptStatus.REJECTED,
                reason="1 test(s) failing",
            )
        )
    db = tmp_path / "siro.db"

    assert main(["storage-migrate", "--store", str(db)]) == 0
    assert "schema 0 -> 2" in capsys.readouterr().out

    assert main(["storage-import", "--store", str(db), "--from-dir", str(runs)]) == 0
    assert "attempts: 3 new" in capsys.readouterr().out

    # summarize-runs works against the SQLite store, not just JSONL.
    assert main(["summarize-runs", "--store", str(db)]) == 0
    assert "Attempts: 3" in capsys.readouterr().out

    out_dir = tmp_path / "export"
    assert main(["storage-export", "--store", str(db), "--to-dir", str(out_dir)]) == 0
    capsys.readouterr()
    exported = (out_dir / "attempts.jsonl").read_text().splitlines()
    assert sorted(exported) == sorted((runs / "attempts.jsonl").read_text().splitlines())

    # Hash-chain verification passes on an untampered store.
    assert main(["storage-verify", "--store", str(db)]) == 0


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


def test_tier2_model_training_smoke_path_uses_separate_train_and_deploy_approvals(
    tmp_path, capsys
):
    """Cheap end-to-end Tier 2 smoke through the public CLI entrypoints."""

    approvals = tmp_path / "approvals.jsonl"
    config = tmp_path / "tier2.governed.yaml"
    config.write_text(
        f"""
tier: 2
governance:
  enabled: true
  approvals_path: {approvals}
""",
        encoding="utf-8",
    )
    archive = tmp_path / "model_artifacts.jsonl"
    store = tmp_path / "artifacts"
    registry_path = tmp_path / "model_registry.jsonl"
    experiment_id = "tier2-smoke"

    train_payload = {
        "train_config": {"learning_rate": 0.1, "epochs": 300},
        "compute_tier": 0,
    }
    assert main([
        "request-approval",
        "model_train",
        "--target",
        f"train:{experiment_id}",
        "--payload",
        json.dumps(train_payload),
        "--ledger",
        str(approvals),
    ]) == 0
    train_request = re.search(r"request ([0-9a-f]{12})", capsys.readouterr().out).group(1)

    assert main(["approve", train_request, "--by", "alice", "--ledger", str(approvals)]) == 0
    capsys.readouterr()

    assert main([
        "train-model",
        experiment_id,
        "--config",
        str(config),
        "--archive",
        str(archive),
        "--store",
        str(store),
    ]) == 0
    train_out = capsys.readouterr().out
    artifact_id = re.search(r"trained artifact ([0-9a-f]{12})", train_out).group(1)
    assert "NOT deployed" in train_out
    assert ModelRegistry(registry_path).is_deployed(artifact_id, "implementation") is False

    assert main([
        "deploy-model",
        artifact_id,
        "implementation",
        "--implementation-provider",
        "anthropic",
        "--reviewer-provider",
        "openai",
        "--config",
        str(config),
        "--store",
        str(store),
        "--registry",
        str(registry_path),
    ]) == 2
    deploy_denied = capsys.readouterr().out
    assert "needs human approval" in deploy_denied
    assert ModelRegistry(registry_path).is_deployed(artifact_id, "implementation") is False

    deploy_payload = {"artifact_id": artifact_id, "role": "implementation"}
    assert main([
        "request-approval",
        "model_deploy",
        "--target",
        "deploy:implementation",
        "--payload",
        json.dumps(deploy_payload),
        "--ledger",
        str(approvals),
    ]) == 0
    deploy_request = re.search(r"request ([0-9a-f]{12})", capsys.readouterr().out).group(1)

    assert main(["approve", deploy_request, "--by", "alice", "--ledger", str(approvals)]) == 0
    capsys.readouterr()

    assert main([
        "deploy-model",
        artifact_id,
        "implementation",
        "--implementation-provider",
        "anthropic",
        "--reviewer-provider",
        "openai",
        "--config",
        str(config),
        "--store",
        str(store),
        "--registry",
        str(registry_path),
    ]) == 0
    deploy_out = capsys.readouterr().out
    assert "DEPLOYED" in deploy_out
    assert "reviewer openai" in deploy_out
    assert ModelRegistry(registry_path).is_deployed(artifact_id, "implementation") is True
