"""Meta-research loop — the OUTER loop that improves the *process* (Goal 05).

This is the canonical outer loop of ``docs/13_self_improvement_loop.md``. Where the
inner loop (``controller``) improves *candidates* for a task, this loop improves *the
loop itself*: candidate-generation prompts, memory-retrieval strategy, and other
process knobs captured by :class:`~siro.schemas.ProcessConfig`. It reuses the same
lifecycle, gates, and memory as the inner loop; only the object under change differs.

It runs the same six-step cycle, bounded throughout:

    summarize experiment archive   (observe / reflect)
    → identify the bottleneck
    → propose a meta-change        (propose — bounded to the allowed kinds)
    → build an A/B validation plan
    → run on fixed benchmark tasks (validate — same task set, same generations)
    → compare against the current process
    → recommend promote / reject   (gate — aggregate-metric improvement)
    → record separately + rollback (record)

Bounds (``goal_05`` "Forbidden meta-changes" / ``docs/13`` "Bounds") are enforced two
ways: structurally, because :class:`ProcessConfig` cannot *represent* a safety/evaluator/
budget/network/permission change; and explicitly, via :func:`forbidden_meta_change`,
which flags any proposal that names such a surface so it is never validated or applied.
Durable application is human-gated: :func:`apply_meta_change` refuses unless a human has
set ``approved=True`` on a promote-recommended, in-bounds record.
"""

from __future__ import annotations

import statistics
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .archive import JSONLArchive, ModelCallLedger
from .controller import Controller, RunResult
from .memory import ResearchMemory, _candidate_summary, failure_signature
from .model_client import ModelClient
from .schemas import (
    ABResult,
    Attempt,
    AttemptStatus,
    GateDecision,
    MetaChange,
    MetaChangeKind,
    MetaChangeRecord,
    MetaMetrics,
    MetaRecommendation,
    ProcessConfig,
)

DEFAULT_META_CHANGES_PATH = Path("runs/meta_changes.jsonl")

#: A meta-change whose target/description mentions any of these surfaces is *forbidden*
#: without human approval (``goal_05`` "Forbidden meta-changes", ``docs/13`` "Bounds").
#: The check is deliberately broad: the outer loop may *propose* nothing that touches
#: these, and a constructed proposal that does is flagged and never auto-applied.
FORBIDDEN_SURFACES: tuple[str, ...] = (
    "safety gate",
    "safety",
    "evaluator",
    "scoring weight",
    "weaken",
    "disable test",
    "delete test",
    "weaken test",
    "logging",
    "audit ledger",
    "permission",
    "tool access",
    "edit surface",
    "budget",
    "token ceiling",
    "usd",
    "network",
    "egress",
    "allowlist",
    "package install",
    "pip install",
    "tier",
)

#: A factory returning a *fresh* model client per call, so the A/B arms are independent
#: yet identical (e.g. two ScriptedModelClients replaying the same canned responses).
ModelFactory = Callable[[], ModelClient]


def forbidden_meta_change(target: str, description: str) -> tuple[bool, str]:
    """Return ``(ok, reason)`` — whether a meta-change stays within bounds.

    ``ok`` is false when the proposal names a forbidden surface (safety gates, the
    evaluator, logging/audit, permissions, budgets, network, package install, tier).
    These require explicit human approval and stricter review; the autonomous loop may
    never apply them.
    """
    text = f"{target}\n{description}".lower()
    for surface in FORBIDDEN_SURFACES:
        if surface in text:
            return False, f"touches forbidden surface '{surface}'"
    return True, ""


# --------------------------------------------------------------------------- #
# Reflect + propose.
# --------------------------------------------------------------------------- #


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _archive_pass_rate(attempts: list[Attempt]) -> float:
    evaluated = [a for a in attempts if a.evaluation is not None]
    if not evaluated:
        return 0.0
    passing = sum(1 for a in evaluated if _attempt_passes(a))
    return passing / len(evaluated)


