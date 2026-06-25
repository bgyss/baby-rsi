"""Agents package — the model-backed roles of the Tier 1 research organization (Goal 08).

Each role from ``docs/03_agent_roles.md`` is an :class:`~siro.agents.base.Agent`: a role
system prompt, a typed input contract + Pydantic ``output_schema`` (structured output), a
constrained control-plane toolbox, and explicit forbidden actions. Roles bind to providers
purely by config (:func:`build_agents`), so the same organization runs local (Tier 0) or
frontier (Tier 1) with no code change.
"""

from __future__ import annotations

from .base import INJECTION_GUARD, Agent, AgentResult
from .roles import (
    EVALUATION,
    HYPOTHESIS,
    IMPLEMENTATION,
    INTERPRETATION,
    LITERATURE,
    MEMORY,
    META_RESEARCH,
    MODEL_ROLES,
    ROLE_SPECS,
    SAFETY,
    RoleSpec,
    build_agent,
    build_agents,
)

__all__ = [
    "Agent",
    "AgentResult",
    "INJECTION_GUARD",
    "RoleSpec",
    "ROLE_SPECS",
    "MODEL_ROLES",
    "HYPOTHESIS",
    "LITERATURE",
    "IMPLEMENTATION",
    "EVALUATION",
    "SAFETY",
    "INTERPRETATION",
    "MEMORY",
    "META_RESEARCH",
    "build_agent",
    "build_agents",
]
