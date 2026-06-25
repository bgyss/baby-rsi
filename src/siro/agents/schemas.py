"""Typed input/output contracts for the frontier organization's agents (Goal 08).

Every role from ``docs/03_agent_roles.md`` declares a typed **input contract** (what the
orchestrator hands it) and a Pydantic **output_schema** (what it must return, enforced via
structured output). These are the contract the orchestrator validates *before* anything
executes — an agent emits a structured proposal, never an action.

Kept apart from :mod:`siro.schemas` (the persistence substrate) because these are the
agent *interface*, not the loop's archived records. The orchestrator translates the
relevant agent outputs into the unchanged :class:`~siro.schemas.Attempt` /
:class:`~siro.schemas.MemoryEntry` records (Goal 08 constraint: reuse the lifecycle, gates,
evaluator, and memory schema unchanged — only the agents behind the roles get more capable).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Hypothesis Agent — falsifiable idea with a predicted result + expected failure.
# --------------------------------------------------------------------------- #


class HypothesisInput(BaseModel):
    """What the Hypothesis Agent reasons over (``docs/03`` inputs)."""

    objective: str
    task_prompt: str
    prior_results: str = ""
    memory_summaries: str = ""
    known_bottlenecks: str = ""


class HypothesisOutput(BaseModel):
    """A falsifiable idea plus the prediction that makes it testable."""

    statement: str
    expected_mechanism: str = ""
    proposed_experiment: str = ""
    required_metrics: list[str] = Field(default_factory=list)
    predicted_result: str = ""
    expected_failure: str = ""
    risk_notes: str = ""


# --------------------------------------------------------------------------- #
# Literature Agent — ground + dedupe against references and memory.
# --------------------------------------------------------------------------- #


class Novelty(str, Enum):
    NOVEL = "novel"
    INCREMENTAL = "incremental"
    DUPLICATE = "duplicate"


class LiteratureInput(BaseModel):
    hypothesis: str
    references: str = ""
    prior_summaries: str = ""


class LiteratureOutput(BaseModel):
    """Prior-art grounding + a duplicate/novelty assessment (triage input)."""

    prior_art: str = ""
    related_work: list[str] = Field(default_factory=list)
    novelty: Novelty = Novelty.NOVEL
    is_duplicate: bool = False
    refinements: str = ""
    caveats: str = ""


# --------------------------------------------------------------------------- #
# Implementation Agent — a patch limited to allowed edit surfaces.
# --------------------------------------------------------------------------- #


class ImplementationInput(BaseModel):
    experiment_plan: str
    allowed_edit_surfaces: list[str] = Field(default_factory=list)
    baseline_code: str = ""
    module_name: str = ""
    test_requirements: str = ""
    memory_lessons: str = ""


class ImplementationOutput(BaseModel):
    """A code patch (full replacement module) plus notes. Code is *data* until gated."""

    code: str
    implementation_notes: str = ""
    expected_impact: str = ""
    known_risks: str = ""


# --------------------------------------------------------------------------- #
# Evaluation Agent — a regression narrative over the *objective* metrics.
# --------------------------------------------------------------------------- #


class EvaluationInput(BaseModel):
    baseline_metrics: str
    candidate_metrics: str
    regression_thresholds: str = ""


class EvaluationOutput(BaseModel):
    """A narrative over objective deltas. The objective evaluator stays authoritative."""

    pass_fail: bool = False
    metric_deltas: str = ""
    regression_report: str = ""
    suggested_follow_up: str = ""


# --------------------------------------------------------------------------- #
# Safety Agent — cross-model review (different provider than Implementation).
# --------------------------------------------------------------------------- #


class SafetyClassification(str, Enum):
    SAFE = "safe"
    NEEDS_MITIGATION = "needs_mitigation"
    UNSAFE = "unsafe"


class SafetyInput(BaseModel):
    code_diff: str
    tool_permissions: list[str] = Field(default_factory=list)
    logs: str = ""
    agent_outputs: str = ""
    eval_results: str = ""


class SafetyOutput(BaseModel):
    """Safety classification + escalation recommendation (a review, never an approval)."""

    classification: SafetyClassification = SafetyClassification.SAFE
    risk_notes: str = ""
    required_mitigations: list[str] = Field(default_factory=list)
    escalate: bool = False


# --------------------------------------------------------------------------- #
# Interpretation Agent — explain the result, draft a memory entry.
# --------------------------------------------------------------------------- #


class InterpretationInput(BaseModel):
    hypothesis: str
    experiment_plan: str
    metrics: str
    logs: str = ""
    failure_report: str = ""


class InterpretationOutput(BaseModel):
    """A research-quality interpretation + an honest confidence + a memory draft."""

    result_summary: str
    likely_explanation: str = ""
    confidence: float = 0.5
    follow_up_experiments: list[str] = Field(default_factory=list)
    memory_entry_draft: str = ""


# --------------------------------------------------------------------------- #
# Memory Curator Agent — structured record + retrieval tags.
# --------------------------------------------------------------------------- #


class MemoryCuratorInput(BaseModel):
    experiment_record: str
    interpretation: str
    metadata: str = ""


class MemoryCuratorOutput(BaseModel):
    """The curated fields layered onto the unchanged :class:`~siro.schemas.MemoryEntry`."""

    strategy: str = ""
    lessons_learned: list[str] = Field(default_factory=list)
    retrieval_tags: list[str] = Field(default_factory=list)
    follow_up: str = ""


# --------------------------------------------------------------------------- #
# Meta-Research Agent — propose a process change (proposal only, human-gated).
# --------------------------------------------------------------------------- #


class MetaResearchInput(BaseModel):
    experiment_history: str
    agent_performance: str = ""
    failure_modes: str = ""
    bottleneck_report: str = ""


class MetaResearchOutput(BaseModel):
    """A proposed process change + rollback. Never applied by the loop (human-gated)."""

    proposed_change: str
    target: str = ""
    expected_benefit: str = ""
    validation_experiment: str = ""
    rollback_plan: str = ""


__all__ = [
    "HypothesisInput",
    "HypothesisOutput",
    "Novelty",
    "LiteratureInput",
    "LiteratureOutput",
    "ImplementationInput",
    "ImplementationOutput",
    "EvaluationInput",
    "EvaluationOutput",
    "SafetyClassification",
    "SafetyInput",
    "SafetyOutput",
    "InterpretationInput",
    "InterpretationOutput",
    "MemoryCuratorInput",
    "MemoryCuratorOutput",
    "MetaResearchInput",
    "MetaResearchOutput",
]
