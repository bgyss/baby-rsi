"""Controller-owned EDA evaluator for the rtl_area / redundant_logic task (Goal 25).

Offline Yosys flow: prove the candidate `design.v` is formally equivalent to the hidden
reference (a miter + SAT proof — correctness is a hard precondition), then synthesize it under
a fixed, light pass and report the generic cell count as the area metric. A design that is not
equivalent fails outright, so a smaller-but-wrong design can never win. The reference is
controller-owned (delivered via SIRO_HIDDEN_PATH, outside the candidate cwd); the candidate
edits only `design.v`.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# Constructs a candidate must not use: simulation/system tasks, and any attempt to reach the
# controller-owned reference. (The static safety gate cannot parse Verilog, so the evaluator
# enforces this directly.)
FORBIDDEN = (
    "$display",
    "$finish",
    "$dumpfile",
    "$readmem",
    "$fopen",
    "initial",
    "golden",
    "reference.json",
    "siro_hidden",
)

TOP = "top"


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


def equivalence_script():
    return (
        f"read_verilog -sv golden.v; hierarchy -top {TOP}; proc; flatten; opt -fast; "
        f"rename {TOP} gold; design -stash gold; "
        f"read_verilog -sv design.v; hierarchy -top {TOP}; proc; flatten; opt -fast; "
        f"rename {TOP} gate; design -copy-from gold -as gold gold; "
        "miter -equiv -flatten -make_assert gold gate miter; hierarchy -top miter; "
        "sat -verify -prove-asserts -show-inputs miter"
    )


def area_script():
    return (
        f"read_verilog -sv design.v; hierarchy -top {TOP}; proc; opt_expr; opt_clean; "
        "splitnets -ports; simplemap; opt_clean; stat"
    )


def parse_cells(stdout):
    # Yosys `stat` prints either "Number of cells: N" (older) or "N cells" (newer); accept both
    # and take the last occurrence (the synthesized top module's block).
    matches = re.findall(r"Number of cells:\s+(\d+)", stdout)
    if not matches:
        matches = re.findall(r"(?m)^\s*(\d+)\s+cells\b", stdout)
    if not matches:
        return None
    return int(matches[-1])


def main():
    design_path = Path("design.v")
    if not design_path.exists():
        metric(False, error="missing design.v")
        return
    design = design_path.read_text(encoding="utf-8")
    lowered = design.lower()
    for token in FORBIDDEN:
        if token in lowered:
            metric(False, error=f"forbidden construct in design.v: {token}")
            return

    reference = load_reference()
    Path("golden.v").write_text(reference["golden"], encoding="utf-8")
    timeout = budget_seconds()

    equiv = run_yosys(equivalence_script(), timeout)
    if equiv is None:
        metric(False, error="yosys executable not found; provision the pinned EDA toolchain")
        return
    if equiv.returncode != 0:
        metric(
            False,
            error="not formally equivalent to the reference: "
            + (equiv.stdout.strip().splitlines()[-1] if equiv.stdout.strip() else "miter failed"),
        )
        return

    area = run_yosys(area_script(), timeout)
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
        notes=f"equivalent to reference; {cells} generic cells after light synthesis",
        secondary={"area_cells": float(cells)},
    )


if __name__ == "__main__":
    main()
