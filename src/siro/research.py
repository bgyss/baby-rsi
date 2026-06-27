"""Research-shaped task suite + evaluation harness (Goal 09).

Goal 09 gives the Tier 1 organization *real work*: a suite of research-shaped tasks
(beyond single-function code repair) with objective, reproducible evaluators, so the
frontier agents are measured doing genuine research rather than templated mutation
(``docs/goal_prompts/goal_09_research_task_suite.md``). It is also the **fixed benchmark
the validate step of the self-improvement loop depends on** (``docs/13``): the held-fixed
A/B set both loops compare candidates and meta-changes against.

A research task lives in ``packs/<domain>/tasks/<family>/<task>/``::

    task.json   # machine metadata: family, edit surface, primary metric + direction
    brief.md    # objective, constraints, allowed edit surface, success metric (agent-visible)
    baseline/   # the starting code/config the org improves on (the edit surface + supports)
    eval.py     # the objective, reproducible evaluator — the *authority for promotion*
    hidden/     # optional held-out tests/data, never shown to agents (no-leakage)

The load-bearing invariants are enforced **structurally**, not by trust:

- ``eval.py`` is controller-owned and runs in the offline sandbox; a candidate cannot
  rewrite what scores it (the execution plane has no network, a scrubbed env, a hard
  timeout).
- The metric record ``eval.py`` returns is the authority for promotion — never a model's
  self-judgment. The *controller* decides promotion from it.
- Held-out data lives in ``hidden/`` and is handed to ``eval.py`` **outside** the
  candidate's working directory, via the ``SIRO_HIDDEN_PATH`` env var (see
  :meth:`Sandbox.run_research`); it never enters a model prompt, there is no relative file
  for the candidate to ``open``, and reading the env var or an absolute path from candidate
  code trips the static safety gate — so a metric gain cannot come from hidden-data leakage
  (enforced, not assumed).
- Promotion requires a *reproducible* improvement over the baseline; a lucky or noisy win
  cannot be promoted.

Expanding the benchmark scope or the compute/token budget is a human-gated change (the
bound in ``docs/13``): the suite here is the fixed set, and the budgets live in the
controller/config, never in a candidate.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .memory import failure_signature
from .packs import DEFAULT_PACK_ID, DomainPack, EvaluatorAdapter, EvaluatorRegime, load_pack
from .sandbox import Sandbox
from .schemas import (
    AttemptStatus,
    Candidate,
    GateDecision,
    GateResult,
    MemoryEntry,
    MetricRecord,
    ResearchAttempt,
    StatisticalEvidence,
)

DEFAULT_RESEARCH_ATTEMPTS_PATH = Path("runs/research_attempts.jsonl")
DEFAULT_RESEARCH_TASKS_DIR = Path("packs/ml/tasks")

#: A candidate must beat the incumbent's primary metric by at least this (oriented so
#: larger is better) to count as an improvement — a guard against promoting on noise.
MIN_PRIMARY_IMPROVEMENT = 1e-9
#: Reruns of a promotion contender must agree on the primary metric within this tolerance.
REPRO_TOLERANCE = 1e-9
#: Default wall-clock budget for one evaluation, seconds (a *fixed* harness parameter).
DEFAULT_RESEARCH_BUDGET_SECONDS = 15.0

#: Fixed replicate seeds for the ``statistical`` regime (Goal 24). These are *harness*
#: parameters set by the controller/config, never candidate-supplied: a candidate can neither
#: set nor read them (reading ``SIRO_EVAL_SEED`` from candidate code trips the safety gate).
DEFAULT_STATISTICAL_SEEDS: tuple[int, ...] = (11, 23, 47, 89, 101, 211, 307)
#: Confidence level the primary-metric delta interval must clear to promote a noisy candidate.
DEFAULT_STATISTICAL_CONFIDENCE = 0.95


# --------------------------------------------------------------------------- #
# Task loading.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ResearchTask:
    """A research task loaded from disk.

    The evaluator (``eval_path``) and held-out data (``hidden_dir``) are *controller-owned*
    and are never placed in a model prompt — only ``brief`` and the baseline edit surface
    are agent-visible. ``primary_name``/``higher_is_better`` describe the metric direction
    so the same promotion logic works for higher-better (accuracy) and lower-better
    (validation loss, executed-line count) tasks.
    """

    task_id: str
    family: str
    path: str
    objective: str
    brief: str
    edit_surface: str
    surface_code: str
    support_files: dict[str, str]
    eval_path: Path
    hidden_dir: Path | None
    primary_name: str
    higher_is_better: bool
    budget_seconds: float
    pack_id: str = DEFAULT_PACK_ID
    pack_version: str = ""
    evaluator_regime: EvaluatorRegime = EvaluatorRegime.SEEDED_DETERMINISTIC
    evaluator_adapter: EvaluatorAdapter | None = None
    #: Direction (higher-is-better) per named secondary metric, for the statistical regime's
    #: secondary-regression check. Empty for deterministic packs (secondaries stay
    #: informational); a candidate cannot set it — it is read from the controller-owned
    #: ``task.json``.
    secondary_directions: dict[str, bool] = field(default_factory=dict)
    #: Controller-owned external-experiment metadata for the ``external-oracle`` regime
    #: (Goal 26): action class, proposal text, cost/risk envelope. Read from ``task.json``;
    #: a candidate cannot set it. Empty for in-silico (Regime A/B) tasks.
    external: dict = field(default_factory=dict)

    @property
    def allowed_surface(self) -> str:
        """The single path a candidate may edit (the agents' allow-listed edit surface)."""
        return str(Path(self.path) / "baseline" / self.edit_surface)


def _find_pack_for_task(path: Path) -> DomainPack:
    parts = path.resolve().parts
    if "packs" in parts:
        idx = len(parts) - 1 - parts[::-1].index("packs")
        if idx + 1 < len(parts):
            return load_pack(parts[idx + 1])
    return load_pack(DEFAULT_PACK_ID)


def load_research_task(task_dir: str | Path, *, pack: DomainPack | None = None) -> ResearchTask:
    """Load a research task directory (``task.json`` + ``brief.md`` + ``baseline/`` + ``eval.py``)."""
    path = Path(task_dir)
    pack = pack or _find_pack_for_task(path)
    meta_path = path / "task.json"
    brief_path = path / "brief.md"
    eval_path = path / "eval.py"
    baseline_dir = path / "baseline"
    if not meta_path.exists() or not brief_path.exists() or not eval_path.exists() or not baseline_dir.is_dir():
        raise FileNotFoundError(
            f"Research task dir {path} must contain task.json, brief.md, eval.py, and baseline/."
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    edit_surface = meta["edit_surface"]
    surface_path = baseline_dir / edit_surface
    if not surface_path.exists():
        raise FileNotFoundError(f"Edit surface {surface_path} declared in task.json is missing.")
    support_files = {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(baseline_dir.iterdir())
        if p.is_file() and p.name != edit_surface
    }
    hidden_dir = path / "hidden"
    has_hidden = hidden_dir.is_dir() and any(hidden_dir.iterdir())
    return ResearchTask(
        task_id=path.name,
        family=meta.get("family", path.parent.name),
        path=str(path),
        objective=meta.get("objective", ""),
        brief=brief_path.read_text(encoding="utf-8"),
        edit_surface=edit_surface,
        surface_code=surface_path.read_text(encoding="utf-8"),
        support_files=support_files,
        eval_path=eval_path,
        hidden_dir=hidden_dir if has_hidden else None,
        primary_name=meta.get("primary_metric", "primary"),
        higher_is_better=bool(meta.get("higher_is_better", True)),
        budget_seconds=float(meta.get("budget_seconds", DEFAULT_RESEARCH_BUDGET_SECONDS)),
        pack_id=pack.id,
        pack_version=pack.version,
        evaluator_regime=pack.regime,
        evaluator_adapter=pack.adapter,
        secondary_directions={
            str(k): bool(v) for k, v in (meta.get("secondary_directions") or {}).items()
        },
        external=dict(meta.get("external") or {}),
    )


def discover_research_tasks(
    root: str | Path | None = DEFAULT_RESEARCH_TASKS_DIR, *, pack_id: str | None = None
) -> list[ResearchTask]:
    """Load every research task under ``root`` (a directory with a ``task.json``)."""
    pack = load_pack(pack_id or DEFAULT_PACK_ID)
    base = pack.tasks_dir if root is None else Path(root)
    if not base.is_dir():
        return []
    tasks: list[ResearchTask] = []
    for meta in sorted(base.rglob("task.json")):
        tasks.append(load_research_task(meta.parent, pack=pack))
    return tasks


def hidden_payload(task: ResearchTask) -> str | None:
    """Serialize the held-out data for ``eval.py`` (read by the controller, not the model).

    Merges every ``*.json`` file under ``hidden/`` into one object keyed by file stem (so
    ``hidden/benchmark.json`` becomes ``{"benchmark": ...}``). The sandbox writes this
    outside the candidate's working directory and points ``eval.py`` at it via
    ``SIRO_HIDDEN_PATH``. This is the only path the held-out data takes; it never reaches a
    prompt nor the candidate's cwd.
    """
    if task.hidden_dir is None:
        return None
    merged: dict[str, object] = {}
    for p in sorted(task.hidden_dir.glob("*.json")):
        merged[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    if not merged:
        return None
    return json.dumps(merged)


# --------------------------------------------------------------------------- #
# Evaluation harness — eval.py is the authority for promotion.
# --------------------------------------------------------------------------- #


def _run_eval_py(
    task: ResearchTask, candidate_code: str, sandbox: Sandbox, *, seed: int | None = None
) -> MetricRecord:
    """Run the task's fixed ``eval.py`` against ``candidate_code`` and return its metric.

    The candidate supplies only its edited edit surface; ``eval.py`` (controller-owned) and
    the held-out data are copied in by the sandbox. The returned :class:`MetricRecord` is
    the objective authority the controller promotes on. ``seed`` is forwarded to ``eval.py``
    via ``SIRO_EVAL_SEED`` for the statistical regime's replicate runs (Goal 24); deterministic
    evaluators ignore it.
    """
    files = {task.edit_surface: candidate_code, **task.support_files}
    run = sandbox.run_research(
        task.eval_path,
        files,
        hidden_payload=hidden_payload(task),
        budget_seconds=task.budget_seconds,
        seed=seed,
    )
    if not run.ran:
        return MetricRecord(
            primary_name=task.primary_name,
            higher_is_better=task.higher_is_better,
            passed=False,
            reproducible=False,
            error=run.error or "eval.py produced no metric record",
        )
    m = run.metrics
    secondary = {k: float(v) for k, v in (m.get("secondary") or {}).items()}
    return MetricRecord(
        primary_name=task.primary_name,
        primary=float(m["primary"]),
        higher_is_better=task.higher_is_better,
        passed=bool(m.get("passed", False)),
        secondary=secondary,
        reproducible=True,
        notes=str(m.get("notes", "")),
    )


def run_research_eval(
    task: ResearchTask, candidate_code: str, sandbox: Sandbox, *, seed: int | None = None
) -> MetricRecord:
    """Score a candidate through the task's pack-declared evaluator adapter.

    ``seed`` is supplied only by the statistical regime's replicate harness (Goal 24); a
    deterministic adapter ignores it.
    """
    adapter = task.evaluator_adapter
    if adapter is None:
        adapter = load_pack(task.pack_id).adapter
    return adapter.evaluate(task, candidate_code, sandbox, seed=seed)


# --------------------------------------------------------------------------- #
# Statistical reproducibility policy (Goal 24) — promote noisy evaluators on a bound.
# --------------------------------------------------------------------------- #


#: Two-sided Student-t critical values t_{(1+c)/2, df} for the confidence levels the
#: statistical policy supports. Hardcoded so the gate is deterministic and dependency-free;
#: ``df >= 30`` falls back to the large-sample (normal) value at key ``"inf"``.
_T_CRITICAL: dict[float, dict[int | str, float]] = {
    0.90: {
        1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015, 6: 1.943, 7: 1.895, 8: 1.860,
        9: 1.833, 10: 1.812, 11: 1.796, 12: 1.782, 13: 1.771, 14: 1.761, 15: 1.753,
        16: 1.746, 17: 1.740, 18: 1.734, 19: 1.729, 20: 1.725, 21: 1.721, 22: 1.717,
        23: 1.714, 24: 1.711, 25: 1.708, 26: 1.706, 27: 1.703, 28: 1.701, 29: 1.699,
        30: 1.697, "inf": 1.645,
    },
    0.95: {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
        9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074,
        23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045,
        30: 2.042, "inf": 1.960,
    },
    0.99: {
        1: 63.657, 2: 9.925, 3: 5.841, 4: 4.604, 5: 4.032, 6: 3.707, 7: 3.499, 8: 3.355,
        9: 3.250, 10: 3.169, 11: 3.106, 12: 3.055, 13: 3.012, 14: 2.977, 15: 2.947,
        16: 2.921, 17: 2.898, 18: 2.878, 19: 2.861, 20: 2.845, 21: 2.831, 22: 2.819,
        23: 2.807, 24: 2.797, 25: 2.787, 26: 2.779, 27: 2.771, 28: 2.763, 29: 2.756,
        30: 2.750, "inf": 2.576,
    },
}


def _t_critical(df: int, confidence: float) -> float:
    """Two-sided Student-t critical value for ``df`` degrees of freedom at ``confidence``."""
    table = _T_CRITICAL.get(confidence)
    if table is None:
        raise ValueError(
            f"unsupported statistical confidence level {confidence!r}; "
            f"supported: {sorted(_T_CRITICAL)} (widening is a human-gated change)"
        )
    return table[df] if df in table and df <= 30 else table["inf"]


def _confidence_interval(samples: list[float], confidence: float) -> tuple[float, float, float]:
    """Two-sided ``confidence`` interval (mean, low, high) of ``samples``.

    A degenerate, zero-variance set (e.g. a deterministic evaluator) collapses to a point
    interval at the mean, so a deterministic positive gain still promotes and a deterministic
    zero gain does not — the statistical policy is strictly a *generalization* of the exact
    one, never looser.
    """
    n = len(samples)
    mean = sum(samples) / n
    if n < 2:
        return mean, mean, mean
    variance = sum((x - mean) ** 2 for x in samples) / (n - 1)
    standard_error = math.sqrt(variance) / math.sqrt(n)
    half_width = _t_critical(n - 1, confidence) * standard_error
    return mean, mean - half_width, mean + half_width


@dataclass(frozen=True)
class StatisticalPolicy:
    """Fixed harness parameters for the ``statistical`` reproducibility regime (Goal 24).

    ``seeds`` (and therefore the replicate count ``N``), the ``confidence`` level, and the
    ``secondary_regression_tolerance`` are controller/config-owned bounds: a candidate can
    neither set nor read them. Tightening (more seeds, higher confidence) is a config change;
    loosening is a reviewed, human-gated escalation (``docs/13``).
    """

    seeds: tuple[int, ...] = DEFAULT_STATISTICAL_SEEDS
    confidence: float = DEFAULT_STATISTICAL_CONFIDENCE
    #: A noisy secondary may drift this far in its worse direction within its CI before it
    #: counts as a regression. ``0.0`` means no statistically-resolved regression is tolerated.
    secondary_regression_tolerance: float = 0.0

    @property
    def replicates(self) -> int:
        return len(self.seeds)


#: The default statistical policy used by the controller when none is configured.
DEFAULT_STATISTICAL_POLICY = StatisticalPolicy()


@dataclass(frozen=True)
class StatisticalAssessment:
    """The replicate evaluation outcome: representative metrics + the recorded evidence."""

    candidate_metric: MetricRecord
    baseline_metric: MetricRecord
    evidence: StatisticalEvidence


def assess_statistical(
    task: ResearchTask,
    candidate_code: str,
    baseline_code: str,
    sandbox: Sandbox,
    *,
    policy: StatisticalPolicy = DEFAULT_STATISTICAL_POLICY,
) -> StatisticalAssessment:
    """Run candidate and incumbent ``N`` times under fixed seeds and bound the gain (Goal 24).

    For each seed the candidate and the baseline are scored under the *same* seed (a paired
    comparison that cancels common noise), and a direction-aware confidence interval is
    computed on the per-seed primary-metric delta (oriented so larger is always better).
    Promotion requires the interval to **exclude "no improvement"** — a lucky or within-noise
    win cannot promote. Every secondary with a declared direction is checked the same way: it
    may not regress past ``secondary_regression_tolerance`` within its own confidence bound.

    The seeds, replicate count, confidence level, and resulting interval are returned on the
    :class:`StatisticalEvidence` so the *decision* is reproducible even though the metric is
    noisy: re-running on the same seeds yields the same interval and the same decision.
    """
    candidate_metrics = [
        run_research_eval(task, candidate_code, sandbox, seed=seed) for seed in policy.seeds
    ]
    baseline_metrics = [
        run_research_eval(task, baseline_code, sandbox, seed=seed) for seed in policy.seeds
    ]
    representative_candidate = candidate_metrics[0]
    representative_baseline = baseline_metrics[0]

    reproducible = all(m.passed and m.reproducible for m in candidate_metrics) and all(
        m.passed and m.reproducible for m in baseline_metrics
    )
    deltas = [c.directional() - b.directional() for c, b in zip(candidate_metrics, baseline_metrics)]
    mean, low, high = _confidence_interval(deltas, policy.confidence)
    primary_clears = reproducible and low > MIN_PRIMARY_IMPROVEMENT

    secondary_within_bound: dict[str, bool] = {}
    for name, higher_is_better in task.secondary_directions.items():
        if not all(name in m.secondary for m in candidate_metrics) or not all(
            name in m.secondary for m in baseline_metrics
        ):
            continue
        sign = 1.0 if higher_is_better else -1.0
        secondary_deltas = [
            sign * (c.secondary[name] - b.secondary[name])
            for c, b in zip(candidate_metrics, baseline_metrics)
        ]
        _, s_low, _ = _confidence_interval(secondary_deltas, policy.confidence)
        secondary_within_bound[name] = s_low >= -policy.secondary_regression_tolerance
    secondaries_ok = all(secondary_within_bound.values())

    promoted = primary_clears and secondaries_ok
    interval = f"[{low:g}, {high:g}]"
    if not reproducible:
        reason = "candidate did not pass on every seeded replicate"
    elif not primary_clears:
        reason = f"improvement within noise: {int(policy.confidence * 100)}% CI {interval} includes zero"
    elif not secondaries_ok:
        regressed = sorted(n for n, ok in secondary_within_bound.items() if not ok)
        reason = f"secondary regression within bound: {', '.join(regressed)}"
    else:
        reason = (
            f"{task.primary_name} gain {mean:g}, {int(policy.confidence * 100)}% CI {interval} "
            f"excludes zero across {policy.replicates} seeds"
        )
    evidence = StatisticalEvidence(
        replicates=policy.replicates,
        confidence=policy.confidence,
        seeds=list(policy.seeds),
        primary_name=task.primary_name,
        primary_delta_mean=mean,
        primary_delta_low=low,
        primary_delta_high=high,
        per_seed_primary_delta=deltas,
        secondary_within_bound=secondary_within_bound,
        reproducible=reproducible,
        promoted=promoted,
        reason=reason,
    )
    return StatisticalAssessment(representative_candidate, representative_baseline, evidence)


def research_improves(
    candidate: MetricRecord,
    baseline: MetricRecord,
    *,
    regime: EvaluatorRegime = EvaluatorRegime.SEEDED_DETERMINISTIC,
    evidence: StatisticalEvidence | None = None,
) -> tuple[bool, str]:
    """Whether ``candidate`` is an objective improvement over ``baseline``.

    Dispatches on the declared evaluator ``regime`` (Goal 24). The ``exact`` and
    ``seeded-deterministic`` regimes use the deterministic single-sample comparison below,
    unchanged. The ``statistical`` regime defers to the replicate ``evidence``: the candidate
    improves only if the direction-aware confidence interval on the primary-metric delta
    excludes "no improvement" — a within-noise gain is not an improvement.

    A candidate must first satisfy the correctness/success precondition (``passed``); a
    candidate that fails it can never be promoted, regardless of its primary value (this is
    what stops a "fast but wrong" or loophole candidate from winning). Among passing
    candidates the primary metric — oriented so larger is always better — must strictly
    improve by :data:`MIN_PRIMARY_IMPROVEMENT`. If the baseline itself does not pass, any
    passing candidate is an improvement.
    """
    name = candidate.primary_name
    if not candidate.passed:
        return False, "candidate failed the correctness/success precondition"
    if regime is EvaluatorRegime.STATISTICAL:
        if evidence is None:
            return False, "statistical regime requires replicate evidence"
        if evidence.reproducible and evidence.primary_delta_low > MIN_PRIMARY_IMPROVEMENT:
            return True, (
                f"{name} delta CI [{evidence.primary_delta_low:g}, "
                f"{evidence.primary_delta_high:g}] excludes zero"
            )
        return False, evidence.reason or "improvement within noise (CI includes zero)"
    if not baseline.passed:
        return True, "candidate passes where baseline did not"
    delta = candidate.directional() - baseline.directional()
    if delta > MIN_PRIMARY_IMPROVEMENT:
        return True, f"{name} {baseline.primary:g} -> {candidate.primary:g}"
    if (
        name == "proof_verified"
        and abs(delta) <= MIN_PRIMARY_IMPROVEMENT
        and candidate.passed
        and baseline.passed
    ):
        for secondary_name in ("proof_length", "dependency_count"):
            if secondary_name not in candidate.secondary or secondary_name not in baseline.secondary:
                continue
            before = baseline.secondary[secondary_name]
            after = candidate.secondary[secondary_name]
            if before - after > MIN_PRIMARY_IMPROVEMENT:
                return True, f"{secondary_name} {before:g} -> {after:g}"
    return False, f"no improvement on {name} ({baseline.primary:g} -> {candidate.primary:g})"


def research_reproducibility_gate(
    task: ResearchTask,
    candidate_code: str,
    sandbox: Sandbox,
    *,
    runs: int = 2,
    evidence: StatisticalEvidence | None = None,
) -> GateResult:
    """Require a promotion contender's improvement to be reproducible, by regime (Goal 24).

    Dispatches on the task's declared evaluator regime — the same gate, generalized across a
    spectrum, never weakened:

    - ``exact`` — reruns must agree **bit-for-bit** (proof checkers, formal equivalence).
    - ``seeded-deterministic`` — today's behavior: reruns must agree within
      :data:`REPRO_TOLERANCE` (Goal 09).
    - ``statistical`` — the gain must clear a **confidence bound** across the policy's fixed
      seeded replicates (the ``evidence`` computed by :func:`assess_statistical`); a
      within-noise or non-reproducible candidate fails. Because the seeds are fixed, the
      decision is itself reproducible: the same seeds yield the same interval and decision.

    A candidate whose metric is not reproducible — because it failed to run on a rerun or
    drifted past tolerance, or its improvement lies within noise — fails and is never promoted.
    """
    if task.evaluator_regime is EvaluatorRegime.STATISTICAL:
        if evidence is None:
            return GateResult(
                gate="research_reproducibility",
                decision=GateDecision.FAILED,
                risk_level="high",
                findings=["statistical regime requires replicate evidence (none computed)"],
            )
        interval = f"[{evidence.primary_delta_low:g}, {evidence.primary_delta_high:g}]"
        summary = (
            f"{evidence.replicates} seeded replicates at {int(evidence.confidence * 100)}% "
            f"confidence, primary-delta CI {interval}, seeds={evidence.seeds}"
        )
        if not evidence.promoted:
            return GateResult(
                gate="research_reproducibility",
                decision=GateDecision.FAILED,
                risk_level="high",
                findings=[f"{evidence.reason} ({summary})"],
            )
        return GateResult(
            gate="research_reproducibility",
            decision=GateDecision.PASSED,
            risk_level="low",
            notes=f"improvement clears the confidence bound: {summary}",
        )
    # The exact regime demands bit-for-bit agreement; seeded-deterministic allows the
    # historical floating-point tolerance. Both reproduce existing behavior for current tasks.
    # ``exact`` and ``external-oracle`` demand bit-for-bit agreement: the external adapter
    # re-reads the same signed, approved result, so two reads must agree exactly (and a
    # candidate with no live result fails to produce a passing metric, never promoting).
    exact_regimes = {EvaluatorRegime.EXACT, EvaluatorRegime.EXTERNAL_ORACLE}
    tolerance = 0.0 if task.evaluator_regime in exact_regimes else REPRO_TOLERANCE
    runs = max(runs, 2)
    metrics = [run_research_eval(task, candidate_code, sandbox) for _ in range(runs)]
    if not all(m.passed and m.reproducible for m in metrics):
        return GateResult(
            gate="research_reproducibility",
            decision=GateDecision.FAILED,
            risk_level="medium",
            findings=["candidate did not produce a passing metric on every rerun"],
        )
    primaries = [round(m.primary, 12) for m in metrics]
    if max(primaries) - min(primaries) > tolerance:
        return GateResult(
            gate="research_reproducibility",
            decision=GateDecision.FAILED,
            risk_level="high",
            findings=[f"primary metric not reproducible across reruns: {primaries}"],
        )
    return GateResult(
        gate="research_reproducibility",
        decision=GateDecision.PASSED,
        risk_level="low",
        notes=f"{runs} reruns consistent at {task.primary_name}={primaries[0]:g}",
    )


# --------------------------------------------------------------------------- #
# Archive + memory derivation.
# --------------------------------------------------------------------------- #


def _read_lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return iter(())
    with path.open("r", encoding="utf-8") as fh:
        return iter([line for line in (raw.strip() for raw in fh) if line])


class ResearchArchive:
    """Append-only JSONL archive of :class:`ResearchAttempt`s — separate from code attempts.

    Kept in its own file (``runs/research_attempts.jsonl``) so a research attempt is never
    confused with a code or training attempt, and every candidate tried — promoted or
    rejected — stays auditable.
    """

    def __init__(self, path: str | Path = DEFAULT_RESEARCH_ATTEMPTS_PATH) -> None:
        self.path = Path(path)

    def append(self, attempt: ResearchAttempt) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(attempt.model_dump_json() + "\n")

    def read_all(self) -> list[ResearchAttempt]:
        return [ResearchAttempt.model_validate_json(line) for line in _read_lines(self.path)]

    def __len__(self) -> int:
        return sum(1 for _ in _read_lines(self.path))


def _candidate_summary(code: str) -> str:
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:120]
    return ""


def entry_from_research_attempt(attempt: ResearchAttempt) -> MemoryEntry:
    """Derive a typed :class:`MemoryEntry` from a research attempt (controller-only write).

    The only path from a research attempt into memory; it runs in the controller, never a
    model. The metric becomes a directional ``score`` (larger is better) so memory's
    highest-scoring retrieval works uniformly across families.
    """
    metric = attempt.metric
    signature = failure_signature(attempt.reason)
    if metric is None:
        evaluator_output = "no evaluation"
        score = 0.0
    else:
        evaluator_output = (
            f"{metric.primary_name}={metric.primary:g} passed={metric.passed} "
            f"reproducible={metric.reproducible}"
        )
        score = metric.directional() if metric.passed else 0.0
    return MemoryEntry(
        entry_id=uuid.uuid4().hex[:12],
        experiment_id=attempt.attempt_id,
        source_experiment_id=attempt.candidate.parent_id or "",
        task_id=attempt.task_id,
        pack_id=attempt.pack_id,
        pack_version=attempt.pack_version,
        candidate_summary=_candidate_summary(attempt.candidate.code),
        score=score,
        failure_mode=signature,
        reason=attempt.reason,
        evaluator_output=evaluator_output,
        status=attempt.status,
        created_at=attempt.created_at,
    )


# --------------------------------------------------------------------------- #
# Suite summary — per task family.
# --------------------------------------------------------------------------- #


@dataclass
class ResearchFamilySummary:
    """Aggregate progress for one task family (Goal 09 acceptance: the summary command)."""

    family: str
    task_ids: list[str] = field(default_factory=list)
    attempts: int = 0
    accepted: int = 0
    promoted: int = 0
    mixed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    median_cycles_to_success: float | None = None
    safety_gate_failures: int = 0
    hidden_test_failures: int = 0
    reproducibility_failures: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    cost_per_promotion: float | None = None
    strategy_diversity: float = 0.0


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _cycles_to_success(attempts: list[ResearchAttempt]) -> int | None:
    """Number of attempts up to and including the first promotion, or ``None`` if never."""
    for i, a in enumerate(attempts, start=1):
        if a.status is AttemptStatus.PROMOTED:
            return i
    return None


def _has_safety_gate_failure(attempt: ResearchAttempt) -> bool:
    if attempt.gates is None:
        return False
    return any(
        r.gate == "safety" and r.decision is not GateDecision.PASSED for r in attempt.gates.results
    )


def _has_gate_failure(attempt: ResearchAttempt, needle: str) -> bool:
    if attempt.gates is None:
        return False
    return any(
        needle in r.gate and r.decision is not GateDecision.PASSED for r in attempt.gates.results
    )


def summarize_research(
    attempts: list[ResearchAttempt], ledger_rows=None
) -> dict[str, ResearchFamilySummary]:
    """Summarize the research-attempt archive per task family.

    Reports, per family: pass rate, median cycles to success, safety-gate failures,
    token/USD spend, and strategy diversity (Goal 09 acceptance criteria). ``ledger_rows``
    is the model-call audit ledger (:class:`~siro.schemas.ModelCall`); spend is attributed
    to a family by matching each row's ``experiment_id`` to the family's task ids.
    """
    by_family: dict[str, list[ResearchAttempt]] = {}
    for a in attempts:
        by_family.setdefault(a.family or "(unknown)", []).append(a)

    # task_id -> family, to attribute ledger spend.
    task_family = {a.task_id: (a.family or "(unknown)") for a in attempts}
    spend: dict[str, tuple[int, float]] = {}
    for row in ledger_rows or []:
        fam = task_family.get(row.experiment_id)
        if fam is None:
            continue
        tokens, cost = spend.get(fam, (0, 0.0))
        spend[fam] = (tokens + row.input_tokens + row.output_tokens, cost + row.cost_usd)

    summaries: dict[str, ResearchFamilySummary] = {}
    for family, fam_attempts in sorted(by_family.items()):
        task_ids = sorted({a.task_id for a in fam_attempts})
        n = len(fam_attempts)
        passed = sum(1 for a in fam_attempts if a.metric is not None and a.metric.passed)
        promoted = sum(1 for a in fam_attempts if a.status is AttemptStatus.PROMOTED)
        errors = sum(1 for a in fam_attempts if a.status is AttemptStatus.ERROR)
        rejected = sum(1 for a in fam_attempts if a.status is AttemptStatus.REJECTED)
        mixed = sum(
            1
            for a in fam_attempts
            if a.status is AttemptStatus.REJECTED and a.metric is not None and a.metric.passed
        )

        cycles: list[float] = []
        for task_id in task_ids:
            ta = [a for a in fam_attempts if a.task_id == task_id]
            c = _cycles_to_success(ta)
            if c is not None:
                cycles.append(float(c))

        distinct = len({a.candidate.code for a in fam_attempts})
        tokens, cost = spend.get(family, (0, 0.0))
        summaries[family] = ResearchFamilySummary(
            family=family,
            task_ids=task_ids,
            attempts=n,
            accepted=promoted,
            promoted=promoted,
            mixed=mixed,
            failed=rejected + errors - mixed,
            pass_rate=(passed / n) if n else 0.0,
            median_cycles_to_success=_median(cycles) if cycles else None,
            safety_gate_failures=sum(1 for a in fam_attempts if _has_safety_gate_failure(a)),
            hidden_test_failures=sum(
                1
                for a in fam_attempts
                if _has_gate_failure(a, "hidden") or "hidden" in a.reason.lower()
            ),
            reproducibility_failures=sum(
                1
                for a in fam_attempts
                if _has_gate_failure(a, "reproducibility")
                or "reproduc" in a.reason.lower()
                or (a.metric is not None and a.metric.passed and not a.metric.reproducible)
            ),
            tokens=tokens,
            cost_usd=cost,
            cost_per_promotion=(cost / promoted) if promoted else None,
            strategy_diversity=(distinct / n) if n else 0.0,
        )
    return summaries


def select_best_research(attempts: list[ResearchAttempt]) -> ResearchAttempt | None:
    """Return the best passing, reproducible attempt (highest directional primary), or None."""
    scored = [
        a for a in attempts if a.metric is not None and a.metric.passed and a.metric.reproducible
    ]
    if not scored:
        return None
    return max(scored, key=lambda a: a.metric.directional())


def make_candidate(task: ResearchTask, code: str, parent_id: str = "seed") -> Candidate:
    """Build a :class:`Candidate` for a research task's edit surface."""
    return Candidate(
        candidate_id=uuid.uuid4().hex[:12], task_id=task.task_id, code=code, parent_id=parent_id
    )


__all__ = [
    "DEFAULT_RESEARCH_ATTEMPTS_PATH",
    "DEFAULT_RESEARCH_TASKS_DIR",
    "DEFAULT_RESEARCH_BUDGET_SECONDS",
    "MIN_PRIMARY_IMPROVEMENT",
    "REPRO_TOLERANCE",
    "DEFAULT_STATISTICAL_SEEDS",
    "DEFAULT_STATISTICAL_CONFIDENCE",
    "DEFAULT_STATISTICAL_POLICY",
    "StatisticalPolicy",
    "StatisticalAssessment",
    "assess_statistical",
    "ResearchTask",
    "load_research_task",
    "discover_research_tasks",
    "hidden_payload",
    "run_research_eval",
    "research_improves",
    "research_reproducibility_gate",
    "ResearchArchive",
    "entry_from_research_attempt",
    "ResearchFamilySummary",
    "summarize_research",
    "select_best_research",
    "make_candidate",
]
