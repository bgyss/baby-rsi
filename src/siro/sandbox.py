"""Execution plane — isolated candidate/test execution.

Goal 01 establishes the isolation *contract* and a config object; Goal 02 wires the
actual test run. Even as a stub, the rule is fixed: candidate code runs in a temp
dir, with a hard subprocess timeout, no network, and an environment scrubbed of
credentials (``docs/05_evaluation_and_safety_gates.md``).

The controller — never a model — decides what fixed command runs here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .safety import scrub_execution_env


@dataclass(frozen=True)
class SandboxConfig:
    """Execution-plane limits. ``network`` is always disabled in the execution plane."""

    timeout_seconds: float = 10.0
    network: str = "disabled"
    max_output_bytes: int = 1_000_000


class Sandbox:
    """Isolated runner for candidate code. Goal 01 provides the safety surface."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()

    def child_env(self) -> dict[str, str]:
        """Environment for a candidate subprocess: credentials scrubbed."""
        return scrub_execution_env()

    def run(self, candidate, task) -> None:  # noqa: ANN001, ARG002 - stub for Goal 02
        """Run a candidate's tests in isolation and return an EvaluationResult.

        Implemented in Goal 02. The signature is reserved here so the controller
        and tests can be written against a stable surface.
        """
        raise NotImplementedError("Sandbox.run is implemented in Goal 02.")


__all__ = ["SandboxConfig", "Sandbox"]
