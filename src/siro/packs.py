"""Domain-pack registry and evaluator adapters (Goal 22).

A pack is the reviewable unit for domain-specific research content: task families,
controller-owned evaluator, optional prompts/references, and a narrowed tool whitelist.
Selecting a pack is config, not code. The built-in ``ml`` pack reseats the existing
research benchmark suite without changing evaluator behavior.
"""

from __future__ import annotations

import importlib.util
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field, field_validator

from .schemas import MetricRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .research import ResearchTask
    from .sandbox import Sandbox

PACKS_ROOT = Path("packs")
DEFAULT_PACK_ID = "ml"
GLOBAL_CONTROL_PLANE_TOOLS = frozenset(
    {"read_allowed_file", "query_memory", "list_references", "propose_patch"}
)


class EvaluatorRegime(StrEnum):
    """Reproducibility policy a pack's evaluator requires."""

    EXACT = "exact"
    SEEDED_DETERMINISTIC = "seeded-deterministic"
    STATISTICAL = "statistical"


class PackError(ValueError):
    """Raised when a pack is unknown, malformed, or widens a bound."""


class EvaluatorAdapter(Protocol):
    """Typed scoring contract for a domain pack.

    The adapter receives a loaded task, the candidate's edited surface, and the existing
    offline sandbox. It returns the same :class:`MetricRecord` the research harness has
    always promoted on.
    """

    regime: EvaluatorRegime

    def evaluate(
        self,
        task: "ResearchTask",
        candidate_code: str,
        sandbox: "Sandbox",
        *,
        seed: int | None = None,
    ) -> MetricRecord:
        """Score ``candidate_code`` against ``task`` inside ``sandbox``.

        ``seed`` is supplied only by the ``statistical`` regime's replicate harness (Goal 24);
        a deterministic adapter ignores it and a stochastic ``eval.py`` reads it from the
        controller-set ``SIRO_EVAL_SEED`` env var.
        """


@dataclass(frozen=True)
class EvalPyAdapter:
    """Default adapter: run the task's controller-owned ``eval.py`` unchanged."""

    regime: EvaluatorRegime = EvaluatorRegime.SEEDED_DETERMINISTIC

    def evaluate(
        self,
        task: "ResearchTask",
        candidate_code: str,
        sandbox: "Sandbox",
        *,
        seed: int | None = None,
    ) -> MetricRecord:
        from .research import _run_eval_py

        return _run_eval_py(task, candidate_code, sandbox, seed=seed)


class PackManifest(BaseModel):
    """Validated ``pack.toml`` fields."""

    id: str
    title: str
    version: str
    evaluator_regime: EvaluatorRegime = Field(alias="evaluator_regime")
    required_tools: list[str] = Field(default_factory=list)
    tier_floor: int = 0

    @field_validator("id")
    @classmethod
    def _id_is_path_safe(cls, value: str) -> str:
        if not value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("pack id must be a simple path-safe name")
        return value

    @field_validator("tier_floor")
    @classmethod
    def _tier_floor_is_nonnegative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("tier_floor must be non-negative")
        return value


@dataclass(frozen=True)
class DomainPack:
    """A loaded, validated domain pack."""

    manifest: PackManifest
    root: Path
    tasks_dir: Path
    prompts_dir: Path | None = None
    references_dir: Path | None = None
    tools: frozenset[str] = field(default_factory=frozenset)
    adapter: EvaluatorAdapter = field(default_factory=EvalPyAdapter)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def regime(self) -> EvaluatorRegime:
        return self.adapter.regime


def _read_tools_allow(path: Path) -> frozenset[str]:
    if not path.exists():
        return GLOBAL_CONTROL_PLANE_TOOLS
    tools = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    unknown = tools - GLOBAL_CONTROL_PLANE_TOOLS
    if unknown:
        raise PackError(
            "Pack tool whitelist may only narrow the global control-plane tools; "
            f"unknown tool(s): {', '.join(sorted(unknown))}"
        )
    return frozenset(tools)


