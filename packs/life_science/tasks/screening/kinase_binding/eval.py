"""Controller-owned offline screening evaluator for the kinase_binding task (Goal 27).

Regime B, in-silico screen. Reads the candidate `molecule.txt` (a space-separated list of
fragment tokens), then scores it with the pinned, offline surrogate delivered out-of-band via
SIRO_HIDDEN_PATH — a docking/affinity proxy plus an ADMET (logP) proxy and a synthesizability
cost. Predicted affinity is the primary metric (higher is better), but a candidate is credited
(`passed=True`) only if it is drug-like (logP within the window) AND synthesizable (cost under
the ceiling) AND well-formed (has a scaffold, sane token count). This makes "fast but wrong"
gaming — inflating affinity by stacking lipophilic/bulky groups — fail the precondition, so it
can never promote. No network, no file download, no real-world action: the only outside-world
step in this pack is the separate, governed, human-executed wet-lab confirmation.

The surrogate weights, thresholds, and held-out target are controller-owned (read only from
SIRO_HIDDEN_PATH, outside the candidate cwd). The candidate edits only `molecule.txt`.
"""

import json
import os
import re
from pathlib import Path

# Constructs a candidate must not use: any attempt to reach the controller-owned surrogate /
# held-out target, or to break out of the token vocabulary into code/file/network access.
FORBIDDEN = (
    "siro_hidden",
    "surrogate",
    "target",
    "import",
    "open(",
    "/",
    "\\",
    "$",
    "..",
)


def metric(passed, primary=0.0, error="", notes="", secondary=None):
    payload = {
        "primary": float(primary),
        "passed": bool(passed),
        "secondary": secondary or {},
        "notes": notes,
    }
    if error:
        payload["error"] = error
    print(json.dumps(payload))


def load_surrogate():
    path = os.environ.get("SIRO_HIDDEN_PATH")
    if not path:
        raise RuntimeError("missing SIRO_HIDDEN_PATH")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["surrogate"]


def parse_tokens(text):
    return [t for t in re.split(r"\s+", text.strip()) if t]


def score(tokens, weights, intercept=0.0):
    return intercept + sum(weights.get(t, 0.0) for t in tokens)


def main():
    mol_path = Path("molecule.txt")
    if not mol_path.exists():
        metric(False, error="missing molecule.txt")
        return
    raw = mol_path.read_text(encoding="utf-8")
    lowered = raw.lower()
    for token in FORBIDDEN:
        if token in lowered:
            metric(False, error=f"forbidden construct in molecule.txt: {token!r}")
            return

    tokens = parse_tokens(raw)
    surrogate = load_surrogate()
    vocab = set(surrogate["binding_weights"])
    unknown = [t for t in tokens if t not in vocab]
    if unknown:
        metric(False, error=f"unknown fragment token(s): {', '.join(sorted(set(unknown)))}")
        return

    thresholds = surrogate["thresholds"]
    n = len(tokens)
    if n < thresholds["min_tokens"]:
        metric(False, error=f"too few fragments ({n} < {thresholds['min_tokens']})")
        return
    if n > thresholds["max_tokens"]:
        metric(False, error=f"too many fragments ({n} > {thresholds['max_tokens']})")
        return
    if thresholds.get("require_scaffold", True) and "scaffold" not in tokens:
        metric(False, error="candidate has no core scaffold")
        return

    affinity = score(tokens, surrogate["binding_weights"], surrogate.get("intercept", 0.0))
    logp = score(tokens, surrogate["admet_logp"])
    synth = score(tokens, surrogate["synth_cost"])
    secondary = {"predicted_logp": float(logp), "synth_cost": float(synth)}

    # Drug-likeness and synthesizability are hard preconditions for any affinity credit.
    if not (thresholds["min_logp"] <= logp <= thresholds["max_logp"]):
        metric(
            False,
            primary=affinity,
            error=f"not drug-like: predicted logP {logp:g} outside "
            f"[{thresholds['min_logp']}, {thresholds['max_logp']}]",
            secondary=secondary,
        )
        return
    if synth > thresholds["max_synth_cost"]:
        metric(
            False,
            primary=affinity,
            error=f"not synthesizable: cost {synth:g} > {thresholds['max_synth_cost']}",
            secondary=secondary,
        )
        return

    metric(
        True,
        primary=affinity,
        notes=f"drug-like, synthesizable; predicted affinity {affinity:g} "
        f"(logP {logp:g}, synth cost {synth:g})",
        secondary=secondary,
    )


if __name__ == "__main__":
    main()
