"""siro — bounded, auditable self-improving research organization testbed.

This package implements the system described under ``docs/``. Goal 01 lays the
scaffold: explicit schemas, a JSONL archive, plane-isolation safety primitives,
and a CLI surface. Later goals fill the loop (``controller``/``sandbox``/
``evaluator``), research memory, gates, and the provider abstraction.

The package is provider-agnostic and, at Tier 0, fully local/offline. Nothing
here reaches the network.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
