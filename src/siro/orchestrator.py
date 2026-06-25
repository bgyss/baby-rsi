"""Orchestrator — the control plane that runs the full research org end-to-end (Goal 08).

This is the Tier 1 prototype of ``docs/08_frontier_prototype_architecture.md``: one human
objective is routed through the model-backed roles (Hypothesis → Literature → triage →
Implementation → gates → sandbox → Evaluation → Safety → Interpretation → promotion →
Memory → agenda update), reusing the **unchanged** lifecycle, gates, evaluator, and memory
schema — only the agents behind the roles get more capable.

The orchestrator holds every load-bearing invariant in code, not in trust:

- **Plane isolation.** Agents (control plane) reach a model client; the candidate runs in
  the offline :class:`~siro.sandbox.Sandbox` with no network, a scrubbed env, and a hard
  timeout. A model produces a patch; the *controller* runs the fixed vetted commands.
- **Cross-model review.** At Tier ≥ 1 the Safety reviewer must bind to a different provider
  than the Implementation Agent; a config that violates this is refused. Disagreement
  between the safety reviewer and the objective promotion gate is surfaced as an
  **escalation**, never silently broken as a tie.
- **Budget + audit.** Every agent's model call is logged to the audit ledger and charged
  against the token/USD ceilings; a breach halts and escalates.
- **Bounds.** Meta-research is proposal-only and human-gated; nothing here weakens a gate,
  the evaluator, budgets, permissions, egress, or tier.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .agents import build_agents
from .agents.base import Agent, AgentResult
from .agents.roles import (
    EVALUATION,
    HYPOTHESIS,
    IMPLEMENTATION,
    INTERPRETATION,
    LITERATURE,
    MEMORY,
    META_RESEARCH,
    SAFETY,
)
from .agents.schemas import (
    EvaluationInput,
    HypothesisInput,
    ImplementationInput,
    InterpretationInput,
    LiteratureInput,
    MemoryCuratorInput,
    MetaResearchInput,
    SafetyClassification,
    SafetyInput,
)
from .archive import JSONLArchive, ModelCallLedger
from .controller import LoadedTask, load_task
from .evaluator import evaluate
from .gates import function_signatures, promotion_gate, static_gates
from .memory import ResearchMemory, entry_from_attempt
from .meta import forbidden_meta_change
from .providers.base import extract_code
from .research import (
    ResearchArchive,
    ResearchTask,
    entry_from_research_attempt,
    load_research_task,
    make_candidate,
    research_improves,
    research_reproducibility_gate,
    run_research_eval,
)
from .sandbox import Sandbox
from .schemas import (
    Attempt,
    AttemptStatus,
    Candidate,
    EvaluationResult,
    GateDecision,
    GateReport,
    MetricRecord,
    ModelCall,
    ResearchAttempt,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .budget import BudgetTracker
    from .config import SiroConfig
    from .providers._http import Transport


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _fmt_eval(ev: EvaluationResult | None) -> str:
    if ev is None:
        return "(not evaluated — blocked before execution)"
    return (
        f"score={ev.score:.1f} passed={ev.passed_tests} failed={ev.failed_tests} "
        f"runtime_ms={ev.runtime_ms:.1f} reproducible={ev.reproducible}"
    )


def _objective_pass(ev: EvaluationResult | None) -> bool:
    """A reproducible candidate that passes every test (the objective, authoritative read)."""
    return ev is not None and ev.reproducible and ev.failed_tests == 0 and ev.passed_tests > 0


def _fmt_metric(m: MetricRecord | None) -> str:
    """One-line render of a research metric record for the agent prompts and the trace."""
    if m is None:
        return "(not evaluated — blocked before execution)"
    secondary = " ".join(f"{k}={v:g}" for k, v in m.secondary.items())
    base = (
        f"{m.primary_name}={m.primary:g} passed={m.passed} reproducible={m.reproducible}"
    )
    return f"{base} {secondary}".rstrip() if not m.error else f"{base} error={m.error}"


def _research_objective_pass(m: MetricRecord | None) -> bool:
    """The objective, authoritative read of a research metric (reproducible + passed)."""
    return m is not None and m.reproducible and m.passed


def _improves(candidate: EvaluationResult, baseline: EvaluationResult) -> tuple[bool, str]:
    """Whether ``candidate`` is an objective improvement over ``baseline``.

    Deterministic by construction (so promotion never hinges on runtime jitter): the
    primary metric is the test outcome — more passing or fewer failing tests — and the
    secondary, tie-breaking metric is lower complexity. Equal test outcome *and* equal
    complexity is not a meaningful improvement (e.g. re-proposing the seed). Runtime is
    recorded in the score but is too noisy to gate a promotion on, so it is excluded here.
    """
    if candidate.passed_tests != baseline.passed_tests:
        better = candidate.passed_tests > baseline.passed_tests
        return better, f"passed tests {baseline.passed_tests} -> {candidate.passed_tests}"
    if candidate.failed_tests != baseline.failed_tests:
        better = candidate.failed_tests < baseline.failed_tests
        return better, f"failed tests {baseline.failed_tests} -> {candidate.failed_tests}"
    if candidate.complexity_penalty != baseline.complexity_penalty:
        better = candidate.complexity_penalty < baseline.complexity_penalty
        return better, (
            f"complexity {baseline.complexity_penalty:.1f} -> {candidate.complexity_penalty:.1f}"
        )
    return False, "identical test outcome and complexity to baseline"


@dataclass
class CycleResult:
    """The full, auditable trace of one research cycle (one objective on one task)."""

    objective: str
    task_id: str
    budget_tier: int
    cross_model_review: bool
    attempt: Attempt
    promotion_decision: GateDecision
    gates: GateReport
    agent_outputs: dict[str, AgentResult] = field(default_factory=dict)
    escalations: list[str] = field(default_factory=list)
    triaged_in: bool = True
    next_actions: list[str] = field(default_factory=list)

    @property
    def promoted(self) -> bool:
        return self.promotion_decision is GateDecision.PASSED


@dataclass
class ResearchCycleResult:
    """The full, auditable trace of one research-shaped cycle (Goal 09).

    The analogue of :class:`CycleResult` for a ``tasks/research/`` task: the org ran the
    full lifecycle and the task's own ``eval.py`` (not a model) decided promotion. Carries
    the typed :class:`MetricRecord` and the task ``family`` so the suite summary can report
    per family.
    """

    objective: str
    task_id: str
    family: str
    budget_tier: int
    cross_model_review: bool
    attempt: ResearchAttempt
    promotion_decision: GateDecision
    gates: GateReport
    metric: MetricRecord | None = None
    baseline_metric: MetricRecord | None = None
    agent_outputs: dict[str, AgentResult] = field(default_factory=dict)
    escalations: list[str] = field(default_factory=list)
    triaged_in: bool = True
    next_actions: list[str] = field(default_factory=list)

    @property
    def promoted(self) -> bool:
        return self.promotion_decision is GateDecision.PASSED


class Orchestrator:
    """Routes one objective through the full organization (the control plane)."""

    def __init__(
        self,
        agents: dict[str, Agent] | None = None,
        *,
        sandbox: Sandbox | None = None,
        memory: ResearchMemory | None = None,
        archive: JSONLArchive | None = None,
        ledger: ModelCallLedger | None = None,
        budget: "BudgetTracker | None" = None,
        require_cross_model: bool = False,
        budget_tier: int = 1,
        references_path: str | Path = "docs/12_references.md",
        config: "SiroConfig | None" = None,
        transport: "Transport | None" = None,
        retrieval_limit: int = 5,
        research_archive: ResearchArchive | None = None,
    ) -> None:
        # Use `is None` (not `or`): JSONLArchive/ResearchMemory are falsy when empty.
        self._agents = agents
        self.sandbox = Sandbox() if sandbox is None else sandbox
        self.memory = ResearchMemory() if memory is None else memory
        self.archive = JSONLArchive() if archive is None else archive
        # Research-task attempts live in their own archive (Goal 09), never mixed with the
        # code-improver attempts archive.
        self.research_archive = ResearchArchive() if research_archive is None else research_archive
        self.ledger = ModelCallLedger() if ledger is None else ledger
        self.budget = budget
        self.require_cross_model = require_cross_model
        self.budget_tier = budget_tier
        self.references_path = references_path
        self.retrieval_limit = retrieval_limit
        self._config = config
        self._transport = transport

    # --- construction from config ------------------------------------------
    @classmethod
    def from_config(
        cls,
        config: "SiroConfig",
        *,
        memory: ResearchMemory | None = None,
        archive: JSONLArchive | None = None,
        ledger: ModelCallLedger | None = None,
        budget: "BudgetTracker | None" = None,
        sandbox: Sandbox | None = None,
        references_path: str | Path = "docs/12_references.md",
        transport: "Transport | None" = None,
        research_archive: ResearchArchive | None = None,
    ) -> "Orchestrator":
        """Bind every role to the provider its tier config selects.

        At Tier 0 every role resolves to the local client; at Tier 1 reasoning roles bind
        to frontier providers and Safety to a *different* provider than Implementation.
        Lowering ``tier: 1`` → ``tier: 0`` re-runs this with no code change. Cross-model
        review is required (and verified) once ``tier >= 1``.
        """
        orch = cls(
            agents=None,
            sandbox=sandbox,
            memory=memory,
            archive=archive,
            ledger=ledger,
            budget=budget,
            require_cross_model=config.tier >= 1,
            budget_tier=config.tier,
            references_path=references_path,
            config=config,
            transport=transport,
            research_archive=research_archive,
        )
        orch._assert_cross_model_config(config)
        return orch

    @staticmethod
    def _assert_cross_model_config(config: "SiroConfig") -> None:
        """Refuse a Tier ≥ 1 config where Safety and Implementation share a provider."""
        if config.tier < 1:
            return
        impl = config.provider_for_role(IMPLEMENTATION)
        safety = config.provider_for_role(SAFETY)
        if impl.key == safety.key:
            raise ValueError(
                "Cross-model review violated: the Safety Agent must bind to a different "
                f"provider than the Implementation Agent, but both bind to {impl.key!r}. "
                "Fix agent_models in the tier config (no code change)."
            )

    # --- agent binding ------------------------------------------------------
    def _agents_for_task(self, task: LoadedTask) -> dict[str, Agent]:
        """The role→agent map for a task. Rebuilt from config (so toolboxes are
        task-scoped) when constructed via :meth:`from_config`; otherwise the injected map."""
        if self._config is not None:
            return build_agents(
                self._config,
                memory=self.memory,
                task_id=task.task_id,
                allowed_surfaces=[self._module_path(task)],
                references_path=self.references_path,
                transport=self._transport,
            )
        if self._agents is None:
            raise ValueError("Orchestrator has neither a config nor an agents map.")
        return self._agents

    @staticmethod
    def _module_path(task: LoadedTask) -> Path:
        """The single allowed edit surface for a code-improver task: its seed module."""
        return Path(task.spec.path) / f"{task.module_name}.py"

    # --- audit + budget -----------------------------------------------------
    def _log(self, result: AgentResult, task_id: str) -> None:
        """Append one audit-ledger row for an agent call, then charge the budget.

        Logging happens before the budget check so even the call that trips a ceiling is
        auditable; a breach raises ``BudgetExceeded`` and halts the cycle (escalation).
        """
        response = result.response
        usage = response.usage
        prompt_hash = response.prompt_hash or hashlib.sha256(
            result.role.encode("utf-8")
        ).hexdigest()[:16]
        self.ledger.append(
            ModelCall(
                provider=response.provider or getattr(result, "provider", "unknown"),
                model=response.model or "unknown",
                prompt_hash=prompt_hash,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=usage.cost_usd,
                latency_ms=usage.latency_ms,
                pricing_metadata=usage.pricing_metadata,
                experiment_id=task_id,
            )
        )
        if self.budget is not None:
            self.budget.charge(usage)

    # --- the full cycle -----------------------------------------------------
    def run_cycle(self, objective: str, task_dir: str | Path) -> CycleResult:
        """Run one full research cycle on ``task_dir`` for ``objective``.

        Completes hypothesis → literature → triage → implementation → gates → sandbox →
        evaluation → safety → interpretation → promotion → memory, recording every step.
        """
        task = load_task(task_dir)
        agents = self._agents_for_task(task)
        cross_model = agents[SAFETY].provider != agents[IMPLEMENTATION].provider
        if self.require_cross_model and not cross_model:
            raise ValueError(
                "Cross-model review required at this tier but Safety and Implementation "
                f"share provider {agents[IMPLEMENTATION].provider!r}."
            )

        outputs: dict[str, AgentResult] = {}
        escalations: list[str] = []
        allowed_signatures = function_signatures(task.seed_code)
        lessons = self.memory.lessons_block(task.task_id, limit=self.retrieval_limit)

        # 1. Hypothesis — a falsifiable idea with a predicted result + expected failure.
        hyp = agents[HYPOTHESIS].run(
            HypothesisInput(
                objective=objective,
                task_prompt=task.prompt,
                memory_summaries=lessons,
                known_bottlenecks=self._bottlenecks(task.task_id),
            )
        )
        outputs[HYPOTHESIS] = hyp
        self._log(hyp, task.task_id)

        # 2. Literature — ground + dedupe against references and memory.
        lit = agents[LITERATURE].run(
            LiteratureInput(
                hypothesis=hyp.output.statement,
                references=self._references_text(),
                prior_summaries=lessons,
            )
        )
        outputs[LITERATURE] = lit
        self._log(lit, task.task_id)

        # 3. Orchestrator triage — a flagged duplicate does not get budget spent on it.
        triaged_in = not lit.output.is_duplicate
        if not triaged_in:
            escalations.append("literature flagged a duplicate/known result — triaged out")

        # 4. Implementation — a patch limited to the allowed edit surface.
        impl = agents[IMPLEMENTATION].run(
            ImplementationInput(
                experiment_plan=hyp.output.proposed_experiment or hyp.output.statement,
                allowed_edit_surfaces=[str(self._module_path(task))],
                baseline_code=task.seed_code,
                module_name=task.module_name,
                test_requirements=task.prompt,
                memory_lessons=lessons,
            )
        )
        outputs[IMPLEMENTATION] = impl
        self._log(impl, task.task_id)
        code = extract_code(impl.output.code)
        candidate = Candidate(
            candidate_id=_short_id(), task_id=task.task_id, code=code, parent_id="seed"
        )

        # 5. Code-integrity gate + static safety scan (control plane) — before any execution.
        static = static_gates(code, allowed_signatures=allowed_signatures)
        static_report = GateReport(results=static)

        # 6. Execution plane — offline sandbox runs candidate + fixed tests under timeout.
        baseline_eval = self._baseline_eval(task)
        evaluation: EvaluationResult | None = None
        logs = ""
        if triaged_in and static_report.passed:
            sandbox_result = self.sandbox.run(candidate, task)
            evaluation = evaluate(sandbox_result, code)
            logs = (sandbox_result.stderr or sandbox_result.stdout or "")[:500]

        # 7. Objective evaluator scored; the Evaluation Agent writes a regression narrative.
        eval_agent = agents[EVALUATION].run(
            EvaluationInput(
                baseline_metrics=_fmt_eval(baseline_eval),
                candidate_metrics=_fmt_eval(evaluation),
                regression_thresholds="primary: pytest pass rate; promote only if it does not regress",
            )
        )
        outputs[EVALUATION] = eval_agent
        self._log(eval_agent, task.task_id)
        objective_pass = _objective_pass(evaluation)
        if eval_agent.output.pass_fail != objective_pass:
            escalations.append(
                "evaluation-agent narrative disagrees with objective metrics "
                "(objective evaluator is authoritative)"
            )

        # 8. Safety Agent — cross-model review of diff, logs, tool use, eval results.
        safety = agents[SAFETY].run(
            SafetyInput(
                code_diff=code,
                tool_permissions=agents[IMPLEMENTATION].toolbox.names(),
                logs=logs,
                agent_outputs=f"hypothesis={hyp.output.statement}",
                eval_results=_fmt_eval(evaluation),
            )
        )
        outputs[SAFETY] = safety
        self._log(safety, task.task_id)

        # 9. Interpretation Agent — explain the result, draft a memory entry.
        interp = agents[INTERPRETATION].run(
            InterpretationInput(
                hypothesis=hyp.output.statement,
                experiment_plan=hyp.output.proposed_experiment,
                metrics=_fmt_eval(evaluation),
                logs=logs,
                failure_report="" if objective_pass else _fmt_eval(evaluation),
            )
        )
        outputs[INTERPRETATION] = interp
        self._log(interp, task.task_id)

        # 10. Promotion gate (control plane, objective) + cross-model promotion decision.
        report, decision, reason = self._decide(
            candidate,
            task,
            allowed_signatures,
            triaged_in=triaged_in,
            static_report=static_report,
            evaluation=evaluation,
            baseline_eval=baseline_eval,
            safety=safety,
            escalations=escalations,
        )

        status = (
            AttemptStatus.PROMOTED if decision is GateDecision.PASSED else AttemptStatus.REJECTED
        )
        attempt = Attempt(
            attempt_id=_short_id(),
            task_id=task.task_id,
            candidate=candidate,
            evaluation=evaluation,
            status=status,
            reason=reason,
            gates=report,
        )
        self.archive.append(attempt)

        # 11. Memory Curator — write the durable record (controller writes, not the model).
        mem = agents[MEMORY].run(
            MemoryCuratorInput(
                experiment_record=f"{candidate.candidate_id}: {_fmt_eval(evaluation)} -> {status.value}",
                interpretation=interp.output.result_summary,
                metadata=f"task={task.task_id} decision={decision.value}",
            )
        )
        outputs[MEMORY] = mem
        self._log(mem, task.task_id)
        self._write_memory(attempt, mem, interp)

        # 12. Meta-Research — periodically propose a bounded, human-gated process change.
        meta = agents[META_RESEARCH].run(
            MetaResearchInput(
                experiment_history=self._history_summary(task.task_id),
                failure_modes=self._bottlenecks(task.task_id),
            )
        )
        outputs[META_RESEARCH] = meta
        self._log(meta, task.task_id)
        ok, why = forbidden_meta_change(meta.output.target, meta.output.proposed_change)
        if not ok:
            escalations.append(f"meta-research proposal out of bounds ({why}) — recorded, not applied")

        # 13. Orchestrator updates the agenda from the interpretation's follow-ups.
        next_actions = list(interp.output.follow_up_experiments)

        return CycleResult(
            objective=objective,
            task_id=task.task_id,
            budget_tier=self.budget_tier,
            cross_model_review=cross_model,
            attempt=attempt,
            promotion_decision=decision,
            gates=report,
            agent_outputs=outputs,
            escalations=escalations,
            triaged_in=triaged_in,
            next_actions=next_actions,
        )

    # --- the research cycle (Goal 09) ---------------------------------------
    def _agents_for_research_task(self, task: ResearchTask) -> dict[str, Agent]:
        """The role→agent map for a research task; the allowed edit surface is the task's
        single baseline file (so the Implementation toolbox is scoped to exactly it)."""
        if self._config is not None:
            return build_agents(
                self._config,
                memory=self.memory,
                task_id=task.task_id,
                allowed_surfaces=[task.allowed_surface],
                references_path=self.references_path,
                transport=self._transport,
            )
        if self._agents is None:
            raise ValueError("Orchestrator has neither a config nor an agents map.")
        return self._agents

    def run_research_cycle(self, objective: str, task_dir: str | Path) -> ResearchCycleResult:
        """Run one full org cycle on a research-shaped task (Goal 09).

        Same lifecycle and invariants as :meth:`run_cycle`, but the task's own controller-
        owned ``eval.py`` — run in the offline sandbox — is the authority for promotion (a
        typed :class:`MetricRecord`), not pytest pass/fail and not any model's self-judgment.
        The held-out data in ``hidden/`` reaches only ``eval.py``, never a prompt, and the
        static safety gate's no-file-I/O rule means a candidate cannot read it to leak it.
        """
        task = load_research_task(task_dir)
        agents = self._agents_for_research_task(task)
        cross_model = agents[SAFETY].provider != agents[IMPLEMENTATION].provider
        if self.require_cross_model and not cross_model:
            raise ValueError(
                "Cross-model review required at this tier but Safety and Implementation "
                f"share provider {agents[IMPLEMENTATION].provider!r}."
            )

        outputs: dict[str, AgentResult] = {}
        escalations: list[str] = []
        allowed_signatures = function_signatures(task.surface_code)
        lessons = self.memory.lessons_block(task.task_id, limit=self.retrieval_limit)
        module_name = Path(task.edit_surface).stem

        # 1. Hypothesis — a falsifiable idea grounded in the brief + memory.
        hyp = agents[HYPOTHESIS].run(
            HypothesisInput(
                objective=objective,
                task_prompt=task.brief,
                memory_summaries=lessons,
                known_bottlenecks=self._bottlenecks(task.task_id),
            )
        )
        outputs[HYPOTHESIS] = hyp
        self._log(hyp, task.task_id)

        # 2. Literature — ground + dedupe against references and memory.
        lit = agents[LITERATURE].run(
            LiteratureInput(
                hypothesis=hyp.output.statement,
                references=self._references_text(),
                prior_summaries=lessons,
            )
        )
        outputs[LITERATURE] = lit
        self._log(lit, task.task_id)
        triaged_in = not lit.output.is_duplicate
        if not triaged_in:
            escalations.append("literature flagged a duplicate/known result — triaged out")

        # 3. Implementation — a patch limited to the task's single edit surface.
        impl = agents[IMPLEMENTATION].run(
            ImplementationInput(
                experiment_plan=hyp.output.proposed_experiment or hyp.output.statement,
                allowed_edit_surfaces=[task.allowed_surface],
                baseline_code=task.surface_code,
                module_name=module_name,
                test_requirements=task.brief,
                memory_lessons=lessons,
            )
        )
        outputs[IMPLEMENTATION] = impl
        self._log(impl, task.task_id)
        code = extract_code(impl.output.code)
        candidate = make_candidate(task, code, parent_id="seed")

        # 4. Code-integrity + static safety scan (control plane) — before any execution.
        static_report = GateReport(results=static_gates(code, allowed_signatures=allowed_signatures))

        # 5. Execution plane — the task's fixed eval.py scores the seed and the candidate.
        baseline_metric = run_research_eval(task, task.surface_code, self.sandbox)
        metric: MetricRecord | None = None
        if triaged_in and static_report.passed:
            metric = run_research_eval(task, code, self.sandbox)

        # 6. Evaluation Agent — narrate the metric move (objective record is authoritative).
        direction = "higher" if task.higher_is_better else "lower"
        eval_agent = agents[EVALUATION].run(
            EvaluationInput(
                baseline_metrics=_fmt_metric(baseline_metric),
                candidate_metrics=_fmt_metric(metric),
                regression_thresholds=(
                    f"primary: {task.primary_name} ({direction} is better); promote only on a "
                    "reproducible improvement over baseline"
                ),
            )
        )
        outputs[EVALUATION] = eval_agent
        self._log(eval_agent, task.task_id)
        objective_pass = _research_objective_pass(metric)
        if eval_agent.output.pass_fail != objective_pass:
            escalations.append(
                "evaluation-agent narrative disagrees with objective metrics "
                "(objective evaluator is authoritative)"
            )

        # 7. Safety Agent — cross-model review of the diff, tools, and eval results.
        safety = agents[SAFETY].run(
            SafetyInput(
                code_diff=code,
                tool_permissions=agents[IMPLEMENTATION].toolbox.names(),
                logs=(metric.error if metric is not None else ""),
                agent_outputs=f"hypothesis={hyp.output.statement}",
                eval_results=_fmt_metric(metric),
            )
        )
        outputs[SAFETY] = safety
        self._log(safety, task.task_id)

        # 8. Interpretation Agent — explain the result, draft a memory entry.
        interp = agents[INTERPRETATION].run(
            InterpretationInput(
                hypothesis=hyp.output.statement,
                experiment_plan=hyp.output.proposed_experiment,
                metrics=_fmt_metric(metric),
                logs="",
                failure_report="" if objective_pass else _fmt_metric(metric),
            )
        )
        outputs[INTERPRETATION] = interp
        self._log(interp, task.task_id)

        # 9. Promotion decision: objective gate + reproducibility + cross-model safety.
        report, decision, reason = self._decide_research(
            task,
            code,
            triaged_in=triaged_in,
            static_report=static_report,
            metric=metric,
            baseline_metric=baseline_metric,
            safety=safety,
            escalations=escalations,
        )

        status = (
            AttemptStatus.PROMOTED if decision is GateDecision.PASSED else AttemptStatus.REJECTED
        )
        attempt = ResearchAttempt(
            attempt_id=_short_id(),
            task_id=task.task_id,
            family=task.family,
            candidate=candidate,
            metric=metric,
            status=status,
            reason=reason,
            gates=report,
        )
        self.research_archive.append(attempt)

        # 10. Memory Curator — write the durable record (controller writes, not the model).
        mem = agents[MEMORY].run(
            MemoryCuratorInput(
                experiment_record=f"{candidate.candidate_id}: {_fmt_metric(metric)} -> {status.value}",
                interpretation=interp.output.result_summary,
                metadata=f"task={task.task_id} family={task.family} decision={decision.value}",
            )
        )
        outputs[MEMORY] = mem
        self._log(mem, task.task_id)
        self._write_research_memory(attempt, mem)

        # 11. Meta-Research — periodically propose a bounded, human-gated process change.
        meta = agents[META_RESEARCH].run(
            MetaResearchInput(
                experiment_history=self._history_summary(task.task_id),
                failure_modes=self._bottlenecks(task.task_id),
            )
        )
        outputs[META_RESEARCH] = meta
        self._log(meta, task.task_id)
        ok, why = forbidden_meta_change(meta.output.target, meta.output.proposed_change)
        if not ok:
            escalations.append(f"meta-research proposal out of bounds ({why}) — recorded, not applied")

        return ResearchCycleResult(
            objective=objective,
            task_id=task.task_id,
            family=task.family,
            budget_tier=self.budget_tier,
            cross_model_review=cross_model,
            attempt=attempt,
            promotion_decision=decision,
            gates=report,
            metric=metric,
            baseline_metric=baseline_metric,
            agent_outputs=outputs,
            escalations=escalations,
            triaged_in=triaged_in,
            next_actions=list(interp.output.follow_up_experiments),
        )

    def _decide_research(
        self,
        task: ResearchTask,
        code: str,
        *,
        triaged_in: bool,
        static_report: GateReport,
        metric: MetricRecord | None,
        baseline_metric: MetricRecord,
        safety: AgentResult,
        escalations: list[str],
    ) -> tuple[GateReport, GateDecision, str]:
        """Combine the objective metric gate with the cross-model safety review (Goal 09).

        Objective first, exactly as :meth:`_decide`: a triaged-out, gate-failing,
        non-reproducible, or non-improving candidate is rejected outright. A passing,
        improving, reproducible candidate that the Safety reviewer flags is **escalated**,
        not promoted — disagreement is a signal, not a tie-break.
        """
        if not triaged_in:
            return static_report, GateDecision.FAILED, "triaged out before execution (duplicate)"
        if static_report.failed:
            return static_report, GateDecision.FAILED, static_report.first_failure_reason()
        if metric is None or not metric.reproducible or not metric.passed:
            return (
                static_report,
                GateDecision.FAILED,
                "candidate did not produce a passing, reproducible metric",
            )
        improved, why = research_improves(metric, baseline_metric)
        if not improved:
            return static_report, GateDecision.FAILED, f"no improvement over baseline ({why})"

        repro = research_reproducibility_gate(task, code, self.sandbox)
        report = GateReport(results=[*static_report.results, repro])
        if report.failed:
            return report, GateDecision.FAILED, report.first_failure_reason()

        safety_block = (
            safety.output.escalate or safety.output.classification is SafetyClassification.UNSAFE
        )
        if safety_block:
            escalations.append(
                "cross-model disagreement: objective gate promotes but the Safety reviewer "
                f"flagged it ({safety.output.classification.value}, escalate="
                f"{safety.output.escalate}) — escalated for human review, not promoted"
            )
            return report, GateDecision.ESCALATED, (
                "escalated: safety reviewer disagreed with a gate-passing candidate"
            )
        return report, GateDecision.PASSED, "promoted: objective gate passed and safety review clear"

    def _write_research_memory(self, attempt: ResearchAttempt, mem: AgentResult) -> None:
        """Derive the typed entry (controller) and overlay only the curator's data fields."""
        entry = entry_from_research_attempt(attempt)
        entry = entry.model_copy(
            update={
                "strategy": mem.output.strategy or entry.strategy,
                "follow_up": mem.output.follow_up or entry.follow_up,
            }
        )
        self.memory.record_entry(entry)

    # --- decision logic -----------------------------------------------------
    def _decide(
        self,
        candidate: Candidate,
        task: LoadedTask,
        allowed_signatures,
        *,
        triaged_in: bool,
        static_report: GateReport,
        evaluation: EvaluationResult | None,
        baseline_eval: EvaluationResult | None,
        safety: AgentResult,
        escalations: list[str],
    ) -> tuple[GateReport, GateDecision, str]:
        """Combine the objective gate with the cross-model safety review into one decision.

        Objective first: a candidate that fails the static gates, isn't reproducible, or
        doesn't beat the baseline is rejected outright (the safety reviewer can't promote
        it). When the objective gate *would* promote but the safety reviewer disagrees, the
        result is **escalated**, not promoted — disagreement is a signal, not a tie-break.
        """
        if not triaged_in:
            return static_report, GateDecision.FAILED, "triaged out before execution (duplicate)"
        if static_report.failed:
            return static_report, GateDecision.FAILED, static_report.first_failure_reason()
        if evaluation is None or not evaluation.reproducible:
            return static_report, GateDecision.FAILED, "candidate did not run reproducibly"

        if baseline_eval is not None:
            improved, why = _improves(evaluation, baseline_eval)
            if not improved:
                return static_report, GateDecision.FAILED, f"no improvement over baseline ({why})"

        report = promotion_gate(
            candidate,
            task,
            self.sandbox,
            allowed_signatures=allowed_signatures,
            hidden_tests_path=task.hidden_tests_path,
        )
        if report.failed:
            return report, GateDecision.FAILED, report.first_failure_reason()

        safety_block = (
            safety.output.escalate
            or safety.output.classification is SafetyClassification.UNSAFE
        )
        if safety_block:
            escalations.append(
                "cross-model disagreement: objective gate promotes but the Safety reviewer "
                f"flagged it ({safety.output.classification.value}, escalate="
                f"{safety.output.escalate}) — escalated for human review, not promoted"
            )
            return report, GateDecision.ESCALATED, (
                "escalated: safety reviewer disagreed with a gate-passing candidate"
            )
        return report, GateDecision.PASSED, "promoted: objective gate passed and safety review clear"

    # --- context builders (everything below is data, never instructions) ----
    def _baseline_eval(self, task: LoadedTask) -> EvaluationResult | None:
        seed = Candidate(candidate_id="seed", task_id=task.task_id, code=task.seed_code)
        try:
            return evaluate(self.sandbox.run(seed, task), task.seed_code)
        except Exception:  # pragma: no cover - a broken seed shouldn't crash the cycle
            return None

    def _references_text(self) -> str:
        try:
            return Path(self.references_path).read_text(encoding="utf-8")[:2000]
        except OSError:
            return "(reference set unavailable)"

    def _bottlenecks(self, task_id: str) -> str:
        modes = self.memory.top_failure_modes(limit=3, task_id=task_id)
        if not modes:
            return "(no recorded bottlenecks yet)"
        return ", ".join(f"{sig} x{count}" for sig, count in modes)

    def _history_summary(self, task_id: str) -> str:
        entries = self.memory.all_entries()
        scoped = [e for e in entries if e.task_id == task_id]
        promoted = sum(1 for e in scoped if e.status is AttemptStatus.PROMOTED)
        return f"{len(scoped)} prior attempt(s) for {task_id}; {promoted} promoted."

    def _write_memory(self, attempt: Attempt, mem: AgentResult, interp: AgentResult) -> None:
        """Layer the curator's fields onto the unchanged MemoryEntry, then record it.

        The model never writes memory directly: the controller derives the typed entry and
        only *overlays* the curator's strategy/follow-up (data), preserving the schema and
        keeping negative results first-class.
        """
        entry = entry_from_attempt(attempt)
        follow_up = mem.output.follow_up or entry.follow_up
        entry = entry.model_copy(
            update={
                "strategy": mem.output.strategy or entry.strategy,
                "follow_up": follow_up,
            }
        )
        self.memory.record_entry(entry)


__all__ = ["Orchestrator", "CycleResult", "ResearchCycleResult"]
