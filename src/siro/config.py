"""Runtime config — the *only* place tier and provider selection live (Goal 07).

A tier is a deployment posture chosen by config, not code: ``config/tier0.local.yaml``
binds every role to the local model; ``config/tier1.frontier.yaml`` binds roles to
Claude/GPT. Loading a different file is the whole act of changing tier — the controller,
evaluator, sandbox, gates, and memory are untouched, and **lowering the tier back to 0
requires no code change** (``docs/07_model_providers_and_tiers.md``).

This module reads the ``providers``, ``agent_models``, ``budget``, and ``network``
blocks, resolves API keys from the environment (control plane only), and hands back
ready-to-use :class:`ModelClient` instances and a :class:`BudgetLimits`. It never lets a
credential reach the execution plane and never makes a network call itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .budget import BudgetLimits
from .providers import ModelClient, ProviderConfig, build_client
from .providers._http import Transport

#: Default config file (Tier 0, fully local) — the safe default posture.
DEFAULT_CONFIG_PATH = Path("config/tier0.local.yaml")

#: The role the single Tier 0 code-improver agent maps to. At Tier 1 this is the
#: Implementation Agent; ``agent_models`` may also carry a ``default`` fallback.
DEFAULT_ROLE = "implementation"


@dataclass
class SiroConfig:
    """Parsed runtime configuration. Pure data + client factory; holds no live socket."""

    tier: int
    providers: dict[str, ProviderConfig]
    agent_models: dict[str, str]
    budget: BudgetLimits
    allowed_endpoints: list[str] | None
    path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # --- role binding -------------------------------------------------------
    def provider_for_role(self, role: str) -> ProviderConfig:
        """Resolve a role to its provider config: role → ``default`` → sole/local."""
        name = self.agent_models.get(role) or self.agent_models.get("default")
        if name is None:
            if "local" in self.providers:
                name = "local"
            elif len(self.providers) == 1:
                name = next(iter(self.providers))
            else:
                raise KeyError(
                    f"No provider bound for role {role!r} and no 'default' in agent_models."
                )
        if name not in self.providers:
            raise KeyError(f"agent_models binds role {role!r} to unknown provider {name!r}.")
        return self.providers[name]

    def client_for_role(
        self, role: str = DEFAULT_ROLE, *, transport: Transport | None = None
    ) -> ModelClient:
        """Build the :class:`ModelClient` bound to ``role`` under the active tier."""
        return build_client(
            self.provider_for_role(role),
            allowed_endpoints=self.allowed_endpoints,
            transport=transport,
        )

    def client_factory(self, role: str = DEFAULT_ROLE, *, transport: Transport | None = None):
        """A zero-arg factory (fresh client per call) for the A/B meta-loop."""
        return lambda: self.client_for_role(role, transport=transport)


def load_config(path: str | Path | None = None) -> SiroConfig:
    """Load and parse a tier config file into a :class:`SiroConfig`."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    providers = {
        key: ProviderConfig.from_block(key, block or {})
        for key, block in (raw.get("providers") or {}).items()
    }
    agent_models = {str(k): str(v) for k, v in (raw.get("agent_models") or {}).items()}

    network = raw.get("network") or {}
    allowed_endpoints: list[str] | None = None
    if network.get("egress") == "allowlist":
        allowed_endpoints = [str(e) for e in (network.get("allowed_endpoints") or [])]

    return SiroConfig(
        tier=int(raw.get("tier", 0)),
        providers=providers,
        agent_models=agent_models,
        budget=BudgetLimits.from_config(raw.get("budget")),
        allowed_endpoints=allowed_endpoints,
        path=config_path,
        raw=raw,
    )


__all__ = ["SiroConfig", "load_config", "DEFAULT_CONFIG_PATH", "DEFAULT_ROLE"]