def propose_meta_change(
    archive: JSONLArchive, *, baseline: ProcessConfig | None = None
) -> MetaChange:
    """Reflect on the attempt archive and propose one bounded process change.

    The Tier 0 proposer is deterministic (no model required, matching the offline
    design): it identifies the dominant failure bottleneck and proposes a *memory
    retrieval-strategy* change — surface more prior lessons to the proposer — which is
    a reversible :class:`ProcessConfig` delta with a clear rollback plan. The proposal
    is checked against :func:`forbidden_meta_change`; an in-bounds retrieval change
    always passes, but the verdict is recorded regardless.
    """
    baseline = baseline or ProcessConfig()
    attempts = archive.read_all()
    pass_rate = _archive_pass_rate(attempts)
    failure_counts = Counter(
        failure_signature(a.reason)
        for a in attempts
        if failure_signature(a.reason) != "none"
    )
    top = failure_counts.most_common(1)
    bottleneck = top[0][0] if top else "exploration"

    new_limit = baseline.retrieval_limit + 3
    candidate_config = baseline.model_copy(update={"retrieval_limit": new_limit})
    target = "memory.retrieval_limit"
    description = (
        f"Increase memory retrieval_limit {baseline.retrieval_limit} → {new_limit} so the "
        "candidate-generation prompt surfaces more prior lessons to the proposer."
    )
    rationale = (
        f"Archive pass rate {pass_rate:.0%} over {len(attempts)} attempt(s); dominant "
        f"bottleneck is '{bottleneck}'. Surfacing more prior lessons may reduce repeated "
        f"'{bottleneck}' failures without touching the evaluator, gates, or budgets."
    )
    rollback_plan = (
        f"Revert ProcessConfig.retrieval_limit to {baseline.retrieval_limit}. The change "
        "is a single in-memory config delta; no prompt file, gate, evaluator, or budget "
        "was modified, so rollback is immediate and total."
    )
    ok, reason = forbidden_meta_change(target, description)
    return MetaChange(
        meta_change_id=_short_id(),
        kind=MetaChangeKind.RETRIEVAL_STRATEGY,
        target=target,
        description=description,
        rationale=rationale,
        baseline_config=baseline,
        candidate_config=candidate_config,
        rollback_plan=rollback_plan,
        bounds_ok=ok,
        forbidden_reason=reason,
    )


# --------------------------------------------------------------------------- #
# Aggregate metrics over benchmark runs.
# --------------------------------------------------------------------------- #


def _attempt_passes(attempt: Attempt) -> bool:
    """A candidate that reproducibly passes every test (a clean success)."""
    ev = attempt.evaluation
    return (
        ev is not None and ev.reproducible and ev.failed_tests == 0 and ev.passed_tests > 0
    )


def _is_invalid(attempt: Attempt) -> bool:
    """An *invalid* candidate: no evaluation, non-reproducible, or an outright error."""
    ev = attempt.evaluation
    if ev is None or not ev.reproducible:
        return True
    return attempt.status == AttemptStatus.ERROR


def _safety_failed(attempt: Attempt) -> bool:
    """True if the attempt's recorded gates include a non-passing *safety* gate."""
    if attempt.gates is None:
        return False
    return any(
        r.gate == "safety" and r.decision is not GateDecision.PASSED
        for r in attempt.gates.results
    )


def aggregate_metrics(runs: list[RunResult]) -> MetaMetrics:
    """Compute the ``goal_05`` process metrics across a set of benchmark runs.

    Each :class:`~siro.controller.RunResult` is one benchmark task's inner loop, whose
    ``attempts[0]`` is the seed (generation 0) and the rest are proposed generations.
    """
    attempts = [a for run in runs for a in run.attempts]
    n_attempts = len(attempts)
    evaluated = [a for a in attempts if a.evaluation is not None]
    pass_rate = (
        sum(1 for a in evaluated if _attempt_passes(a)) / len(evaluated)
        if evaluated
        else 0.0
    )
    invalid = sum(1 for a in attempts if _is_invalid(a))
    safety_failures = sum(1 for a in attempts if _safety_failed(a))

    gens_to_success: list[float] = []
    score_improvements: list[float] = []
    for run in runs:
        success_gen = next(
            (i for i, a in enumerate(run.attempts) if _attempt_passes(a)), None
        )
        # Never reaching success is penalized as one worse than the last generation.
        gens_to_success.append(
            float(success_gen) if success_gen is not None else float(len(run.attempts))
        )
        n_gens = max(len(run.attempts) - 1, 1)  # exclude the seed
        seed = run.attempts[0] if run.attempts else None
        seed_score = seed.evaluation.score if seed and seed.evaluation else 0.0
        best_score = run.best.evaluation.score if run.best and run.best.evaluation else seed_score
        score_improvements.append((best_score - seed_score) / n_gens)

    distinct = {_candidate_summary(a.candidate.code) for a in attempts}
    diversity = len(distinct) / n_attempts if n_attempts else 0.0

    return MetaMetrics(
        n_runs=len(runs),
        n_attempts=n_attempts,
        pass_rate=pass_rate,
        median_generations_to_success=(
            statistics.median(gens_to_success) if gens_to_success else 0.0
        ),
        invalid_candidates=invalid,
        safety_gate_failures=safety_failures,
        score_improvement_per_generation=(
            statistics.mean(score_improvements) if score_improvements else 0.0
        ),
        strategy_diversity=diversity,
    )


