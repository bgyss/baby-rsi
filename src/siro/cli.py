"""``siro`` command-line interface.

The canonical interface to the system (``docs/10_repo_structure.md``); ``mise``
tasks are thin wrappers. Goal 01 ships the command *surface* the self-improvement
cycle uses:

- ``run-task``            — run the per-task improvement loop (Goal 02).
- ``run-training``        — run the tiny-training improvement loop (Goal 06).
- ``run-org``             — run one full frontier-org research cycle (Goal 08).
- ``run-research``        — run the org on research-shaped task(s) (Goal 09).
- ``run-scaled``          — run an eval under a governed compute budget (Goal 11);
                            ``--backend`` selects the isolation backend (Goal 15).
- ``sandbox-backends``    — list resource-isolation backends + availability (Goal 15).
- ``storage-migrate`` / ``storage-import`` / ``storage-export`` / ``storage-verify`` —
                            durable SQLite research store + JSONL round-trip (Goal 16).
- ``train-model`` / ``deploy-model`` — governed weight-update experiments (Goal 12);
                            both human-gated, deploy needs cross-model review.
- ``check-docs``          — verify README/goal manifest consistency and docs privacy
                            patterns (Goal 13).
- ``pricing-audit``       — report resolved provider pricing, review freshness, and
                            representative cycle costs (Goal 14).
- ``provider-report``     — summarize provider spend, latency, retries, and errors
                            from the audit ledger (Goal 18).
- ``pilot-init`` / ``pilot-run`` / ``pilot-report`` — fixed operational pilot plan,
                            execution wrapper, and decision report (Goal 20).
- ``summarize-runs``      — reflect on the archive (real: counts + pass rate + best).
- ``summarize-research``  — per-family summary of the research suite (Goal 09).
- ``propose-meta-change`` — propose a process change (Goal 05).
- ``request-approval`` / ``list-approvals`` / ``approve`` / ``deny`` / ``revoke``
  / ``create-operator`` / ``list-operators`` / ``revoke-operator`` / ``verify-governance``
  / ``export-governance-packet`` — the Tier 2 governance workflow (Goals 10 + 19);
                            approval and identity management are human-only.

Uses only the standard library ``argparse`` to keep Tier 0 dependency-light.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

from . import __version__
from .archive import JSONLArchive, ModelCallLedger
from .backends import available_backends
from .budget import BudgetExceeded, BudgetTracker
from .config import DEFAULT_CONFIG_PATH, load_config
from .controller import Controller, select_best
from .docs_check import DEFAULT_MANIFEST_PATH, check_docs
from .external import (
    DEFAULT_EXTERNAL_RESULTS_PATH,
    ExternalResultLedger,
    ExternalResultRejected,
    external_spec_for,
    ingest_external_result,
    propose_external_experiment,
)
from .governance import (
    DEFAULT_APPROVALS_PATH,
    DEFAULT_OPERATORS_PATH,
    ApprovalLedger,
    GovernanceDenied,
    GovernanceGate,
    OperatorLedger,
)
from .memory import ResearchMemory, failure_signature
from .meta import MetaChangeStore, MetaResearcher
from .model_client import LocalOpenAIClient
from .model_training import (
    DEFAULT_ARTIFACT_STORE_DIR,
    DEFAULT_MODEL_ARTIFACTS_PATH,
    DEFAULT_MODEL_REGISTRY_PATH,
    ArtifactStore,
    DeploymentError,
    GovernedModelTrainer,
    ModelArtifactArchive,
    ModelRegistry,
    ModelTrainingDisabled,
    StabilityError,
    assess_stability,
    deploy_model,
)
from .orchestrator import Orchestrator
from .pilot import (
    DEFAULT_PILOT_PLAN_PATH,
    DEFAULT_PILOT_REPORT_PATH,
    DEFAULT_PILOT_ROOT,
    PilotPlan,
    archive_pilot_configs,
    write_command_transcript,
    write_default_pilot_plan,
    write_pilot_report,
)
from .providers import ModelClient
from .providers.pricing import Pricing
from .research import (
    DEFAULT_RESEARCH_ATTEMPTS_PATH,
    ResearchArchive,
    discover_research_tasks,
    load_research_task,
    summarize_research,
)
from .scale import (
    DEFAULT_CHECKPOINT_DIR,
    BackendPolicyError,
    CheckpointStore,
    ComputeAllocationError,
    ScaledRunner,
    backend_policy_from_config,
    compute_tiers_from_config,
)
from .schemas import (
    ApprovalScope,
    AttemptStatus,
    ExternalResultStatus,
    GovernedAction,
    MetaChangeRecord,
    MetaRecommendation,
    OperatorRole,
)
from .storage import (
    DEFAULT_STORE_PATH,
    STREAMS,
    JSONLStore,
    SQLiteStore,
)
from .training import (
    DEFAULT_BUDGET_SECONDS,
    DEFAULT_TRAINING_ATTEMPTS_PATH,
    TrainingArchive,
    TrainingController,
)


def _build_runtime(
    args: argparse.Namespace, ledger: ModelCallLedger, role: str
) -> tuple[ModelClient, BudgetTracker | None, str]:
    """Resolve the model client + budget for a run from config (Goal 07).

    Tier and provider come from the config file alone — lowering tier back to 0 needs
    no code change. ``--config`` defaults to the safe Tier 0 (local) posture; if the
    file is missing we fall back to a bare local client so Tier 0 always works.
    """
    config_path = getattr(args, "config", None) or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return LocalOpenAIClient(), None, f"tier 0 (local default; {config_path} not found)"
    config = load_config(config_path)
    model = config.client_for_role(role)
    budget = None if config.budget.unbounded else BudgetTracker(config.budget, ledger=ledger)
    label = (
        f"tier {config.tier} (role {role} -> {getattr(model, 'provider', '?')}:"
        f"{getattr(model, 'model', '?')})"
    )
    return model, budget, label


def _wants_json(args: argparse.Namespace) -> bool:
    """True when the user asked for machine-readable output (Goal 21)."""
    return bool(getattr(args, "json", False))


def _emit_json(obj: object) -> int:
    """Print a single JSON document for a skill to parse (Goal 21). Read-only."""
    print(json.dumps(obj, indent=2, default=str))
    return 0


# Goal 21 — a side-effect-free plan/dry-run table. Each command names what it does so the
# conversational layer can "propose before it acts": whether the command mutates state /
# spends money, and whether it is governed (human-gated). Read-only commands are safe to
# run without confirmation; everything else should be confirmed first.
_PLAN_INFO: dict[str, dict[str, str]] = {
    "summarize-runs": {"effect": "read-only", "governance": "none"},
    "summarize-research": {"effect": "read-only", "governance": "none"},
    "provider-report": {"effect": "read-only", "governance": "none"},
    "list-approvals": {"effect": "read-only", "governance": "none"},
    "list-operators": {"effect": "read-only", "governance": "none"},
    "sandbox-backends": {"effect": "read-only", "governance": "none"},
    "check-docs": {"effect": "read-only", "governance": "none"},
    "pricing-audit": {"effect": "read-only", "governance": "none"},
    "verify-governance": {"effect": "read-only", "governance": "none"},
    "export-governance-packet": {"effect": "read-only", "governance": "none"},
    "storage-verify": {"effect": "read-only", "governance": "none"},
    "storage-export": {"effect": "writes files (export only)", "governance": "none"},
    "run-task": {"effect": "runs a loop; writes archives; spends at Tier ≥ 1", "governance": "none"},
    "run-training": {
        "effect": "runs training; writes archives; spends at Tier ≥ 1",
        "governance": "none",
    },
    "run-org": {"effect": "runs the org; writes archives; spends at Tier ≥ 1", "governance": "none"},
    "run-research": {
        "effect": "runs the org on research tasks; writes archives; spends at Tier ≥ 1",
        "governance": "none",
    },
    "propose-meta-change": {
        "effect": "writes a meta-change proposal (apply stays human-gated)",
        "governance": "proposal only; durable application is human-gated",
    },
    "run-scaled": {
        "effect": "runs an eval under a compute budget; writes archives",
        "governance": "compute-tier > 0 requires a human approval bound to (experiment, tier)",
    },
    "train-model": {
        "effect": "produces model weights; writes artifact archive",
        "governance": "requires a human-approved MODEL_TRAIN request + stability green",
    },
    "deploy-model": {
        "effect": "binds a trained artifact to a role; writes the registry",
        "governance": "requires a separate MODEL_DEPLOY approval + cross-model review",
    },
    "request-approval": {
        "effect": "records a pending governance request",
        "governance": "request only; a human still decides",
    },
    "approve": {
        "effect": "records an approval decision",
        "governance": "HUMAN-ONLY — run only on explicit human instruction with a real approver",
    },
    "deny": {
        "effect": "records a denial decision",
        "governance": "HUMAN-ONLY — run only on explicit human instruction",
    },
    "revoke": {
        "effect": "revokes a granted decision",
        "governance": "HUMAN-ONLY — run only on explicit human instruction",
    },
    "create-operator": {"effect": "writes the operator registry", "governance": "human-managed"},
    "revoke-operator": {"effect": "revokes a local operator", "governance": "human-managed"},
    "propose-external-experiment": {
        "effect": "records a pending EXTERNAL_EXPERIMENT request",
        "governance": "request only; a human still approves, and a human still runs the action",
    },
    "list-external-experiments": {"effect": "read-only", "governance": "none"},
    "ingest-external-result": {
        "effect": "records a signed external result bound to a live approval",
        "governance": "HUMAN-ONLY — only a human operator attests a real-world result",
    },
    "external-audit": {"effect": "read-only", "governance": "none"},
    "storage-migrate": {"effect": "creates/upgrades the SQLite store", "governance": "none"},
    "storage-import": {"effect": "writes rows into the SQLite store", "governance": "none"},
    "pilot-init": {"effect": "writes the fixed pilot plan + transcript", "governance": "none"},
    "pilot-run": {
        "effect": "runs pilot arms; frontier arms spend money; writes archives",
        "governance": "none (budget ceilings still apply)",
    },
    "pilot-report": {"effect": "writes the pilot report file", "governance": "none"},
}


def _config_tier_label(args: argparse.Namespace) -> str:
    """Best-effort tier label for a plan, derived from --config alone (config, not code)."""
    config_path = getattr(args, "config", None)
    if config_path is None:
        return "n/a (no model tier for this command)"
    name = Path(config_path).name
    if "tier0" in name:
        return "Tier 0 (local, offline, free)"
    if "tier1" in name:
        return "Tier 1 (frontier; spends money)"
    if "tier2" in name:
        return "Tier 2 (governed; human-gated)"
    return f"from {config_path}"


def _dry_run(args: argparse.Namespace, argv: list[str]) -> int:
    """Goal 21: print the command, tier, and governance implications without acting.

    Makes no state change, spends nothing, and writes no ledger row — this returns before
    the command handler is ever called. It is the machine-checkable form of "propose first".
    """
    command = getattr(args, "command", "") or ""
    reconstructed = "siro " + " ".join(tok for tok in argv if tok != "--dry-run")
    info = _PLAN_INFO.get(command, {"effect": "unknown", "governance": "unknown"})
    plan = {
        "dry_run": True,
        "command": command,
        "would_run": reconstructed,
        "tier": _config_tier_label(args),
        "effect": info["effect"],
        "governance": info["governance"],
        "read_only": info["effect"] == "read-only",
    }
    if _wants_json(args):
        return _emit_json(plan)
    print("DRY RUN — no state changed, nothing spent, no ledger row written.")
    print(f"  would run:   {plan['would_run']}")
    print(f"  tier:        {plan['tier']}")
    print(f"  effect:      {plan['effect']}")
    print(f"  governance:  {plan['governance']}")
    if not plan["read_only"]:
        print("  confirm before running: this is not a read-only action.")
    return 0


def _cmd_run_task(args: argparse.Namespace) -> int:
    ledger = ModelCallLedger(args.model_calls)
    model, budget, label = _build_runtime(args, ledger, role="implementation")
    controller = Controller(
        archive=JSONLArchive(args.archive),
        ledger=ledger,
        memory=ResearchMemory(args.memory),
        budget=budget,
    )
    print(f"config: {label}")
    try:
        result = controller.run_task(args.task_dir, model=model, generations=args.generations)
    except BudgetExceeded as exc:
        print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
        print("Escalation required: a human must approve raising the ceiling (config-only).")
        return 2

    print(f"run-task: {args.task_dir}  ({args.generations} generation(s))")
    for attempt in result.attempts:
        ev = attempt.evaluation
        print(
            f"  {attempt.candidate.candidate_id:>12}  "
            f"score={ev.score:>9.1f}  "
            f"pass={ev.passed_tests} fail={ev.failed_tests}  "
            f"{attempt.status.value:<8} {attempt.reason}"
        )
    best = result.best
    if best is not None:
        print(f"Best: {best.candidate.candidate_id} score={best.evaluation.score:.1f}")
        print(f"Archived {len(result.attempts)} attempt(s) to {args.archive}")
    return 0


def _cmd_run_training(args: argparse.Namespace) -> int:
    ledger = ModelCallLedger(args.model_calls)
    model, token_budget, label = _build_runtime(args, ledger, role="implementation")
    controller = TrainingController(
        archive=TrainingArchive(args.archive),
        ledger=ledger,
        budget_seconds=args.budget,
        budget=token_budget,
    )
    print(f"config: {label}")
    try:
        result = controller.run_training(args.task_dir, model=model, generations=args.generations)
    except BudgetExceeded as exc:
        print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
        print("Escalation required: a human must approve raising the ceiling (config-only).")
        return 2

    print(
        f"run-training: {args.task_dir}  "
        f"({args.generations} generation(s), {args.budget:g}s budget each)"
    )
    for attempt in result.attempts:
        r = attempt.result
        val = f"{r.val_loss:.6f}" if r and r.reproducible else "   n/a  "
        thr = f"{r.throughput:>8.0f}" if r and r.reproducible else "     n/a"
        print(
            f"  {attempt.attempt_id:>12}  val_loss={val}  "
            f"thr={thr}/s  {attempt.status.value:<8} {attempt.reason}"
        )
    best = result.best
    if best is not None and best.result is not None:
        print(f"Best: {best.attempt_id} val_loss={best.result.val_loss:.6f}")
        print(f"Archived {len(result.attempts)} training attempt(s) to {args.archive}")
    return 0


def _cmd_run_org(args: argparse.Namespace) -> int:
    """Run one full frontier-organization research cycle on a task (Goal 08).

    Binds every role to its provider from the tier config (Tier 0 = all local; Tier 1 =
    frontier reasoning + a different-provider safety reviewer). Lowering the tier is
    config-only — no code change. Needs the model server / API keys the config selects.
    """
    config = load_config(args.config)
    ledger = ModelCallLedger(args.model_calls)
    budget = None if config.budget.unbounded else BudgetTracker(config.budget, ledger=ledger)
    orchestrator = Orchestrator.from_config(
        config,
        memory=ResearchMemory(args.memory),
        archive=JSONLArchive(args.archive),
        ledger=ledger,
        budget=budget,
    )
    print(
        f"config: tier {config.tier} ({args.config}); cross-model review: "
        f"{'required' if orchestrator.require_cross_model else 'not required (all-local)'}"
    )
    try:
        result = orchestrator.run_cycle(args.objective, args.task_dir)
    except BudgetExceeded as exc:
        print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
        print("Escalation required: a human must approve raising the ceiling (config-only).")
        return 2

    print(f"run-org: {args.task_dir}  objective={args.objective!r}")
    for role in result.agent_outputs:
        agent_result = result.agent_outputs[role]
        provider = agent_result.response.provider or "?"
        print(f"  {role:>15}  [{provider}]")
    decision = result.promotion_decision.value
    print(f"Promotion decision: {decision.upper()}  (attempt {result.attempt.attempt_id})")
    if result.attempt.evaluation is not None:
        ev = result.attempt.evaluation
        print(f"  objective: score={ev.score:.1f} pass={ev.passed_tests} fail={ev.failed_tests}")
    for escalation in result.escalations:
        print(f"  ESCALATION: {escalation}")
    if result.next_actions:
        print(f"  next: {'; '.join(result.next_actions)}")
    print(f"Recorded 1 attempt to {args.archive} and memory to {args.memory}.")
    return 0


def _cmd_run_research(args: argparse.Namespace) -> int:
    """Run the full org on research-shaped task(s) (Goal 09).

    With a ``task_dir`` it runs one cycle on that task; with none it runs one cycle on every
    task discovered under the configured pack's tasks/ directory — so "the Tier 1 org runs a full lifecycle on
    each task family" is one command. Promotion is decided by each task's own ``eval.py``
    (the objective evaluator), not by any model. Lowering the tier is config-only.
    """
    config = load_config(args.config)
    ledger = ModelCallLedger(args.model_calls)
    budget = None if config.budget.unbounded else BudgetTracker(config.budget, ledger=ledger)
    orchestrator = Orchestrator.from_config(
        config,
        memory=ResearchMemory(args.memory),
        ledger=ledger,
        budget=budget,
        research_archive=ResearchArchive(args.archive),
    )
    if args.task_dir is not None:
        tasks = [args.task_dir]
    else:
        discovered = discover_research_tasks(args.tasks_root, pack_id=config.pack)
        if not discovered:
            root_label = args.tasks_root or f"pack {config.pack!r}"
            print(f"No research tasks found under {root_label}.")
            return 0
        tasks = [Path(t.path) for t in discovered]

    print(
        f"config: tier {config.tier} ({args.config}); cross-model review: "
        f"{'required' if orchestrator.require_cross_model else 'not required (all-local)'}"
    )
    print(f"run-research: {len(tasks)} task(s), objective={args.objective!r}")
    for task_dir in tasks:
        try:
            result = orchestrator.run_research_cycle(args.objective, task_dir)
        except BudgetExceeded as exc:
            print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
            print("Escalation required: a human must approve raising the ceiling (config-only).")
            return 2
        metric = result.metric
        primary = (
            f"{metric.primary_name}={metric.primary:g} passed={metric.passed}"
            if metric is not None
            else "(not evaluated)"
        )
        print(
            f"  [{result.family:>9}] {result.task_id:<16} "
            f"{result.promotion_decision.value.upper():<9} {primary}"
        )
        for escalation in result.escalations:
            print(f"      ESCALATION: {escalation}")
    print(f"Recorded research attempts to {args.archive} and memory to {args.memory}.")
    return 0


def _cmd_summarize_research(args: argparse.Namespace) -> int:
    """Per-family suite summary (Goal 09 acceptance): pass rate, median cycles to success,
    safety-gate failures, token/USD spend, and strategy diversity."""
    if args.store is not None:
        store = SQLiteStore(args.store, migrate=False)
        attempts = store.read("research_attempts")
        ledger_rows = store.read("model_calls")
        source = f"{args.store} (sqlite)"
    else:
        attempts = ResearchArchive(args.path).read_all()
        ledger_rows = (
            ModelCallLedger(args.model_calls).read_all() if args.model_calls.exists() else []
        )
        source = str(args.path)
    if not attempts:
        if _wants_json(args):
            return _emit_json({"source": source, "total_attempts": 0, "families": {}})
        print(f"No research attempts found in {source}.")
        return 0
    summaries = summarize_research(attempts, ledger_rows=ledger_rows)

    if _wants_json(args):
        return _emit_json(
            {
                "source": source,
                "total_attempts": len(attempts),
                "families": {family: asdict(s) for family, s in summaries.items()},
            }
        )

    print(f"Research attempts: {len(attempts)}  (from {source})")
    for family, s in summaries.items():
        cycles = (
            f"{s.median_cycles_to_success:.1f}" if s.median_cycles_to_success is not None else "n/a"
        )
        print(f"\n[{family}]  tasks: {', '.join(s.task_ids)}")
        cost_per = "n/a" if s.cost_per_promotion is None else f"${s.cost_per_promotion:.4f}"
        print(
            f"  attempts={s.attempts}  accepted={s.accepted}  promoted={s.promoted}  "
            f"mixed={s.mixed}  failed={s.failed}  pass_rate={s.pass_rate:.0%}"
        )
        print(f"  median cycles to success: {cycles}")
        print(
            f"  gate failures: safety={s.safety_gate_failures} "
            f"hidden={s.hidden_test_failures} reproducibility={s.reproducibility_failures}"
        )
        print(f"  spend: {s.tokens} tokens  ${s.cost_usd:.4f}  cost/promotion={cost_per}")
        print(f"  strategy diversity: {s.strategy_diversity:.0%}  (distinct candidates / attempts)")
    return 0


def _cmd_summarize_runs(args: argparse.Namespace) -> int:
    if args.store is not None:
        store = SQLiteStore(args.store, migrate=False)
        attempts = store.read("attempts")
        source = f"{args.store} (sqlite)"
    else:
        attempts = JSONLArchive(args.path).read_all()
        source = str(args.path)
    if not attempts:
        if _wants_json(args):
            return _emit_json({"source": source, "total_attempts": 0})
        print(f"No attempts found in {source}.")
        return 0

    status_counts = Counter(a.status.value for a in attempts)
    evaluated = [a for a in attempts if a.evaluation is not None]
    total_tests = sum(a.evaluation.passed_tests + a.evaluation.failed_tests for a in evaluated)
    passed_tests = sum(a.evaluation.passed_tests for a in evaluated)
    pass_rate = (passed_tests / total_tests) if total_tests else 0.0
    best = select_best(attempts)
    failure_modes = Counter(
        failure_signature(a.reason) for a in attempts if failure_signature(a.reason) != "none"
    )

    if _wants_json(args):
        return _emit_json(
            {
                "source": source,
                "total_attempts": len(attempts),
                "status_counts": dict(status_counts),
                "test_pass_rate": pass_rate,
                "passed_tests": passed_tests,
                "total_tests": total_tests,
                "best": (
                    None
                    if best is None
                    else {"attempt_id": best.attempt_id, "score": best.evaluation.score}
                ),
                "top_failure_modes": dict(failure_modes.most_common(5)),
            }
        )

    print(f"Attempts: {len(attempts)}  (from {source})")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    print(f"Test pass rate: {pass_rate:.1%}  ({passed_tests}/{total_tests})")
    if best is not None:
        print(f"Best score: {best.evaluation.score:.1f}  (attempt {best.attempt_id})")

    # Top recurring failure modes — reflect on negative results (Goal 03).
    if failure_modes:
        print("Top failure modes:")
        for signature, count in failure_modes.most_common(5):
            print(f"  {signature}: {count}")
    return 0


def _print_meta_change(record: MetaChangeRecord) -> None:
    """Render a meta-change record: the proposal, A/B deltas, and the gating reminder."""
    proposal = record.proposal
    print(f"Proposed meta-change [{proposal.kind.value}] target={proposal.target}")
    print(f"  {proposal.description}")
    print(f"  Rationale: {proposal.rationale}")
    print(f"  Rollback:  {proposal.rollback_plan}")
    if not proposal.bounds_ok:
        print(f"  BOUNDS: out of bounds — {proposal.forbidden_reason} (cannot be applied)")

    ab = record.ab_result
    if ab is not None:
        print(f"A/B on {len(ab.benchmark_tasks)} task(s), {ab.generations} generation(s) each:")
        print(
            f"  pass_rate            {ab.baseline.pass_rate:.0%} -> {ab.candidate.pass_rate:.0%}"
            f"  (Δ {ab.deltas['pass_rate']:+.2f})"
        )
        print(
            f"  median gens->success {ab.baseline.median_generations_to_success:.1f} -> "
            f"{ab.candidate.median_generations_to_success:.1f}"
            f"  (Δ {ab.deltas['median_generations_to_success']:+.1f})"
        )
        print(
            f"  invalid candidates   {ab.baseline.invalid_candidates} -> "
            f"{ab.candidate.invalid_candidates}"
        )
        print(
            f"  safety gate failures {ab.baseline.safety_gate_failures} -> "
            f"{ab.candidate.safety_gate_failures}"
        )
        print(
            f"  score/generation     {ab.baseline.score_improvement_per_generation:.1f} -> "
            f"{ab.candidate.score_improvement_per_generation:.1f}"
        )

    print(f"Recommendation: {record.recommendation.value} — {record.reason}")
    if record.recommendation is MetaRecommendation.PROMOTE:
        print("Durable application is human-gated: set approved=True before applying.")
    print("Reminder: meta-changes are proposals only; promotion is human-gated.")


def _cmd_propose_meta_change(args: argparse.Namespace) -> int:
    archive = JSONLArchive(args.path)
    store = MetaChangeStore(args.store)
    researcher = MetaResearcher(
        archive=archive,
        store=store,
        benchmark_tasks=list(args.benchmark),
        generations=args.generations,
    )
    print(f"propose-meta-change: read {len(archive.read_all())} attempt(s) from {args.path}")

    if args.validate:
        record = researcher.run(model_factory=lambda: LocalOpenAIClient())
    else:
        # Propose + record without running A/B (no model server needed). The record is
        # stored as a pending rejection until validation runs — proposals are kept
        # separately and audited either way.
        proposal = researcher.propose()
        record = MetaChangeRecord(
            record_id=proposal.meta_change_id,
            proposal=proposal,
            recommendation=MetaRecommendation.REJECT,
            reason="A/B validation not run (pass --validate to A/B on the benchmark)",
        )
        store.append(record)

    _print_meta_change(record)
    print(f"Recorded meta-change to {store.path} (separate from candidate attempts).")
    return 0


# --- governance (Tier 2, Goal 10) ------------------------------------------ #


def _expires_at(seconds: float | None):
    """Absolute UTC expiry from a relative ``--expires-in`` (seconds), or ``None``."""
    if seconds is None:
        return None
    from datetime import timedelta

    from .schemas import _utcnow

    return _utcnow() + timedelta(seconds=seconds)


def _cmd_request_approval(args: argparse.Namespace) -> int:
    """Record a pending governance request (an escalation). Human-operated; never an agent."""
    gate = GovernanceGate(ApprovalLedger(args.ledger))
    payload = json.loads(args.payload) if args.payload else None
    req = gate.request(
        GovernedAction(args.action),
        args.target,
        actor=args.actor,
        rationale=args.rationale,
        payload=payload,
        risk=args.risk,
        evidence=args.evidence,
        rollback_plan=args.rollback_plan,
        scope=ApprovalScope(args.scope),
        expires_at=_expires_at(args.expires_in),
    )
    print(f"requested {req.action.value} (request {req.request_id})")
    print(f"  target:  {req.target or '(none)'}")
    print(f"  hash:    {req.content_hash}")
    print(f"  scope:   {req.scope.value}  expires: {req.expires_at or 'never'}")
    print(f"A human must approve: siro approve {req.request_id} --by <human>")
    print(f"Recorded to {args.ledger}.")
    return 0


def _cmd_list_approvals(args: argparse.Namespace) -> int:
    gate = GovernanceGate(ApprovalLedger(args.ledger))
    requests = gate.ledger.requests()
    rows = [
        {
            "request_id": req.request_id,
            "status": gate.status_of(req.request_id),
            "action": req.action.value,
            "target": req.target or None,
            "actor": req.actor or None,
        }
        for req in requests
    ]
    if args.status:
        rows = [r for r in rows if r["status"] == args.status]
    if _wants_json(args):
        return _emit_json({"ledger": str(args.ledger), "requests": rows})
    if not requests:
        print(f"No approval requests in {args.ledger}.")
        return 0
    print(f"Approval requests in {args.ledger}:")
    for r in rows:
        print(
            f"  {r['request_id']}  {r['status']:<8} {r['action']:<26} "
            f"target={r['target'] or '-'}  by={r['actor'] or '-'}"
        )
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    config = load_config(args.config) if args.config else None
    gate = (
        GovernanceGate.from_config(config, ledger=ApprovalLedger(args.ledger))
        if config
        else GovernanceGate(ApprovalLedger(args.ledger))
    )
    try:
        decision = gate.approve(
            args.request_id,
            by=args.by,
            expires_at=_expires_at(args.expires_in),
            signature=args.signature,
            signing_key=args.signing_key,
        )
    except (KeyError, ValueError) as exc:
        print(f"cannot approve: {exc}")
        return 2
    print(
        f"APPROVED {decision.action.value} (request {decision.request_id}) by {decision.approver}"
    )
    print(
        f"  decision {decision.decision_id}  scope={decision.scope.value}  "
        f"expires: {decision.expires_at or 'never'}"
    )
    print(f"Recorded to {args.ledger}.")
    return 0


def _cmd_deny(args: argparse.Namespace) -> int:
    config = load_config(args.config) if args.config else None
    gate = (
        GovernanceGate.from_config(config, ledger=ApprovalLedger(args.ledger))
        if config
        else GovernanceGate(ApprovalLedger(args.ledger))
    )
    try:
        decision = gate.deny(
            args.request_id,
            by=args.by,
            reason=args.reason,
            signature=args.signature,
            signing_key=args.signing_key,
        )
    except (KeyError, ValueError) as exc:
        print(f"cannot deny: {exc}")
        return 2
    print(f"DENIED {decision.action.value} (request {decision.request_id}) by {decision.approver}")
    print(f"Recorded to {args.ledger}.")
    return 0


def _cmd_revoke(args: argparse.Namespace) -> int:
    gate = GovernanceGate(ApprovalLedger(args.ledger))
    rv = gate.revoke(args.decision_id, by=args.by, reason=args.reason)
    print(f"REVOKED decision {rv.decision_id} by {rv.by or '(unknown)'}")
    print(f"Recorded to {args.ledger}.")
    return 0


def _cmd_create_operator(args: argparse.Namespace) -> int:
    ledger = OperatorLedger(args.operators)
    try:
        identity = ledger.create(
            args.operator_id,
            display_name=args.display_name,
            role=OperatorRole(args.role),
            auth_method=args.auth_method,
        )
    except ValueError as exc:
        print(f"cannot create operator: {exc}")
        return 2
    print(f"CREATED operator {identity.operator_id} ({identity.role.value})")
    print(f"Recorded to {args.operators}.")
    return 0


def _cmd_list_operators(args: argparse.Namespace) -> int:
    identities = OperatorLedger(args.operators).latest()
    if not identities:
        print(f"No operators in {args.operators}.")
        return 0
    print(f"Operators in {args.operators}:")
    for identity in identities.values():
        print(
            f"  {identity.operator_id:<16} {identity.status.value:<8} "
            f"{identity.role.value:<10} {identity.display_name}"
        )
    return 0


def _cmd_revoke_operator(args: argparse.Namespace) -> int:
    try:
        identity = OperatorLedger(args.operators).revoke(args.operator_id)
    except KeyError as exc:
        print(f"cannot revoke operator: {exc}")
        return 2
    print(f"REVOKED operator {identity.operator_id}")
    print(f"Recorded to {args.operators}.")
    return 0


def _cmd_verify_governance(args: argparse.Namespace) -> int:
    config = load_config(args.config) if args.config else None
    gate = (
        GovernanceGate.from_config(config, ledger=ApprovalLedger(args.ledger))
        if config
        else GovernanceGate(ApprovalLedger(args.ledger))
    )
    result = gate.verify()
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")
    if not result.ok:
        print(f"Governance ledger verification FAILED for {args.ledger}.")
        return 1
    print(f"Governance ledger verification OK for {args.ledger}.")
    return 0


def _cmd_export_governance_packet(args: argparse.Namespace) -> int:
    config = load_config(args.config) if args.config else None
    gate = (
        GovernanceGate.from_config(config, ledger=ApprovalLedger(args.ledger))
        if config
        else GovernanceGate(ApprovalLedger(args.ledger))
    )
    try:
        packet = gate.governance_packet(args.request_id)
    except KeyError as exc:
        print(f"cannot export governance packet: {exc}")
        return 2
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


# --- governed external experiments (Tier 2, Goal 26) ----------------------- #


def _external_gate(args: argparse.Namespace) -> GovernanceGate:
    config = load_config(args.config) if getattr(args, "config", None) else None
    if config:
        return GovernanceGate.from_config(config, ledger=ApprovalLedger(args.ledger))
    return GovernanceGate(ApprovalLedger(args.ledger))


def _cmd_propose_external_experiment(args: argparse.Namespace) -> int:
    """Record a typed EXTERNAL_EXPERIMENT request (propose step). A human still approves."""
    gate = _external_gate(args)
    task = load_research_task(args.task_dir)
    candidate = (
        args.candidate.read_text(encoding="utf-8") if args.candidate else task.surface_code
    )
    spec = external_spec_for(task, candidate)
    req = propose_external_experiment(
        gate,
        spec,
        actor=args.actor,
        rationale=args.rationale,
        rollback_plan=args.rollback_plan,
        evidence=args.evidence,
    )
    print(f"requested external_experiment (request {req.request_id})")
    print(f"  class:   {spec.action_class.value}  target: {spec.task_id}")
    print(f"  measure: {spec.measurement} ({spec.primary_name})")
    print(f"  cost:    ${spec.cost_usd:g}  risk: {spec.risk}  irreversible: {spec.irreversible}")
    print(f"  hash:    {req.content_hash}")
    print(f"A human must approve: siro approve {req.request_id} --by <human>")
    print("Then a human runs the action OUTSIDE siro and ingests a signed result:")
    print(f"  siro ingest-external-result {req.request_id} --operator <id> --primary <v> --signing-key <key>")
    print(f"Recorded to {args.ledger}.")
    return 0


def _cmd_list_external_experiments(args: argparse.Namespace) -> int:
    gate = _external_gate(args)
    requests = [
        r for r in gate.ledger.requests() if r.action is GovernedAction.EXTERNAL_EXPERIMENT
    ]
    results = ExternalResultLedger(args.results)
    rows = []
    for req in requests:
        status = gate.status_of(req.request_id)
        ingested = [r for r in results.for_request(req.request_id) if r.status.value != "rejected"]
        rows.append(
            {
                "request_id": req.request_id,
                "status": status,
                "class": req.payload.get("action_class", "?"),
                "target": req.target or None,
                "result": (ingested[-1].status.value if ingested else None),
            }
        )
    if args.status:
        rows = [r for r in rows if r["status"] == args.status]
    if _wants_json(args):
        return _emit_json({"ledger": str(args.ledger), "external_experiments": rows})
    if not rows:
        print(f"No external experiments in {args.ledger}.")
        return 0
    print(f"External experiments in {args.ledger}:")
    for r in rows:
        print(
            f"  {r['request_id']}  {r['status']:<8} {r['class']:<14} "
            f"target={r['target'] or '-'}  result={r['result'] or 'awaiting'}"
        )
    return 0


def _cmd_ingest_external_result(args: argparse.Namespace) -> int:
    """Attach a signed external result to a live approval (human-operated; never an agent)."""
    gate = _external_gate(args)
    results = ExternalResultLedger(args.results)
    try:
        record = ingest_external_result(
            gate,
            results,
            args.request_id,
            status=ExternalResultStatus(args.status),
            primary=args.primary,
            passed=not args.failed and args.status == ExternalResultStatus.OK.value,
            secondary=json.loads(args.secondary) if args.secondary else None,
            operator_id=args.operator,
            provenance=args.provenance,
            reason=args.reason,
            signature=args.signature,
            signing_key=args.signing_key,
        )
    except ExternalResultRejected as exc:
        print(f"REJECTED external result: {exc.reason}")
        print(f"  logged to {args.results} (result {exc.record.result_id})")
        return 2
    print(f"INGESTED external result {record.result_id} ({record.status.value})")
    print(f"  request {record.request_id}  decision {record.decision_id}")
    print(f"  {record.primary_name}={record.primary:g}  passed={record.passed}")
    print(f"  operator {record.operator_id}  provenance={record.provenance or '-'}")
    print(f"Recorded to {args.results}.")
    return 0


def _cmd_external_audit(args: argparse.Namespace) -> int:
    gate = _external_gate(args)
    results = ExternalResultLedger(args.results)
    requests = [
        r for r in gate.ledger.requests() if r.action is GovernedAction.EXTERNAL_EXPERIMENT
    ]
    if args.request_id:
        requests = [r for r in requests if r.request_id == args.request_id]
    trail = []
    for req in requests:
        decisions = [d for d in gate.ledger.decisions() if d.request_id == req.request_id]
        trail.append(
            {
                "request": req.model_dump(mode="json"),
                "status": gate.status_of(req.request_id),
                "decisions": [d.model_dump(mode="json") for d in decisions],
                "results": [r.model_dump(mode="json") for r in results.for_request(req.request_id)],
            }
        )
    print(json.dumps({"external_experiments": trail}, indent=2, sort_keys=True, default=str))
    return 0


# --- governed compute scale-up (Tier 2, Goal 11) --------------------------- #


def _cmd_run_scaled(args: argparse.Namespace) -> int:
    """Run a research eval under a governed compute budget (Goal 11).

    The default compute tier is free; a larger tier requires both a recorded pass at the
    smaller tier (promotion-before-budget) and a human-approved governance request (Goal 10).
    A wall-clock or memory ceiling breach halts and escalates. Lowering the tier is config-only.
    """
    config = load_config(args.config)
    gate = GovernanceGate.from_config(config)
    policy = backend_policy_from_config(config)
    runner = ScaledRunner(
        gate,
        archive=ResearchArchive(args.archive),
        checkpoints=CheckpointStore(args.checkpoints),
        tiers=compute_tiers_from_config(config),
        backend=args.backend,
        policy=policy,
    )
    task = load_research_task(args.task_dir)
    candidate = args.candidate.read_text(encoding="utf-8") if args.candidate else task.surface_code
    experiment_id = args.experiment_id or task.task_id
    backend_name = args.backend or policy.default_backend
    hard_note = (
        f"; hard backend required above tier {policy.hard_backend_above_tier}"
        if policy.hard_backend_above_tier is not None
        else ""
    )
    print(
        f"config: tier {config.tier} ({args.config}); governance "
        f"{'on' if gate.enabled else 'off (compute tier > 0 needs Tier 2)'}; "
        f"backend={backend_name}{hard_note}"
    )
    print(
        f"run-scaled: {task.task_id}  compute-tier={args.compute_tier}  experiment={experiment_id}"
    )
    try:
        result = runner.run(
            task,
            candidate,
            compute_tier=args.compute_tier,
            experiment_id=experiment_id,
            actor=args.actor,
            rationale=args.rationale,
        )
    except BackendPolicyError as exc:
        print(f"BLOCKED — {exc}")
        print(
            "Use a hard-isolation backend (e.g. --backend linux_guarded on a supported host) "
            "or set compute.allow_local_dev for local development only."
        )
        return 2
    except ComputeAllocationError as exc:
        print(f"BLOCKED — {exc}")
        print("Pass the smaller compute tier first (promotion-before-budget), then retry.")
        return 2
    except GovernanceDenied as exc:
        print(
            f"BLOCKED — compute tier {args.compute_tier} needs human approval "
            f"(request {exc.request.request_id})."
        )
        print(f"Approve with: siro approve {exc.request.request_id} --by <human>")
        return 2
    except BudgetExceeded as exc:
        print(
            f"HALTED — compute ceiling breached ({exc.kind}): {exc} "
            f"(limit {exc.limit:g}, observed {exc.observed:g})"
        )
        print("Escalation required: a human must approve a larger compute tier (governed).")
        return 2

    m = result.metric
    procs = "" if result.budget.max_processes is None else f" procs={result.budget.max_processes}"
    print(
        f"  budget: wall_clock={result.budget.wall_clock_seconds:g}s "
        f"memory={result.budget.memory_mb}MB{procs}  backend={result.backend}"
    )
    print(
        f"  metric: {m.primary_name}={m.primary:g} passed={m.passed} peak_mem={result.peak_memory_mb:.0f}MB"
    )
    print(
        f"  {result.attempt.status.value} — archived to {args.archive}; checkpoint in {args.checkpoints}"
    )
    return 0


def _cmd_sandbox_backends(args: argparse.Namespace) -> int:
    """Report which execution-plane isolation backends are usable here (Goal 15).

    ``local`` is the portable developer fallback (always available); ``linux_guarded`` is the
    hard, OS-enforced cgroup backend used for trusted compute scale-up.
    """
    print("Sandbox resource-isolation backends:")
    for name, (usable, reason) in available_backends().items():
        mark = "available" if usable else "unavailable"
        print(f"  {name}: {mark} — {reason}")
    return 0


# --- durable storage (Goal 16) --------------------------------------------- #


def _cmd_storage_migrate(args: argparse.Namespace) -> int:
    """Create or migrate the SQLite store schema to the latest version (Goal 16)."""
    store = SQLiteStore(args.store, migrate=False)
    before = store.schema_version()
    after = store.migrate()
    print(f"storage: {args.store} (sqlite)  schema {before} -> {after}")
    return 0


def _cmd_storage_import(args: argparse.Namespace) -> int:
    """Import the existing JSONL archives into the SQLite store (idempotent, Goal 16)."""
    store = SQLiteStore(args.store)
    jsonl = JSONLStore(args.from_dir)
    total = 0
    print(f"storage import -> {args.store} (sqlite)")
    for stream in STREAMS:
        src = jsonl.path_for(stream)
        if not src.exists():
            continue
        inserted = store.import_jsonl(stream, src)
        total += inserted
        print(f"  {stream}: {inserted} new record(s) from {src}")
    print(f"imported {total} new record(s) (duplicates skipped by idempotency key)")
    return 0


def _cmd_storage_export(args: argparse.Namespace) -> int:
    """Export the SQLite store back to JSONL files compatible with existing readers (Goal 16)."""
    store = SQLiteStore(args.store, migrate=False)
    out_dir = args.to_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    print(f"storage export {args.store} (sqlite) -> {out_dir}/")
    for stream in STREAMS:
        path = out_dir / f"{stream}.jsonl"
        count = store.export_jsonl(stream, path)
        if count:
            total += count
            print(f"  {stream}: {count} record(s) -> {path}")
    print(f"exported {total} record(s)")
    return 0


def _cmd_storage_verify(args: argparse.Namespace) -> int:
    """Verify the tamper-evident hash chains in the SQLite store (Goal 16)."""
    store = SQLiteStore(args.store, migrate=False)
    streams = (
        [args.stream] if args.stream else [s for s, spec in STREAMS.items() if spec.hash_chained]
    )
    ok = True
    print(f"storage verify {args.store} (sqlite)")
    for stream in streams:
        result = store.verify_chain(stream)
        if not result.supported:
            print(f"  {stream}: not hash-chained")
            continue
        status = "OK" if result.ok else f"BROKEN at seq {result.broken_seq}"
        print(f"  {stream}: {status}  ({result.checked} record(s))")
        ok = ok and result.ok
    return 0 if ok else 1


# --- governed model-training (Tier 2, Goal 12) ----------------------------- #


def _cmd_train_model(args: argparse.Namespace) -> int:
    """Run a governed weight-update experiment (Goal 12).

    Refused below Tier 2, when the scaffold is not stable (independent of approval), or
    without a human-approved MODEL_TRAIN request. Produces a weight artifact with full
    lineage; it is **never** auto-deployed — binding to a role is a separate `deploy-model`.
    """
    config = load_config(args.config)
    gate = GovernanceGate.from_config(config)
    trainer = GovernedModelTrainer(
        gate,
        archive=ModelArtifactArchive(args.archive),
        store=ArtifactStore(args.store),
    )
    stability = assess_stability(open_incidents=args.open_incidents)
    train_config = {"learning_rate": args.learning_rate, "epochs": args.epochs}
    print(
        f"config: tier {config.tier} ({args.config}); governance "
        f"{'on' if gate.enabled else 'off (model-training is Tier 2)'}; "
        f"stability {'green' if stability.stable else 'RED ' + str(stability.failures)}"
    )
    try:
        artifact = trainer.train(
            args.experiment_id,
            train_config,
            compute_tier=args.compute_tier,
            actor=args.actor,
            rationale=args.rationale,
            stability=stability,
        )
    except ModelTrainingDisabled as exc:
        print(f"BLOCKED — {exc}")
        return 2
    except StabilityError as exc:
        print(f"BLOCKED — {exc}")
        return 2
    except GovernanceDenied as exc:
        print(
            f"BLOCKED — weight-update experiment needs human approval "
            f"(request {exc.request.request_id})."
        )
        print(f"Approve with: siro approve {exc.request.request_id} --by <human>")
        return 2

    print(
        f"trained artifact {artifact.artifact_id}  passed={artifact.passed}  "
        f"val_loss={artifact.val_loss:g}"
    )
    print(
        f"  lineage: base={artifact.base_model_hash} data={artifact.data_id}@{artifact.data_seed} "
        f"code={artifact.code_version}"
    )
    print(f"  stored in {args.store}; archived to {args.archive}")
    print("NOT deployed — `siro deploy-model` is a separate approval + cross-model review.")
    return 0


def _cmd_deploy_model(args: argparse.Namespace) -> int:
    """Bind a trained artifact to an agent role — only with approval + cross-model review."""
    config = load_config(args.config)
    gate = GovernanceGate.from_config(config)
    artifact = ArtifactStore(args.store).load(args.artifact_id)
    if artifact is None:
        print(f"no trained artifact {args.artifact_id!r} in {args.store}.")
        return 2
    registry = ModelRegistry(args.registry)
    try:
        deployment = deploy_model(
            gate,
            registry,
            artifact,
            args.role,
            implementation_provider=args.implementation_provider,
            reviewer_provider=args.reviewer_provider,
            actor=args.actor,
        )
    except DeploymentError as exc:
        print(f"BLOCKED — {exc}")
        return 2
    except GovernanceDenied as exc:
        print(
            f"BLOCKED — deploying to role {args.role!r} needs human approval "
            f"(request {exc.request.request_id})."
        )
        print(f"Approve with: siro approve {exc.request.request_id} --by <human>")
        return 2

    print(
        f"DEPLOYED artifact {deployment.artifact_id} -> role {deployment.role} "
        f"(approver {deployment.approver}, reviewer {deployment.reviewer_provider})"
    )
    print(f"Recorded to {args.registry}.")
    return 0


def _cmd_check_docs(args: argparse.Namespace) -> int:
    result = check_docs(root=args.root, manifest_path=args.manifest)
    if result.ok:
        print(
            "docs check passed: "
            f"{result.checked_goal_count} goals, "
            f"{result.checked_doc_count} numbered docs, "
            f"{result.checked_privacy_file_count} privacy-scanned files"
        )
        return 0
    print("docs check failed:")
    for error in result.errors:
        print(f"- {error}")
    return 1


def _representative_costs(pricing: Pricing) -> dict[str, float]:
    cycles = {
        "small": (10_000, 2_000),
        "medium": (100_000, 20_000),
        "heavy": (1_000_000, 200_000),
    }
    return {
        name: pricing.cost_usd(input_tokens, output_tokens)
        for name, (input_tokens, output_tokens) in cycles.items()
    }


def _cmd_pricing_audit(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    threshold = args.stale_days
    today = date.today()
    errors = 0

    print(f"Pricing audit: {args.config} (tier {config.tier})")
    print(
        "Budget ceilings: "
        f"run=${config.budget.max_usd_per_run if config.budget.max_usd_per_run is not None else 'unbounded'} "
        f"day=${config.budget.max_usd_per_day if config.budget.max_usd_per_day is not None else 'unbounded'} "
        f"tokens/call={config.budget.max_tokens_per_call if config.budget.max_tokens_per_call is not None else 'unbounded'}"
    )
    print(
        "Representative cycle costs use input/output token counts: small=10k/2k, medium=100k/20k, heavy=1M/200k."
    )

    for key, provider in sorted(config.providers.items()):
        backend = provider.backend.lower()
        pricing = Pricing.resolve(backend, provider.name, provider.prices)
        age = pricing.review_age_days(today)
        costs = _representative_costs(pricing)
        warnings: list[str] = []

        if pricing.missing:
            warnings.append("missing-price")
        local_free = backend in {"local", "llamacpp"} and pricing.cost_usd(1, 1) == 0.0
        if not local_free:
            if age is None:
                warnings.append("missing-review-date")
            elif age > threshold:
                warnings.append(f"stale-review:{age}d")
        if warnings:
            errors += 1

        reviewed = pricing.last_reviewed or "unreviewed"
        cached = (
            "n/a"
            if pricing.cached_input_per_mtok is None
            else f"${pricing.cached_input_per_mtok:g}/M"
        )
        print(
            f"{key}: backend={provider.backend} model={provider.name} "
            f"source={pricing.source_type} input=${pricing.input_per_mtok:g}/M "
            f"output=${pricing.output_per_mtok:g}/M cached_input={cached} "
            f"reviewed={reviewed} source_note={pricing.source or 'n/a'} "
            f"small=${costs['small']:.4f} medium=${costs['medium']:.4f} "
            f"heavy=${costs['heavy']:.4f} warnings={','.join(warnings) or 'none'}"
        )

    if args.strict and errors:
        print(f"STRICT FAIL: {errors} provider price record(s) need review.")
        return 1
    return 0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def _cmd_provider_report(args: argparse.Namespace) -> int:
    rows = ModelCallLedger(args.model_calls).read_all() if args.model_calls.exists() else []
    if not rows:
        if _wants_json(args):
            return _emit_json({"source": str(args.model_calls), "rows": 0, "groups": []})
        print(f"No model-call ledger rows found in {args.model_calls}.")
        return 0

    research_attempts = (
        ResearchArchive(args.research_attempts).read_all()
        if args.research_attempts.exists()
        else []
    )
    promoted_tasks = {a.task_id for a in research_attempts if a.status is AttemptStatus.PROMOTED}
    task_family = {a.task_id: (a.family or "(unknown)") for a in research_attempts}

    groups: dict[tuple[str, str, str], list] = {}
    for row in rows:
        groups.setdefault((row.provider, row.model, row.role or "(unknown)"), []).append(row)

    report: list[dict] = []
    for (provider, model, role), scoped in sorted(groups.items()):
        tokens = sum(r.input_tokens + r.output_tokens for r in scoped)
        cost = sum(r.cost_usd for r in scoped)
        latencies = [r.latency_ms for r in scoped if r.latency_ms]
        errors = [r for r in scoped if r.final_error_kind]
        retries = sum(r.retry_count for r in scoped)
        promoted = len({r.experiment_id for r in scoped if r.experiment_id in promoted_tasks})
        family_spend: dict[str, float] = {}
        for row in scoped:
            family = task_family.get(row.experiment_id, "(unknown)")
            family_spend[family] = family_spend.get(family, 0.0) + row.cost_usd
        report.append(
            {
                "provider": provider,
                "model": model,
                "role": role,
                "calls": len(scoped),
                "tokens": tokens,
                "cost_usd": cost,
                "latency_p50_ms": _percentile(latencies, 50),
                "latency_p95_ms": _percentile(latencies, 95),
                "retries": retries,
                "error_rate": len(errors) / len(scoped),
                "escalations": len(errors),
                "cost_per_promotion": (cost / promoted) if promoted else None,
                "spend_by_family": dict(sorted(family_spend.items())),
                "error_kinds": dict(Counter(r.final_error_kind for r in errors)),
            }
        )

    if _wants_json(args):
        return _emit_json({"source": str(args.model_calls), "rows": len(rows), "groups": report})

    print(f"Provider report: {len(rows)} model-call row(s) from {args.model_calls}")
    for g in report:
        cost_per = "n/a" if g["cost_per_promotion"] is None else f"${g['cost_per_promotion']:.4f}"
        print(
            f"\n[{g['provider']}/{g['model']} role={g['role']}] "
            f"calls={g['calls']} tokens={g['tokens']} cost=${g['cost_usd']:.4f}"
        )
        print(f"  latency_ms: p50={g['latency_p50_ms']:.1f} p95={g['latency_p95_ms']:.1f}")
        print(
            f"  retries={g['retries']} error_rate={g['error_rate']:.0%} "
            f"escalations={g['escalations']} cost_per_promotion={cost_per}"
        )
        print(
            "  spend_by_family: "
            + ", ".join(f"{family}=${amount:.4f}" for family, amount in g["spend_by_family"].items())
        )
        if g["error_kinds"]:
            print(
                "  error_kinds: "
                + ", ".join(f"{kind}={count}" for kind, count in g["error_kinds"].items())
            )
    return 0


def _cmd_pilot_init(args: argparse.Namespace) -> int:
    plan_path = (
        args.root / "pilot_plan.json"
        if args.plan == DEFAULT_PILOT_PLAN_PATH and args.root != DEFAULT_PILOT_ROOT
        else args.plan
    )
    plan = write_default_pilot_plan(plan_path)
    transcript = write_command_transcript(plan, plan_path.parent)
    archived_configs = archive_pilot_configs(plan, plan_path.parent)
    print(f"Wrote pilot plan to {plan_path}.")
    print(f"Wrote command transcript to {transcript}.")
    print("Archived configs: " + ", ".join(str(path) for path in archived_configs))
    print(f"Expected report path: {plan.expected_report_path}")
    return 0


def _cmd_pilot_run(args: argparse.Namespace) -> int:
    plan = PilotPlan.from_path(args.plan)
    root = args.plan.parent
    arms = plan.arms
    if args.arm:
        arms = [arm for arm in arms if arm.name == args.arm]
        if not arms:
            print(f"unknown pilot arm {args.arm!r}")
            return 2
    elif not args.include_conditional:
        arms = [arm for arm in arms if not arm.condition]

    print(f"pilot-run: {plan.pilot_id}  arms={', '.join(arm.name for arm in arms)}")
    for arm in arms:
        archive = root / arm.name / "research_attempts.jsonl"
        model_calls = root / arm.name / "model_calls.jsonl"
        memory = root / arm.name / "memory.jsonl"
        config = load_config(Path(arm.config))
        ledger = ModelCallLedger(model_calls)
        budget = None if config.budget.unbounded else BudgetTracker(config.budget, ledger=ledger)
        orchestrator = Orchestrator.from_config(
            config,
            memory=ResearchMemory(memory),
            ledger=ledger,
            budget=budget,
            research_archive=ResearchArchive(archive),
        )
        print(f"\n[{arm.name}] config={arm.config} tasks={len(plan.tasks)}")
        for task in plan.tasks:
            try:
                result = orchestrator.run_research_cycle(args.objective, Path(task))
            except BudgetExceeded as exc:
                print(f"HALTED — budget ceiling breached ({exc.kind}): {exc}")
                print("Escalation required: stop this pilot before any budget change.")
                return 2
            metric = result.metric
            primary = (
                f"{metric.primary_name}={metric.primary:g} passed={metric.passed}"
                if metric is not None
                else "(not evaluated)"
            )
            print(
                f"  [{result.family:>9}] {result.task_id:<16} "
                f"{result.promotion_decision.value.upper():<9} {primary}"
            )
            for escalation in result.escalations:
                print(f"      ESCALATION: {escalation}")
        print(f"  archived attempts={archive} model_calls={model_calls}")
    return 0


def _cmd_pilot_report(args: argparse.Namespace) -> int:
    report = write_pilot_report(
        args.plan,
        args.output,
        provider_reconciliation=args.provider_reconciliation,
    )
    output = args.output or DEFAULT_PILOT_REPORT_PATH
    print(f"Wrote pilot report to {output}.")
    if "budget breach" in report.lower():
        print("HALTED — pilot budget breach detected; escalate before continuing.")
        return 2
    if "missing evidence" in report.lower():
        print("Pilot report has missing evidence; complete required arms before scale decisions.")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="siro",
        description="Bounded, auditable self-improving research organization testbed.",
    )
    parser.add_argument("--version", action="version", version=f"siro {__version__}")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command, tier, and governance implications without acting (Goal 21). "
        "Makes no state change, spends nothing, and writes no ledger row.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text, where supported "
        "(the read-only summaries and --dry-run) (Goal 21).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run-task", help="Run the per-task improvement loop (Goal 02).")
    p_run.add_argument("task_dir", type=Path, help="Path to a task directory.")
    p_run.add_argument(
        "-n", "--generations", type=int, default=5, help="Number of generations (default: 5)."
    )
    p_run.add_argument(
        "--archive",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Attempts archive path (default: runs/attempts.jsonl).",
    )
    p_run.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_run.add_argument(
        "--memory",
        type=Path,
        default=Path("runs/memory.jsonl"),
        help="Research-memory path (default: runs/memory.jsonl).",
    )
    p_run.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Tier/provider config (default: {DEFAULT_CONFIG_PATH}). Selecting tier is "
        "config-only — no code change.",
    )
    p_run.set_defaults(func=_cmd_run_task)

    p_train = sub.add_parser(
        "run-training", help="Run the tiny-training improvement loop (Goal 06)."
    )
    p_train.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=Path("tasks/training/task_001"),
        help="Path to a training task directory (default: tasks/training/task_001).",
    )
    p_train.add_argument(
        "-n", "--generations", type=int, default=5, help="Number of generations (default: 5)."
    )
    p_train.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_BUDGET_SECONDS,
        help=f"Fixed wall-clock budget per candidate, seconds (default: {DEFAULT_BUDGET_SECONDS:g}).",
    )
    p_train.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_TRAINING_ATTEMPTS_PATH,
        help="Training-attempts archive path (default: runs/training_attempts.jsonl).",
    )
    p_train.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_train.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Tier/provider config (default: {DEFAULT_CONFIG_PATH}).",
    )
    p_train.set_defaults(func=_cmd_run_training)

    p_org = sub.add_parser("run-org", help="Run one full frontier-org research cycle (Goal 08).")
    p_org.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=Path("tasks/code_improver/task_001"),
        help="Path to a task directory (default: tasks/code_improver/task_001).",
    )
    p_org.add_argument(
        "--objective",
        default="Improve the task implementation against its objective metric.",
        help="The human research objective the organization works toward.",
    )
    p_org.add_argument(
        "--config",
        type=Path,
        default=Path("config/tier1.frontier.yaml"),
        help="Tier/provider config (default: config/tier1.frontier.yaml). "
        "Use config/tier0.local.yaml to run the same org fully local — config-only.",
    )
    p_org.add_argument(
        "--archive",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Attempts archive path (default: runs/attempts.jsonl).",
    )
    p_org.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_org.add_argument(
        "--memory",
        type=Path,
        default=Path("runs/memory.jsonl"),
        help="Research-memory path (default: runs/memory.jsonl).",
    )
    p_org.set_defaults(func=_cmd_run_org)

    p_research = sub.add_parser(
        "run-research",
        help="Run the full org on research-shaped task(s) (Goal 09).",
    )
    p_research.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=None,
        help="A research task dir. Omit to run one cycle on every task in the configured pack.",
    )
    p_research.add_argument(
        "--objective",
        default="Improve the task against its objective metric.",
        help="The human research objective the organization works toward.",
    )
    p_research.add_argument(
        "--config",
        type=Path,
        default=Path("config/tier1.frontier.yaml"),
        help="Tier/provider config (default: config/tier1.frontier.yaml). "
        "Use config/tier0.local.yaml to run the same org fully local — config-only.",
    )
    p_research.add_argument(
        "--tasks-root",
        type=Path,
        default=None,
        help="Root to discover research tasks (default: the configured pack's tasks/ directory).",
    )
    p_research.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_RESEARCH_ATTEMPTS_PATH,
        help=f"Research-attempts archive (default: {DEFAULT_RESEARCH_ATTEMPTS_PATH}).",
    )
    p_research.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_research.add_argument(
        "--memory",
        type=Path,
        default=Path("runs/memory.jsonl"),
        help="Research-memory path (default: runs/memory.jsonl).",
    )
    p_research.set_defaults(func=_cmd_run_research)

    p_sumr = sub.add_parser(
        "summarize-research",
        help="Per-family summary of the research suite (Goal 09).",
    )
    p_sumr.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_RESEARCH_ATTEMPTS_PATH,
        help=f"Research-attempts archive (default: {DEFAULT_RESEARCH_ATTEMPTS_PATH}).",
    )
    p_sumr.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger, for per-family spend (default: runs/model_calls.jsonl).",
    )
    p_sumr.add_argument(
        "--store",
        type=Path,
        default=None,
        help="Read research attempts + spend from a SQLite store instead of JSONL (Goal 16).",
    )
    p_sumr.set_defaults(func=_cmd_summarize_research)

    # --- governance (Tier 2, Goal 10) --------------------------------------
    action_choices = [a.value for a in GovernedAction]
    scope_choices = [s.value for s in ApprovalScope]

    p_req = sub.add_parser(
        "request-approval",
        help="Record a pending governance request for a governed action (Goal 10).",
    )
    p_req.add_argument("action", choices=action_choices, help="The governed action kind.")
    p_req.add_argument("--target", default="", help="What the action applies to.")
    p_req.add_argument("--actor", default="", help="Who/what raised it (an agent or operator).")
    p_req.add_argument("--rationale", default="", help="Why it is requested.")
    p_req.add_argument("--risk", default="medium", help="Risk classification for the packet.")
    p_req.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Evaluator/safety evidence attachment or link; repeatable.",
    )
    p_req.add_argument("--rollback-plan", default="", help="Rollback plan for the governed action.")
    p_req.add_argument(
        "--payload",
        default="",
        help="JSON describing the exact change (binds the approval to it via content hash).",
    )
    p_req.add_argument("--scope", choices=scope_choices, default=ApprovalScope.ONCE.value)
    p_req.add_argument("--expires-in", type=float, default=None, help="Expiry in seconds.")
    p_req.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_req.set_defaults(func=_cmd_request_approval)

    p_list = sub.add_parser("list-approvals", help="List governance requests + status (Goal 10).")
    p_list.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_list.add_argument(
        "--status",
        default=None,
        choices=["pending", "granted", "denied", "expired", "revoked"],
        help="Only show requests in this resolved status.",
    )
    p_list.set_defaults(func=_cmd_list_approvals)

    p_appr = sub.add_parser("approve", help="Approve a pending governance request (human-only).")
    p_appr.add_argument("request_id", help="The request id to approve.")
    p_appr.add_argument("--by", required=True, help="Human approver id (required).")
    p_appr.add_argument(
        "--signature", default="", help="External signature over the request proof."
    )
    p_appr.add_argument(
        "--signing-key",
        default=None,
        help="Local development signing key used to create an HMAC proof; never stored.",
    )
    p_appr.add_argument("--expires-in", type=float, default=None, help="Expiry in seconds.")
    p_appr.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_appr.add_argument(
        "--config", type=Path, default=None, help="Tier config with policies/operators."
    )
    p_appr.set_defaults(func=_cmd_approve)

    p_deny = sub.add_parser("deny", help="Deny a pending governance request (human-only).")
    p_deny.add_argument("request_id", help="The request id to deny.")
    p_deny.add_argument("--by", required=True, help="Human id (required).")
    p_deny.add_argument("--reason", default="", help="Why it was denied.")
    p_deny.add_argument("--signature", default="", help="External signature over the denial proof.")
    p_deny.add_argument(
        "--signing-key",
        default=None,
        help="Local development signing key used to create an HMAC proof; never stored.",
    )
    p_deny.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_deny.add_argument(
        "--config", type=Path, default=None, help="Tier config with policies/operators."
    )
    p_deny.set_defaults(func=_cmd_deny)

    p_rev = sub.add_parser("revoke", help="Revoke a granted governance decision (human-only).")
    p_rev.add_argument("decision_id", help="The decision id to revoke.")
    p_rev.add_argument("--by", required=True, help="Human id (required).")
    p_rev.add_argument("--reason", default="", help="Why it was revoked.")
    p_rev.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_rev.set_defaults(func=_cmd_revoke)

    p_op_create = sub.add_parser("create-operator", help="Create a local governance operator.")
    p_op_create.add_argument("operator_id")
    p_op_create.add_argument("--display-name", required=True)
    p_op_create.add_argument(
        "--role",
        choices=[r.value for r in OperatorRole],
        required=True,
        help="Governance role for this operator.",
    )
    p_op_create.add_argument("--auth-method", default="local")
    p_op_create.add_argument("--operators", type=Path, default=DEFAULT_OPERATORS_PATH)
    p_op_create.set_defaults(func=_cmd_create_operator)

    p_op_list = sub.add_parser("list-operators", help="List local governance operators.")
    p_op_list.add_argument("--operators", type=Path, default=DEFAULT_OPERATORS_PATH)
    p_op_list.set_defaults(func=_cmd_list_operators)

    p_op_revoke = sub.add_parser("revoke-operator", help="Revoke a local governance operator.")
    p_op_revoke.add_argument("operator_id")
    p_op_revoke.add_argument("--operators", type=Path, default=DEFAULT_OPERATORS_PATH)
    p_op_revoke.set_defaults(func=_cmd_revoke_operator)

    p_gov_verify = sub.add_parser(
        "verify-governance", help="Verify approval ledger identity/policy proofs."
    )
    p_gov_verify.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_gov_verify.add_argument(
        "--config", type=Path, default=None, help="Tier config with policies/operators."
    )
    p_gov_verify.set_defaults(func=_cmd_verify_governance)

    p_packet = sub.add_parser(
        "export-governance-packet", help="Export a governance packet as JSON."
    )
    p_packet.add_argument("request_id")
    p_packet.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_packet.add_argument(
        "--config", type=Path, default=None, help="Tier config with policies/operators."
    )
    p_packet.set_defaults(func=_cmd_export_governance_packet)

    # --- governed external experiments (Tier 2, Goal 26) -------------------
    p_ext_propose = sub.add_parser(
        "propose-external-experiment",
        help="Record a typed EXTERNAL_EXPERIMENT request for a candidate (Goal 26).",
    )
    p_ext_propose.add_argument("task_dir", type=Path, help="The Regime-C research task dir.")
    p_ext_propose.add_argument(
        "--candidate", type=Path, default=None, help="Candidate file (defaults to the baseline)."
    )
    p_ext_propose.add_argument("--actor", default="", help="Who/what raised it (an agent or operator).")
    p_ext_propose.add_argument("--rationale", default="", help="Why it is worth its cost.")
    p_ext_propose.add_argument("--rollback-plan", default="", help="Rollback plan for the action.")
    p_ext_propose.add_argument("--evidence", action="append", default=[], help="Evidence link; repeatable.")
    p_ext_propose.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_ext_propose.add_argument("--config", type=Path, default=None)
    p_ext_propose.set_defaults(func=_cmd_propose_external_experiment)

    p_ext_list = sub.add_parser(
        "list-external-experiments", help="List external-experiment requests + status (Goal 26)."
    )
    p_ext_list.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_ext_list.add_argument("--results", type=Path, default=DEFAULT_EXTERNAL_RESULTS_PATH)
    p_ext_list.add_argument(
        "--status",
        default=None,
        choices=["pending", "granted", "denied", "expired", "revoked"],
        help="Only show requests in this resolved status.",
    )
    p_ext_list.add_argument("--config", type=Path, default=None)
    p_ext_list.set_defaults(func=_cmd_list_external_experiments)

    p_ext_ingest = sub.add_parser(
        "ingest-external-result",
        help="Attach a signed external result to a live approval (human-only).",
    )
    p_ext_ingest.add_argument("request_id", help="The approved request to attach a result to.")
    p_ext_ingest.add_argument("--operator", required=True, help="Human operator id (required).")
    p_ext_ingest.add_argument(
        "--status",
        choices=[s.value for s in ExternalResultStatus if s is not ExternalResultStatus.REJECTED],
        default=ExternalResultStatus.OK.value,
        help="Result class: ok / null / failed (null and failed are first-class negatives).",
    )
    p_ext_ingest.add_argument("--primary", type=float, default=0.0, help="Measured primary value.")
    p_ext_ingest.add_argument(
        "--failed", action="store_true", help="Mark the candidate as not passing the precondition."
    )
    p_ext_ingest.add_argument("--secondary", default="", help="JSON object of secondary metrics.")
    p_ext_ingest.add_argument("--provenance", default="", help="Instrument id / notebook ref / run id.")
    p_ext_ingest.add_argument("--reason", default="", help="Reason (required for null/failed results).")
    p_ext_ingest.add_argument("--signature", default="", help="External signature over the result proof.")
    p_ext_ingest.add_argument(
        "--signing-key",
        default=None,
        help="Local development signing key used to create an HMAC proof; never stored.",
    )
    p_ext_ingest.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_ext_ingest.add_argument("--results", type=Path, default=DEFAULT_EXTERNAL_RESULTS_PATH)
    p_ext_ingest.add_argument("--config", type=Path, default=None)
    p_ext_ingest.set_defaults(func=_cmd_ingest_external_result)

    p_ext_audit = sub.add_parser(
        "external-audit", help="Show the external-experiment audit trail as JSON (Goal 26)."
    )
    p_ext_audit.add_argument("request_id", nargs="?", default=None, help="Limit to one request.")
    p_ext_audit.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_ext_audit.add_argument("--results", type=Path, default=DEFAULT_EXTERNAL_RESULTS_PATH)
    p_ext_audit.add_argument("--config", type=Path, default=None)
    p_ext_audit.set_defaults(func=_cmd_external_audit)

    # --- governed compute scale-up (Tier 2, Goal 11) -----------------------
    p_scaled = sub.add_parser(
        "run-scaled",
        help="Run a research eval under a governed compute budget (Goal 11).",
    )
    p_scaled.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=Path("packs/ml/tasks/training/tiny_mlp"),
        help="Research task dir (default: packs/ml/tasks/training/tiny_mlp).",
    )
    p_scaled.add_argument(
        "--compute-tier", type=int, default=0, help="Compute tier (0 = free; higher = governed)."
    )
    p_scaled.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help="Candidate edit-surface file (default: the task baseline).",
    )
    p_scaled.add_argument("--experiment-id", default=None, help="Lineage key (default: task id).")
    p_scaled.add_argument("--actor", default="operator", help="Who requested the scale-up.")
    p_scaled.add_argument("--rationale", default="", help="Why the larger budget is needed.")
    p_scaled.add_argument(
        "--config",
        type=Path,
        default=Path("config/tier2.governed.yaml"),
        help="Tier/provider config (default: config/tier2.governed.yaml).",
    )
    p_scaled.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_RESEARCH_ATTEMPTS_PATH,
        help=f"Research-attempts archive (default: {DEFAULT_RESEARCH_ATTEMPTS_PATH}).",
    )
    p_scaled.add_argument(
        "--checkpoints",
        type=Path,
        default=DEFAULT_CHECKPOINT_DIR,
        help=f"Checkpoint directory (default: {DEFAULT_CHECKPOINT_DIR}).",
    )
    p_scaled.add_argument(
        "--backend",
        default=None,
        help="Isolation backend (local | linux_guarded; default: from config's compute block).",
    )
    p_scaled.set_defaults(func=_cmd_run_scaled)

    p_backends = sub.add_parser(
        "sandbox-backends",
        help="List execution-plane resource-isolation backends and availability (Goal 15).",
    )
    p_backends.set_defaults(func=_cmd_sandbox_backends)

    # --- governed model-training (Tier 2, Goal 12) -------------------------
    p_train_model = sub.add_parser(
        "train-model",
        help="Run a governed weight-update experiment (Goal 12).",
    )
    p_train_model.add_argument("experiment_id", help="Experiment / lineage id.")
    p_train_model.add_argument("--learning-rate", type=float, default=0.1)
    p_train_model.add_argument("--epochs", type=int, default=300)
    p_train_model.add_argument("--compute-tier", type=int, default=0)
    p_train_model.add_argument(
        "--open-incidents",
        type=int,
        default=0,
        help="Open safety incidents (>0 fails the stability precondition).",
    )
    p_train_model.add_argument("--actor", default="operator")
    p_train_model.add_argument("--rationale", default="")
    p_train_model.add_argument("--config", type=Path, default=Path("config/tier2.governed.yaml"))
    p_train_model.add_argument("--archive", type=Path, default=DEFAULT_MODEL_ARTIFACTS_PATH)
    p_train_model.add_argument("--store", type=Path, default=DEFAULT_ARTIFACT_STORE_DIR)
    p_train_model.set_defaults(func=_cmd_train_model)

    p_deploy = sub.add_parser(
        "deploy-model",
        help="Bind a trained artifact to a role — approval + cross-model review (Goal 12).",
    )
    p_deploy.add_argument("artifact_id", help="The trained artifact id to deploy.")
    p_deploy.add_argument("role", help="The agent role to bind it to.")
    p_deploy.add_argument(
        "--implementation-provider",
        required=True,
        help="The role's current implementation provider (the reviewer must differ).",
    )
    p_deploy.add_argument(
        "--reviewer-provider",
        required=True,
        help="The cross-model reviewer's provider (must differ from implementation).",
    )
    p_deploy.add_argument("--actor", default="operator")
    p_deploy.add_argument("--config", type=Path, default=Path("config/tier2.governed.yaml"))
    p_deploy.add_argument("--store", type=Path, default=DEFAULT_ARTIFACT_STORE_DIR)
    p_deploy.add_argument("--registry", type=Path, default=DEFAULT_MODEL_REGISTRY_PATH)
    p_deploy.set_defaults(func=_cmd_deploy_model)

    p_docs = sub.add_parser(
        "check-docs",
        help="Check docs/README/goal manifest consistency and docs privacy (Goal 13).",
    )
    p_docs.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root to check (default: current directory).",
    )
    p_docs.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=(
            f"Goal manifest path, relative to --root by default (default: {DEFAULT_MANIFEST_PATH})."
        ),
    )
    p_docs.set_defaults(func=_cmd_check_docs)

    p_pricing = sub.add_parser(
        "pricing-audit",
        help="Audit configured model pricing, review freshness, and budget ceilings (Goal 14).",
    )
    p_pricing.add_argument(
        "--config",
        type=Path,
        default=Path("config/tier1.frontier.yaml"),
        help="Tier/provider config to audit (default: config/tier1.frontier.yaml).",
    )
    p_pricing.add_argument(
        "--stale-days",
        type=int,
        default=90,
        help="Review age threshold for stale pricing warnings (default: 90).",
    )
    p_pricing.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero when any configured provider has missing or stale pricing.",
    )
    p_pricing.set_defaults(func=_cmd_pricing_audit)

    p_provider_report = sub.add_parser(
        "provider-report",
        help="Summarize provider spend, latency, retries, and errors (Goal 18).",
    )
    p_provider_report.add_argument(
        "--model-calls",
        type=Path,
        default=Path("runs/model_calls.jsonl"),
        help="Model-call audit ledger path (default: runs/model_calls.jsonl).",
    )
    p_provider_report.add_argument(
        "--research-attempts",
        type=Path,
        default=DEFAULT_RESEARCH_ATTEMPTS_PATH,
        help=f"Research-attempts archive for cost-per-promotion attribution "
        f"(default: {DEFAULT_RESEARCH_ATTEMPTS_PATH}).",
    )
    p_provider_report.set_defaults(func=_cmd_provider_report)

    p_pilot_init = sub.add_parser(
        "pilot-init",
        help="Write the fixed bounded operational pilot plan and command transcript (Goal 20).",
    )
    p_pilot_init.add_argument(
        "--plan",
        type=Path,
        default=DEFAULT_PILOT_PLAN_PATH,
        help=f"Pilot plan path (default: {DEFAULT_PILOT_PLAN_PATH}).",
    )
    p_pilot_init.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PILOT_ROOT,
        help=f"Pilot root directory (default: {DEFAULT_PILOT_ROOT}).",
    )
    p_pilot_init.set_defaults(func=_cmd_pilot_init)

    p_pilot_run = sub.add_parser(
        "pilot-run",
        help="Run the fixed operational pilot tasks into per-arm archives (Goal 20).",
    )
    p_pilot_run.add_argument(
        "--plan",
        type=Path,
        default=DEFAULT_PILOT_PLAN_PATH,
        help=f"Pilot plan path (default: {DEFAULT_PILOT_PLAN_PATH}).",
    )
    p_pilot_run.add_argument(
        "--arm",
        default="",
        help="Run only one named arm (for example tier0_local or tier1_cheap_frontier).",
    )
    p_pilot_run.add_argument(
        "--include-conditional",
        action="store_true",
        help="Also run conditional arms such as the strong-frontier follow-up.",
    )
    p_pilot_run.add_argument(
        "--objective",
        default="Improve the task against its objective metric.",
        help="Pilot objective passed to every research cycle.",
    )
    p_pilot_run.set_defaults(func=_cmd_pilot_run)

    p_pilot_report = sub.add_parser(
        "pilot-report",
        help="Render the bounded operational pilot report from archived ledgers (Goal 20).",
    )
    p_pilot_report.add_argument(
        "--plan",
        type=Path,
        default=DEFAULT_PILOT_PLAN_PATH,
        help=f"Pilot plan path (default: {DEFAULT_PILOT_PLAN_PATH}).",
    )
    p_pilot_report.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PILOT_REPORT_PATH,
        help=f"Report output path (default: {DEFAULT_PILOT_REPORT_PATH}).",
    )
    p_pilot_report.add_argument(
        "--provider-reconciliation",
        default="",
        help="Optional provider-dashboard reconciliation note or URL.",
    )
    p_pilot_report.set_defaults(func=_cmd_pilot_report)

    p_sum = sub.add_parser("summarize-runs", help="Summarize an attempts archive.")
    p_sum.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Path to attempts.jsonl (default: runs/attempts.jsonl).",
    )
    p_sum.add_argument(
        "--store",
        type=Path,
        default=None,
        help="Read attempts from a SQLite store instead of the JSONL path (Goal 16).",
    )
    p_sum.set_defaults(func=_cmd_summarize_runs)

    # --- durable storage (Goal 16) -----------------------------------------
    p_smig = sub.add_parser(
        "storage-migrate", help="Create/migrate the SQLite research store schema (Goal 16)."
    )
    p_smig.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help=f"SQLite store path (default: {DEFAULT_STORE_PATH}).",
    )
    p_smig.set_defaults(func=_cmd_storage_migrate)

    p_simp = sub.add_parser(
        "storage-import", help="Import existing JSONL archives into the SQLite store (Goal 16)."
    )
    p_simp.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help=f"SQLite store path (default: {DEFAULT_STORE_PATH}).",
    )
    p_simp.add_argument(
        "--from-dir",
        type=Path,
        default=None,
        help="Directory of <stream>.jsonl files (default: canonical runs/* paths).",
    )
    p_simp.set_defaults(func=_cmd_storage_import)

    p_sexp = sub.add_parser(
        "storage-export", help="Export the SQLite store back to JSONL files (Goal 16)."
    )
    p_sexp.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help=f"SQLite store path (default: {DEFAULT_STORE_PATH}).",
    )
    p_sexp.add_argument(
        "--to-dir",
        type=Path,
        default=Path("runs/export"),
        help="Output directory for <stream>.jsonl files (default: runs/export).",
    )
    p_sexp.set_defaults(func=_cmd_storage_export)

    p_sver = sub.add_parser(
        "storage-verify", help="Verify tamper-evident hash chains in the SQLite store (Goal 16)."
    )
    p_sver.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help=f"SQLite store path (default: {DEFAULT_STORE_PATH}).",
    )
    p_sver.add_argument(
        "--stream",
        default=None,
        help="Verify only this stream (default: all hash-chained streams).",
    )
    p_sver.set_defaults(func=_cmd_storage_verify)

    p_meta = sub.add_parser(
        "propose-meta-change", help="Propose a bounded process change (Goal 05)."
    )
    p_meta.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Path to attempts.jsonl (default: runs/attempts.jsonl).",
    )
    p_meta.add_argument(
        "--store",
        type=Path,
        default=Path("runs/meta_changes.jsonl"),
        help="Meta-change archive path, separate from attempts (default: runs/meta_changes.jsonl).",
    )
    p_meta.add_argument(
        "--benchmark",
        type=Path,
        nargs="+",
        default=[Path("tasks/code_improver/task_001")],
        help="Fixed benchmark task dir(s) for A/B validation.",
    )
    p_meta.add_argument(
        "-n",
        "--generations",
        type=int,
        default=3,
        help="Generations per benchmark run during A/B (default: 3).",
    )
    p_meta.add_argument(
        "--validate",
        action="store_true",
        help="Run A/B validation on the benchmark (needs the local model server).",
    )
    p_meta.set_defaults(func=_cmd_propose_meta_change)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    if getattr(args, "dry_run", False):
        return _dry_run(args, argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
