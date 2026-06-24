"""Safety primitives — plane isolation and the bounds on self-improvement.

These are the guardrails that keep self-improvement *bounded*
(``docs/05_evaluation_and_safety_gates.md``, ``docs/13_self_improvement_loop.md``).
Goal 01 implements the load-bearing, cheaply-testable pieces:

- network is off in the execution plane by default,
- credentials are scrubbed from any environment handed to candidate code.

The full promotion gate (metric improvement + no regression + reproducibility +
edit-constraint checks) is built in Goal 04.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: Environment variable names that must never enter the execution plane.
CREDENTIAL_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "GOOGLE_API_KEY",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    }
)


def network_allowed() -> bool:
    """Whether control-plane network egress is permitted (off by default at Tier 0).

    Driven by the ``SIRO_ALLOW_NETWORK`` env var (set ``false`` in ``mise.toml``).
    The *execution* plane is offline regardless of this flag.
    """
    return os.environ.get("SIRO_ALLOW_NETWORK", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def scrub_execution_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``env`` with all known credentials removed.

    This is what gets handed to candidate/test subprocesses: no API keys, no
    secrets — ever.
    """
    source = os.environ if env is None else env
    return {k: v for k, v in source.items() if k not in CREDENTIAL_ENV_KEYS}


def assert_execution_plane_isolated(env: Mapping[str, str] | None = None) -> None:
    """Raise if an environment intended for the execution plane carries credentials."""
    source = os.environ if env is None else env
    leaked = sorted(k for k in source if k in CREDENTIAL_ENV_KEYS)
    if leaked:
        raise PermissionError(
            f"Execution plane must not contain credentials; found: {', '.join(leaked)}"
        )


__all__ = [
    "CREDENTIAL_ENV_KEYS",
    "network_allowed",
    "scrub_execution_env",
    "assert_execution_plane_isolated",
]