def _compare(baseline: MetaMetrics, candidate: MetaMetrics) -> tuple[bool, str, dict[str, float]]:
    """Decide whether ``candidate`` is an aggregate improvement over ``baseline``.

    Secondary metrics gate first (objective-evaluation-first): a regression in safety
    gate failures or invalid candidates blocks promotion outright. Then the primary
    metric (pass rate) must improve; ties break on fewer generations-to-success, then
    on faster score improvement per generation.
    """
    deltas = {
        "pass_rate": candidate.pass_rate - baseline.pass_rate,
        "median_generations_to_success": (
            candidate.median_generations_to_success - baseline.median_generations_to_success
        ),
        "invalid_candidates": float(candidate.invalid_candidates - baseline.invalid_candidates),
        "safety_gate_failures": float(
            candidate.safety_gate_failures - baseline.safety_gate_failures
        ),
        "score_improvement_per_generation": (
            candidate.score_improvement_per_generation
            - baseline.score_improvement_per_generation
        ),
        "strategy_diversity": candidate.strategy_diversity - baseline.strategy_diversity,
    }
    if candidate.safety_gate_failures > baseline.safety_gate_failures:
        return False, "safety gate failures regressed — reject", deltas
    if candidate.invalid_candidates > baseline.invalid_candidates:
        return False, "invalid-candidate count regressed — reject", deltas
    if candidate.pass_rate > baseline.pass_rate + 1e-9:
        return True, "pass rate improved on the benchmark", deltas
    if abs(candidate.pass_rate - baseline.pass_rate) <= 1e-9:
        if candidate.median_generations_to_success < baseline.median_generations_to_success:
            return True, "fewer generations to success at equal pass rate", deltas
        if (
            candidate.score_improvement_per_generation
            > baseline.score_improvement_per_generation + 1e-9
        ):
            return True, "faster score improvement at equal pass rate", deltas
    return False, "no aggregate improvement on the benchmark — reject", deltas


# --------------------------------------------------------------------------- #
# Separate store for meta-change records (kept apart from candidate attempts).
# --------------------------------------------------------------------------- #


def _read_lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        return iter([line for line in (raw.strip() for raw in fh) if line])


