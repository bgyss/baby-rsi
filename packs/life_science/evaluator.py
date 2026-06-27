"""Two-stage evaluator adapter for the drug/life-science pack (Goal 27).

The pack combines both new regimes on one workflow, so its adapter *dispatches per task* on the
task's declared regime (set in ``task.json``; controller-owned, candidate cannot move it):

- **Screening (Regime B, ``statistical``).** Routed to the default :class:`EvalPyAdapter`, which
  runs the task's controller-owned offline ``eval.py`` — pinned surrogate docking / ADMET /
  synthesizability proxies against fixtures handed in via ``SIRO_HIDDEN_PATH``. Promotion is
  governed by the Goal 24 confidence-bound gate.
- **Confirmation (Regime C, ``external-oracle``).** Routed to the Goal 26
  :class:`ExternalOracleAdapter`, which runs **no candidate code** and touches no instrument or
  network — it scores only on an ingested, approved, signed wet-lab assay result. A candidate
  with no live, matching, signed result cannot promote (default-deny "awaiting").

The pack-level regime declared in ``pack.toml`` is ``statistical`` (the inner-loop screen); the
dispatcher carries that as its own ``regime`` to satisfy the Goal 22 manifest/adapter check, and
selects the confirmation adapter only for tasks that override their regime to ``external-oracle``.
"""

from siro.external import ExternalOracleAdapter
from siro.packs import EvalPyAdapter, EvaluatorRegime


class LifeScienceAdapter:
    """Route each life-science task to the screening or confirmation adapter by its regime."""

    def __init__(self, regime: EvaluatorRegime = EvaluatorRegime.STATISTICAL) -> None:
        self.regime = regime
        self._screen = EvalPyAdapter(regime=EvaluatorRegime.STATISTICAL)
        self._confirm = ExternalOracleAdapter()

    def evaluate(self, task, candidate_code, sandbox, *, seed=None):
        if task.evaluator_regime is EvaluatorRegime.EXTERNAL_ORACLE:
            # Confirmation: score on the ingested, approved, signed assay result. The execution
            # plane (``sandbox``) is never used — no synthesis or assay runs here.
            return self._confirm.evaluate(task, candidate_code, sandbox, seed=seed)
        # Screening: run the offline surrogate eval.py under the statistical regime.
        return self._screen.evaluate(task, candidate_code, sandbox, seed=seed)


def get_adapter(regime: EvaluatorRegime) -> LifeScienceAdapter:
    """Return the dispatching adapter; ``regime`` is the pack's declared default (statistical)."""
    return LifeScienceAdapter(regime)
