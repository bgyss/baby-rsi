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
- ``train-model`` / ``deploy-model`` — governed weight-update experiments (Goal 12);
                            both human-gated, deploy needs cross-model review.
- ``check-docs``          — verify README/goal manifest consistency and docs privacy
                            patterns (Goal 13).
- ``pricing-audit``       — report resolved provider pricing, review freshness, and
                            representative cycle costs (Goal 14).
- ``summarize-runs``      — reflect on the archive (real: counts + pass rate + best).
- ``summarize-research``  — per-family summary of the research suite (Goal 09).
- ``propose-meta-change`` — propose a process change (Goal 05).
- ``request-approval`` / ``list-approvals`` / ``approve`` / ``deny`` / ``revoke``
                          — the Tier 2 governance workflow (Goal 10); ``approve``/``deny``/
                            ``revoke`` are human-only — no agent can grant approval.

Uses only the standard library ``argparse`` to keep Tier 0 dependency-light.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from . import __version__
from .archive import JSONLArchive, ModelCallLedger
from .backends import available_backends
from .budget import BudgetExceeded, BudgetTracker
from .config import DEFAULT_CONFIG_PATH, load_config
from .controller import Controller, select_best
from .docs_check import DEFAULT_MANIFEST_PATH, check_docs
from .governance import (
    DEFAULT_APPROVALS_PATH,
    ApprovalLedger,
    GovernanceDenied,
    GovernanceGate,
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
from .providers import ModelClient
from .providers.pricing import Pricing
from .research import (
    DEFAULT_RESEARCH_ATTEMPTS_PATH,
    DEFAULT_RESEARCH_TASKS_DIR,
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
    GovernedAction,
    MetaChangeRecord,
    MetaRecommendation,
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
    label = f"tier {config.tier} (role {role} -> {getattr(model, 'provider', '?')}:" \
            f"{getattr(model, 'model', '?')})"
    return model, budget, label


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
        result = controller.run_training(
            args.task_dir, model=model, generations=args.generations
        )
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
    print(f"config: tier {config.tier} ({args.config}); cross-model review: "
          f"{'required' if orchestrator.require_cross_model else 'not required (all-local)'}")
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
    task discovered under ``tasks/research/`` — so "the Tier 1 org runs a full lifecycle on
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
        discovered = discover_research_tasks(args.tasks_root)
        if not discovered:
            print(f"No research tasks found under {args.tasks_root}.")
            return 0
        tasks = [Path(t.path) for t in discovered]

    print(f"config: tier {config.tier} ({args.config}); cross-model review: "
          f"{'required' if orchestrator.require_cross_model else 'not required (all-local)'}")
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
    attempts = ResearchArchive(args.path).read_all()
    if not attempts:
        print(f"No research attempts found in {args.path}.")
        return 0
    ledger_rows = ModelCallLedger(args.model_calls).read_all() if args.model_calls.exists() else []
    summaries = summarize_research(attempts, ledger_rows=ledger_rows)

    print(f"Research attempts: {len(attempts)}  (from {args.path})")
    for family, s in summaries.items():
        cycles = (
            f"{s.median_cycles_to_success:.1f}"
            if s.median_cycles_to_success is not None
            else "n/a"
        )
        print(f"\n[{family}]  tasks: {', '.join(s.task_ids)}")
        print(f"  attempts={s.attempts}  promoted={s.promoted}  pass_rate={s.pass_rate:.0%}")
        print(f"  median cycles to success: {cycles}")
        print(f"  safety-gate failures: {s.safety_gate_failures}")
        print(f"  spend: {s.tokens} tokens  ${s.cost_usd:.4f}")
        print(f"  strategy diversity: {s.strategy_diversity:.0%}  (distinct candidates / attempts)")
    return 0


def _cmd_summarize_runs(args: argparse.Namespace) -> int:
    archive = JSONLArchive(args.path)
    attempts = archive.read_all()
    if not attempts:
        print(f"No attempts found in {args.path}.")
        return 0

    status_counts = Counter(a.status.value for a in attempts)
    evaluated = [a for a in attempts if a.evaluation is not None]
    total_tests = sum(a.evaluation.passed_tests + a.evaluation.failed_tests for a in evaluated)
    passed_tests = sum(a.evaluation.passed_tests for a in evaluated)
    pass_rate = (passed_tests / total_tests) if total_tests else 0.0
    best = select_best(attempts)

    print(f"Attempts: {len(attempts)}  (from {args.path})")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    print(f"Test pass rate: {pass_rate:.1%}  ({passed_tests}/{total_tests})")
    if best is not None:
        print(f"Best score: {best.evaluation.score:.1f}  (attempt {best.attempt_id})")

    # Top recurring failure modes — reflect on negative results (Goal 03).
    failure_modes = Counter(
        failure_signature(a.reason) for a in attempts if failure_signature(a.reason) != "none"
    )
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
    if not requests:
        print(f"No approval requests in {args.ledger}.")
        return 0
    print(f"Approval requests in {args.ledger}:")
    for req in requests:
        status = gate.status_of(req.request_id)
        if args.status and status != args.status:
            continue
        print(
            f"  {req.request_id}  {status:<8} {req.action.value:<26} "
            f"target={req.target or '-'}  by={req.actor or '-'}"
        )
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    gate = GovernanceGate(ApprovalLedger(args.ledger))
    try:
        decision = gate.approve(args.request_id, by=args.by, expires_at=_expires_at(args.expires_in))
    except (KeyError, ValueError) as exc:
        print(f"cannot approve: {exc}")
        return 2
    print(f"APPROVED {decision.action.value} (request {decision.request_id}) by {decision.approver}")
    print(f"  decision {decision.decision_id}  scope={decision.scope.value}  "
          f"expires: {decision.expires_at or 'never'}")
    print(f"Recorded to {args.ledger}.")
    return 0


def _cmd_deny(args: argparse.Namespace) -> int:
    gate = GovernanceGate(ApprovalLedger(args.ledger))
    try:
        decision = gate.deny(args.request_id, by=args.by, reason=args.reason)
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
    print(f"config: tier {config.tier} ({args.config}); governance "
          f"{'on' if gate.enabled else 'off (compute tier > 0 needs Tier 2)'}; "
          f"backend={backend_name}{hard_note}")
    print(f"run-scaled: {task.task_id}  compute-tier={args.compute_tier}  experiment={experiment_id}")
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
        print("Use a hard-isolation backend (e.g. --backend linux_guarded on a supported host) "
              "or set compute.allow_local_dev for local development only.")
        return 2
    except ComputeAllocationError as exc:
        print(f"BLOCKED — {exc}")
        print("Pass the smaller compute tier first (promotion-before-budget), then retry.")
        return 2
    except GovernanceDenied as exc:
        print(f"BLOCKED — compute tier {args.compute_tier} needs human approval "
              f"(request {exc.request.request_id}).")
        print(f"Approve with: siro approve {exc.request.request_id} --by <human>")
        return 2
    except BudgetExceeded as exc:
        print(f"HALTED — compute ceiling breached ({exc.kind}): {exc} "
              f"(limit {exc.limit:g}, observed {exc.observed:g})")
        print("Escalation required: a human must approve a larger compute tier (governed).")
        return 2

    m = result.metric
    procs = "" if result.budget.max_processes is None else f" procs={result.budget.max_processes}"
    print(f"  budget: wall_clock={result.budget.wall_clock_seconds:g}s "
          f"memory={result.budget.memory_mb}MB{procs}  backend={result.backend}")
    print(f"  metric: {m.primary_name}={m.primary:g} passed={m.passed} peak_mem={result.peak_memory_mb:.0f}MB")
    print(f"  {result.attempt.status.value} — archived to {args.archive}; checkpoint in {args.checkpoints}")
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
    print(f"config: tier {config.tier} ({args.config}); governance "
          f"{'on' if gate.enabled else 'off (model-training is Tier 2)'}; "
          f"stability {'green' if stability.stable else 'RED ' + str(stability.failures)}")
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
        print(f"BLOCKED — weight-update experiment needs human approval "
              f"(request {exc.request.request_id}).")
        print(f"Approve with: siro approve {exc.request.request_id} --by <human>")
        return 2

    print(f"trained artifact {artifact.artifact_id}  passed={artifact.passed}  "
          f"val_loss={artifact.val_loss:g}")
    print(f"  lineage: base={artifact.base_model_hash} data={artifact.data_id}@{artifact.data_seed} "
          f"code={artifact.code_version}")
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
        print(f"BLOCKED — deploying to role {args.role!r} needs human approval "
              f"(request {exc.request.request_id}).")
        print(f"Approve with: siro approve {exc.request.request_id} --by <human>")
        return 2

    print(f"DEPLOYED artifact {deployment.artifact_id} -> role {deployment.role} "
          f"(approver {deployment.approver}, reviewer {deployment.reviewer_provider})")
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
    print("Representative cycle costs use input/output token counts: small=10k/2k, medium=100k/20k, heavy=1M/200k.")

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="siro",
        description="Bounded, auditable self-improving research organization testbed.",
    )
    parser.add_argument("--version", action="version", version=f"siro {__version__}")
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

    p_org = sub.add_parser(
        "run-org", help="Run one full frontier-org research cycle (Goal 08)."
    )
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
        help="A research task dir. Omit to run one cycle on every task under tasks/research/.",
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
        default=DEFAULT_RESEARCH_TASKS_DIR,
        help=f"Root to discover research tasks (default: {DEFAULT_RESEARCH_TASKS_DIR}).",
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
    p_appr.add_argument("--expires-in", type=float, default=None, help="Expiry in seconds.")
    p_appr.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_appr.set_defaults(func=_cmd_approve)

    p_deny = sub.add_parser("deny", help="Deny a pending governance request (human-only).")
    p_deny.add_argument("request_id", help="The request id to deny.")
    p_deny.add_argument("--by", required=True, help="Human id (required).")
    p_deny.add_argument("--reason", default="", help="Why it was denied.")
    p_deny.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_deny.set_defaults(func=_cmd_deny)

    p_rev = sub.add_parser("revoke", help="Revoke a granted governance decision (human-only).")
    p_rev.add_argument("decision_id", help="The decision id to revoke.")
    p_rev.add_argument("--by", required=True, help="Human id (required).")
    p_rev.add_argument("--reason", default="", help="Why it was revoked.")
    p_rev.add_argument("--ledger", type=Path, default=DEFAULT_APPROVALS_PATH)
    p_rev.set_defaults(func=_cmd_revoke)

    # --- governed compute scale-up (Tier 2, Goal 11) -----------------------
    p_scaled = sub.add_parser(
        "run-scaled",
        help="Run a research eval under a governed compute budget (Goal 11).",
    )
    p_scaled.add_argument(
        "task_dir",
        type=Path,
        nargs="?",
        default=Path("tasks/research/training/tiny_mlp"),
        help="Research task dir (default: tasks/research/training/tiny_mlp).",
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
    p_train_model.add_argument(
        "--config", type=Path, default=Path("config/tier2.governed.yaml")
    )
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
    p_deploy.add_argument(
        "--config", type=Path, default=Path("config/tier2.governed.yaml")
    )
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
            "Goal manifest path, relative to --root by default "
            f"(default: {DEFAULT_MANIFEST_PATH})."
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

    p_sum = sub.add_parser("summarize-runs", help="Summarize an attempts archive.")
    p_sum.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("runs/attempts.jsonl"),
        help="Path to attempts.jsonl (default: runs/attempts.jsonl).",
    )
    p_sum.set_defaults(func=_cmd_summarize_runs)

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
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
