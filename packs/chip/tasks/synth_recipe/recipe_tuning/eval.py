"""Controller-owned EDA evaluator for the synth_recipe / recipe_tuning task (Goal 25).

The candidate edits only `recipe.txt`: an ordered list of Yosys optimization passes applied to
a fixed, read-only `circuit.v`. The evaluator validates every pass against an allowlist (no
read/write/exec/script commands), applies the recipe, proves the optimized result is formally
equivalent to the controller-owned reference (correctness is a hard precondition), and reports
the generic cell count as the area metric. A recipe that breaks equivalence — or that smuggles
in a non-optimization command — fails outright.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

TOP = "top"

# First token of each recipe line must be one of these Yosys optimization passes. Everything
# else (read_*, write_*, tee, exec, script, shell `!`, command chaining) is rejected so the
# candidate can only *optimize*, never reach the filesystem or the reference.
ALLOWED_PASSES = frozenset(
    {
        "opt",
        "opt_expr",
        "opt_clean",
        "opt_merge",
        "opt_reduce",
        "clean",
        "flatten",
        "share",
        "wreduce",
        "peepopt",
        "memory_opt",
        "techmap",
        "abc",
        "simplemap",
    }
)
FORBIDDEN_SUBSTRINGS = (";", "read", "write", "tee", "exec", "script", "!", "<", ">", "design", "$", "`")


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


def budget_seconds(default=20.0):
    try:
        return float(json.loads(Path("_budget.json").read_text()).get("budget_seconds", default))
    except (OSError, ValueError):
        return default


def load_reference():
    path = os.environ.get("SIRO_HIDDEN_PATH")
    if not path:
        raise RuntimeError("missing SIRO_HIDDEN_PATH")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["reference"]


def parse_recipe(text):
    """Return (passes, error). Each accepted line is a validated Yosys optimization command."""
    passes = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        for bad in FORBIDDEN_SUBSTRINGS:
            if bad in low:
                return None, f"forbidden token {bad!r} in recipe line: {line!r}"
        command = low.split()[0]
        if command not in ALLOWED_PASSES:
            return None, f"pass {command!r} is not in the allowed optimization set"
        passes.append(line)
    if not passes:
        return None, "recipe is empty"
    return passes, ""


def run_yosys(script, timeout):
    yosys = shutil.which("yosys")
    if yosys is None:
        return None
    return subprocess.run(
        [yosys, "-p", script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def equivalence_script(recipe):
    body = "; ".join(recipe)
    return (
        f"read_verilog -sv golden.v; hierarchy -top {TOP}; proc; flatten; opt -fast; "
        f"rename {TOP} gold; design -stash gold; "
        f"read_verilog -sv circuit.v; hierarchy -top {TOP}; proc; {body}; flatten; "
        f"rename {TOP} gate; design -copy-from gold -as gold gold; "
        "miter -equiv -flatten -make_assert gold gate miter; hierarchy -top miter; "
        "sat -verify -prove-asserts miter"
    )


def area_script(recipe):
    body = "; ".join(recipe)
    return (
        f"read_verilog -sv circuit.v; hierarchy -top {TOP}; proc; {body}; "
        "splitnets -ports; simplemap; opt_clean; stat"
    )


def parse_cells(stdout):
    matches = re.findall(r"Number of cells:\s+(\d+)", stdout)
    if not matches:
        matches = re.findall(r"(?m)^\s*(\d+)\s+cells\b", stdout)
    return int(matches[-1]) if matches else None


def main():
    recipe_path = Path("recipe.txt")
    circuit_path = Path("circuit.v")
    if not recipe_path.exists() or not circuit_path.exists():
        metric(False, error="missing recipe.txt or circuit.v")
        return
    passes, err = parse_recipe(recipe_path.read_text(encoding="utf-8"))
    if err:
        metric(False, error=err)
        return

    reference = load_reference()
    Path("golden.v").write_text(reference["golden"], encoding="utf-8")
    timeout = budget_seconds()

    equiv = run_yosys(equivalence_script(passes), timeout)
    if equiv is None:
        metric(False, error="yosys executable not found; provision the pinned EDA toolchain")
        return
    if equiv.returncode != 0:
        last = equiv.stdout.strip().splitlines()[-1] if equiv.stdout.strip() else "miter failed"
        metric(False, error="recipe changed behavior (not equivalent to reference): " + last)
        return

    area = run_yosys(area_script(passes), timeout)
    if area is None or area.returncode != 0:
        detail = (area.stderr or area.stdout or "synthesis failed") if area else "yosys missing"
        metric(False, error="synthesis failed: " + detail.strip()[:400])
        return
    cells = parse_cells(area.stdout)
    if cells is None:
        metric(False, error="could not parse cell count from synthesis stat")
        return

    metric(
        True,
        primary=cells,
        notes=f"recipe of {len(passes)} pass(es) kept equivalence; {cells} generic cells",
        secondary={"area_cells": float(cells), "recipe_length": float(len(passes))},
    )


if __name__ == "__main__":
    main()