def _validate_tool_subset(tools: set[str], *, label: str) -> None:
    unknown = tools - GLOBAL_CONTROL_PLANE_TOOLS
    if unknown:
        raise PackError(
            f"{label} may only reference global control-plane tools; "
            f"unknown tool(s): {', '.join(sorted(unknown))}"
        )


def _load_adapter(path: Path, regime: EvaluatorRegime) -> EvaluatorAdapter:
    """Load the controller-owned adapter from ``evaluator.py`` and validate its shape."""
    module_name = f"_siro_pack_{path.parent.name}_evaluator"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PackError(f"Pack evaluator {path} cannot be imported.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PackError(f"Pack evaluator {path} failed to import: {exc}") from exc

    if hasattr(module, "get_adapter"):
        adapter = module.get_adapter(regime)
    elif hasattr(module, "ADAPTER"):
        adapter = module.ADAPTER
    else:
        raise PackError(
            f"Pack evaluator {path} must define get_adapter(regime) or ADAPTER."
        )

    adapter_regime = getattr(adapter, "regime", None)
    if not isinstance(adapter_regime, EvaluatorRegime):
        try:
            adapter_regime = EvaluatorRegime(str(adapter_regime))
        except ValueError as exc:
            raise PackError(f"Pack evaluator {path} declares invalid regime {adapter_regime!r}.") from exc
    if adapter_regime is not regime:
        raise PackError(
            f"Pack evaluator {path} regime {adapter_regime.value!r} does not match "
            f"pack.toml evaluator_regime {regime.value!r}."
        )
    if not callable(getattr(adapter, "evaluate", None)):
        raise PackError(f"Pack evaluator {path} does not provide an evaluate method.")
    return adapter


def _load_manifest(path: Path) -> PackManifest:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackError(f"Pack manifest {path} is not readable: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PackError(f"Pack manifest {path} is malformed TOML: {exc}") from exc
    try:
        return PackManifest.model_validate(data)
    except Exception as exc:
        raise PackError(f"Pack manifest {path} is invalid: {exc}") from exc


def load_pack(pack_id: str = DEFAULT_PACK_ID, *, root: str | Path = PACKS_ROOT) -> DomainPack:
    """Discover and validate a domain pack by id.

    Unknown or malformed packs fail closed. A pack can narrow the agent toolset via
    ``tools.allow`` but cannot grant tools outside the global control-plane set.
    """
    if not pack_id or "/" in pack_id or "\\" in pack_id or pack_id in {".", ".."}:
        raise PackError(f"Invalid pack id {pack_id!r}.")
    base = Path(root) / pack_id
    if not base.is_dir():
        raise PackError(f"Unknown domain pack {pack_id!r} under {Path(root)}.")
    manifest = _load_manifest(base / "pack.toml")
    if manifest.id != pack_id:
        raise PackError(
            f"Pack manifest id {manifest.id!r} does not match requested id {pack_id!r}."
        )
    tasks_dir = base / "tasks"
    evaluator_path = base / "evaluator.py"
    if not tasks_dir.is_dir():
        raise PackError(f"Pack {pack_id!r} is missing tasks/.")
    if not evaluator_path.exists():
        raise PackError(f"Pack {pack_id!r} is missing evaluator.py.")

    _validate_tool_subset(set(manifest.required_tools), label="Pack required_tools")
    tools = _read_tools_allow(base / "tools.allow")
    adapter = _load_adapter(evaluator_path, manifest.evaluator_regime)
    return DomainPack(
        manifest=manifest,
        root=base,
        tasks_dir=tasks_dir,
        prompts_dir=(base / "prompts") if (base / "prompts").is_dir() else None,
        references_dir=(base / "references") if (base / "references").is_dir() else None,
        tools=tools,
        adapter=adapter,
    )


__all__ = [
    "DEFAULT_PACK_ID",
    "PACKS_ROOT",
    "GLOBAL_CONTROL_PLANE_TOOLS",
    "EvaluatorRegime",
    "PackError",
    "EvaluatorAdapter",
    "EvalPyAdapter",
    "PackManifest",
    "DomainPack",
    "load_pack",
]