class MetaChangeStore:
    """Append-only JSONL store of :class:`MetaChangeRecord`s — *separate* from attempts.

    Keeping meta-changes in their own archive (``runs/meta_changes.jsonl``) is an
    acceptance criterion: a process change is never confused with an ordinary candidate
    attempt, and every proposal (promoted or rejected) stays auditable.
    """

    def __init__(self, path: str | Path = DEFAULT_META_CHANGES_PATH) -> None:
        self.path = Path(path)

    def append(self, record: MetaChangeRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")

    def read_all(self) -> list[MetaChangeRecord]:
        return [MetaChangeRecord.model_validate_json(line) for line in _read_lines(self.path)]

    def __len__(self) -> int:
        return sum(1 for _ in _read_lines(self.path))


# --------------------------------------------------------------------------- #
# The meta-researcher: propose → A/B validate → recommend → record.
# --------------------------------------------------------------------------- #


@dataclass
class MetaResearcher:
    """Drives the outer loop over a fixed benchmark task set.

    ``archive`` is the inner-loop attempt archive reflected on to propose a change;
    ``store`` is the separate meta-change archive recorded into. A/B validation runs the
    inner loop on ``benchmark_tasks`` in *throwaway* archives/memory so it never
    pollutes the real record — validation is not a real attempt.
    """

    archive: JSONLArchive
    store: MetaChangeStore
    benchmark_tasks: list[Path] = field(default_factory=list)
    generations: int = 3

    def propose(self, baseline: ProcessConfig | None = None) -> MetaChange:
        return propose_meta_change(self.archive, baseline=baseline)

    def _run_process(self, config: ProcessConfig, model_factory: ModelFactory) -> list[RunResult]:
        runs: list[RunResult] = []
        for task_dir in self.benchmark_tasks:
            with tempfile.TemporaryDirectory(prefix="siro-ab-") as td:
                controller = Controller(
                    archive=JSONLArchive(Path(td) / "attempts.jsonl"),
                    ledger=ModelCallLedger(Path(td) / "model_calls.jsonl"),
                    memory=ResearchMemory(path=None),  # ephemeral; A/B never touches real memory
                    process=config,
                )
                runs.append(
                    controller.run_task(
                        task_dir, model=model_factory(), generations=self.generations
                    )
                )
        return runs

    def validate(self, proposal: MetaChange, model_factory: ModelFactory) -> ABResult:
        """A/B the baseline vs candidate process on the *same* benchmark task set."""
        baseline_runs = self._run_process(proposal.baseline_config, model_factory)
        candidate_runs = self._run_process(proposal.candidate_config, model_factory)
        baseline_metrics = aggregate_metrics(baseline_runs)
        candidate_metrics = aggregate_metrics(candidate_runs)
        improved, notes, deltas = _compare(baseline_metrics, candidate_metrics)
        return ABResult(
            baseline=baseline_metrics,
            candidate=candidate_metrics,
            benchmark_tasks=[str(p) for p in self.benchmark_tasks],
            generations=self.generations,
            improved=improved,
            deltas=deltas,
            notes=notes,
        )

    def run(
        self,
        model_factory: ModelFactory,
        *,
        baseline: ProcessConfig | None = None,
    ) -> MetaChangeRecord:
        """Run the full outer cycle once and record the result (recommendation only).

        Returns a recorded :class:`MetaChangeRecord` with ``approved=False`` and
        ``applied=False``: the loop recommends, a human approves. An out-of-bounds
        proposal is recorded and rejected without ever running A/B.
        """
        proposal = self.propose(baseline)
        if not proposal.bounds_ok:
            record = MetaChangeRecord(
                record_id=_short_id(),
                proposal=proposal,
                ab_result=None,
                recommendation=MetaRecommendation.REJECT,
                reason=f"forbidden meta-change: {proposal.forbidden_reason}",
            )
            self.store.append(record)
            return record

        ab_result = self.validate(proposal, model_factory)
        recommendation = (
            MetaRecommendation.PROMOTE if ab_result.improved else MetaRecommendation.REJECT
        )
        record = MetaChangeRecord(
            record_id=_short_id(),
            proposal=proposal,
            ab_result=ab_result,
            recommendation=recommendation,
            reason=ab_result.notes,
        )
        self.store.append(record)
        return record


def apply_meta_change(record: MetaChangeRecord) -> ProcessConfig:
    """Return the new :class:`ProcessConfig` to adopt — only if human-approved.

    Durable process changes are human-gated (``goal_05`` acceptance criterion, ``docs/13``
    bounds). This refuses unless the record was recommended for promotion, stays within
    bounds, *and* a human set ``approved=True``. The autonomous loop can reach the first
    two conditions but never the third.
    """
    if not record.proposal.bounds_ok:
        raise PermissionError(
            "cannot apply an out-of-bounds meta-change: "
            f"{record.proposal.forbidden_reason}"
        )
    if record.recommendation is not MetaRecommendation.PROMOTE:
        raise PermissionError("cannot apply a meta-change that A/B validation did not promote")
    if not record.approved:
        raise PermissionError(
            "durable process changes require human approval (set record.approved=True)"
        )
    return record.proposal.candidate_config


__all__ = [
    "DEFAULT_META_CHANGES_PATH",
    "FORBIDDEN_SURFACES",
    "ModelFactory",
    "forbidden_meta_change",
    "propose_meta_change",
    "aggregate_metrics",
    "MetaChangeStore",
    "MetaResearcher",
    "apply_meta_change",
]
