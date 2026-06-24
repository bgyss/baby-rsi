"""Prompt loading — role/template text lives as data under ``prompts/``.

Keeping prompts as files (not inline strings) makes them an explicit, auditable,
self-improvable surface: the meta-research loop (Goal 05) proposes revisions to
these templates under the gates.
"""

from __future__ import annotations

from pathlib import Path

#: Repository ``prompts/`` directory (role templates).
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(name: str, prompts_dir: Path | None = None) -> str:
    """Load a prompt template by name (with or without a ``.md`` suffix)."""
    base = prompts_dir or PROMPTS_DIR
    filename = name if name.endswith(".md") else f"{name}.md"
    path = base / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


__all__ = ["PROMPTS_DIR", "load_prompt"]
