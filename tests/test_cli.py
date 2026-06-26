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


# --- Goal 21: conversational-interface affordances (structured output + dry-run) -------


def _seed_attempt(path, *, status=AttemptStatus.PROMOTED, score=4000.0):
    JSONLArchive(path).append(
        Attempt(
            attempt_id="a1",
            task_id="t",
            candidate=Candidate(candidate_id="a1", task_id="t", code="pass"),
            evaluation=EvaluationResult(passed_tests=4, failed_tests=0, score=score),
            status=status,
        )
    )


def test_summarize_runs_json_is_parseable_and_default_unchanged(tmp_path, capsys):
    path = tmp_path / "attempts.jsonl"
    _seed_attempt(path)

    # Structured output for a skill to parse.
    assert main(["--json", "summarize-runs", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_attempts"] == 1
    assert payload["best"]["score"] == 4000.0
    assert payload["status_counts"]["promoted"] == 1

    # The human-readable default is unchanged (no --json).
    assert main(["summarize-runs", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Attempts: 1" in out and "{" not in out


def test_summarize_research_json_empty_is_valid(tmp_path, capsys):
    assert main(["--json", "summarize-research", str(tmp_path / "none.jsonl")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_attempts"] == 0 and payload["families"] == {}


def test_provider_report_json_empty_is_valid(tmp_path, capsys):
    assert main(["--json", "provider-report", "--model-calls", str(tmp_path / "none.jsonl")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rows"] == 0 and payload["groups"] == []


def test_list_approvals_json_round_trips_a_request(tmp_path, capsys):
    ledger = tmp_path / "approvals.jsonl"
    assert (
        main(
            [
                "request-approval",
                "budget_increase",
                "--target",
                "max_usd_per_run",
                "--payload",
                json.dumps({"max_usd_per_run": 20}),
                "--ledger",
                str(ledger),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--json", "list-approvals", "--ledger", str(ledger)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["requests"]) == 1
    req = payload["requests"][0]
    assert req["action"] == "budget_increase" and req["status"] == "pending"


def test_dry_run_makes_no_side_effects(tmp_path, capsys):
    archive = tmp_path / "attempts.jsonl"
    ledger = tmp_path / "model_calls.jsonl"
    rc = main(
        [
            "--dry-run",
            "run-task",
            "tasks/code_improver/task_001",
            "--archive",
            str(archive),
            "--model-calls",
            str(ledger),
            "--config",
            "config/tier1.frontier.yaml",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "would run" in out
    # No state changed, nothing spent, no ledger row written.
    assert not archive.exists()
    assert not ledger.exists()


def test_dry_run_json_plan_reports_tier_and_governance(capsys):
    assert main(["--dry-run", "--json", "run-scaled", "--compute-tier", "1"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True
    assert plan["command"] == "run-scaled"
    assert plan["read_only"] is False
    assert "approval" in plan["governance"].lower()
    assert "Tier 2" in plan["tier"]


def test_dry_run_marks_read_only_commands(capsys):
    assert main(["--dry-run", "--json", "summarize-research"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["read_only"] is True
    assert plan["effect"] == "read-only"


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


def test_tier2_model_training_smoke_path_uses_separate_train_and_deploy_approvals(tmp_path, capsys):
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
    assert (
        main(
            [
                "request-approval",
                "model_train",
                "--target",
                f"train:{experiment_id}",
                "--payload",
                json.dumps(train_payload),
                "--ledger",
                str(approvals),
            ]
        )
        == 0
    )
    train_request = re.search(r"request ([0-9a-f]{12})", capsys.readouterr().out).group(1)

    assert main(["approve", train_request, "--by", "alice", "--ledger", str(approvals)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "train-model",
                experiment_id,
                "--config",
                str(config),
                "--archive",
                str(archive),
                "--store",
                str(store),
            ]
        )
        == 0
    )
    train_out = capsys.readouterr().out
    artifact_id = re.search(r"trained artifact ([0-9a-f]{12})", train_out).group(1)
    assert "NOT deployed" in train_out
    assert ModelRegistry(registry_path).is_deployed(artifact_id, "implementation") is False

    assert (
        main(
            [
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
            ]
        )
        == 2
    )
    deploy_denied = capsys.readouterr().out
    assert "needs human approval" in deploy_denied
    assert ModelRegistry(registry_path).is_deployed(artifact_id, "implementation") is False

    deploy_payload = {"artifact_id": artifact_id, "role": "implementation"}
    assert (
        main(
            [
                "request-approval",
                "model_deploy",
                "--target",
                "deploy:implementation",
                "--payload",
                json.dumps(deploy_payload),
                "--ledger",
                str(approvals),
            ]
        )
        == 0
    )
    deploy_request = re.search(r"request ([0-9a-f]{12})", capsys.readouterr().out).group(1)

    assert main(["approve", deploy_request, "--by", "alice", "--ledger", str(approvals)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
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
            ]
        )
        == 0
    )
    deploy_out = capsys.readouterr().out
    assert "DEPLOYED" in deploy_out
    assert "reviewer openai" in deploy_out
    assert ModelRegistry(registry_path).is_deployed(artifact_id, "implementation") is True


def test_governance_identity_policy_cli_packet_and_verify(tmp_path, capsys):
    approvals = tmp_path / "approvals.jsonl"
    operators = tmp_path / "operators.jsonl"
    config = tmp_path / "tier2.governed.yaml"
    config.write_text(
        f"""
tier: 2
governance:
  enabled: true
  approvals_path: {approvals}
  operators:
    - operator_id: alice
      display_name: Alice Reviewer
      role: approver
      auth_method: local
      status: active
  policies:
    - policy_id: budget
      action: budget_increase
      required_reviewers: 1
      required_role: approver
      separation_of_duties: true
      max_scope: once
      require_signature: true
      required_evidence: ["safety"]
""",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "create-operator",
                "alice",
                "--display-name",
                "Alice Reviewer",
                "--role",
                "approver",
                "--operators",
                str(operators),
            ]
        )
        == 0
    )
    assert main(["list-operators", "--operators", str(operators)]) == 0
    assert "Alice Reviewer" in capsys.readouterr().out

    assert (
        main(
            [
                "request-approval",
                "budget_increase",
                "--target",
                "max_usd_per_run",
                "--actor",
                "casey",
                "--rationale",
                "needs a larger replay",
                "--payload",
                '{"max_usd_per_run": 20}',
                "--risk",
                "high",
                "--evidence",
                "safety",
                "--rollback-plan",
                "restore prior budget",
                "--ledger",
                str(approvals),
            ]
        )
        == 0
    )
    request_id = re.search(r"request ([0-9a-f]{12})", capsys.readouterr().out).group(1)

    assert (
        main(
            [
                "approve",
                request_id,
                "--by",
                "alice",
                "--signing-key",
                "secret",
                "--config",
                str(config),
                "--ledger",
                str(approvals),
            ]
        )
        == 0
    )
    assert "APPROVED" in capsys.readouterr().out

    assert main(["verify-governance", "--config", str(config), "--ledger", str(approvals)]) == 0
    assert "verification OK" in capsys.readouterr().out

    assert (
        main(
            [
                "export-governance-packet",
                request_id,
                "--config",
                str(config),
                "--ledger",
                str(approvals),
            ]
        )
        == 0
    )
    packet = json.loads(capsys.readouterr().out)
    assert packet["exact_payload"]["payload"] == {"max_usd_per_run": 20}
    assert packet["risk_classification"] == "high"
    assert packet["approval_history"][0]["operator_id"] == "alice"
    assert packet["rollback_plan"] == "restore prior budget"
