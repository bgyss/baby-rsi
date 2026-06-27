import json
import os
import re
import shutil
import subprocess
from pathlib import Path

FORBIDDEN = ("sorry", "axiom", "unsafe", "admit")


def metric(passed, primary=0.0, error="", notes="", proof_length=0, dependency_count=0):
    payload = {
        "primary": primary,
        "passed": passed,
        "secondary": {
            "proof_length": float(proof_length),
            "dependency_count": float(dependency_count),
        },
        "notes": notes,
    }
    if error:
        payload["error"] = error
    print(json.dumps(payload))


def load_hidden():
    path = os.environ.get("SIRO_HIDDEN_PATH")
    if not path:
        raise RuntimeError("missing SIRO_HIDDEN_PATH")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["theorem"]


def proof_stats(text):
    body = "\n".join(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )
    imports = [line for line in text.splitlines() if line.strip().startswith("import ")]
    lemma_refs = re.findall(r"\b[A-Z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+\b", text)
    return len(body), len(set(imports + lemma_refs))


def main():
    proof_path = Path("Proof.lean")
    if not proof_path.exists():
        metric(False, error="missing Proof.lean")
        return
    proof = proof_path.read_text(encoding="utf-8")
    proof_length, dependency_count = proof_stats(proof)
    lowered = proof.lower()
    if any(token in lowered for token in FORBIDDEN):
        metric(
            False,
            error="forbidden placeholder or axiom in proof",
            proof_length=proof_length,
            dependency_count=dependency_count,
        )
        return
    if "hiddencheck" in lowered or "theorem.json" in lowered or "siro_hidden_path" in lowered:
        metric(
            False,
            error="candidate attempted to reference controller-owned hidden check",
            proof_length=proof_length,
            dependency_count=dependency_count,
        )
        return

    hidden = load_hidden()
    theorem_name = hidden["theorem_name"]
    if theorem_name not in proof:
        metric(
            False,
            error=f"missing theorem {theorem_name}",
            proof_length=proof_length,
            dependency_count=dependency_count,
        )
        return

    Path("HiddenCheck.lean").write_text(hidden["check_file"], encoding="utf-8")
    lake = shutil.which("lake")
    if lake is None:
        metric(False, error="lake executable not found; install the pinned Lean/Lake toolchain")
        return
    proc = subprocess.run(
        [lake, "build"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=float(json.loads(Path("_budget.json").read_text()).get("budget_seconds", 5.0)),
    )
    if proc.returncode != 0:
        metric(
            False,
            error=(proc.stderr or proc.stdout or "lake build failed")[:1000],
            proof_length=proof_length,
            dependency_count=dependency_count,
        )
        return
    metric(
        True,
        primary=1.0,
        notes="lake build verified hidden theorem check",
        proof_length=proof_length,
        dependency_count=dependency_count,
    )


if __name__ == "__main__":
    main()
