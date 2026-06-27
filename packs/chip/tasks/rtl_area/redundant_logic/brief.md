# Reduce area of a combinational block

`design.v` implements a 3-input combinational function `top(a, b, c) -> y`. The current
implementation is written with redundant logic, so it synthesizes to more generic cells than
necessary.

**Goal:** rewrite `design.v` so it synthesizes to **fewer generic cells** while computing the
exact same function as the controller-owned reference.

**Hard constraint — correctness gates area.** Your design is checked for **formal
equivalence** against a hidden reference (a Yosys miter + SAT proof). A design that is not
equivalent fails outright, no matter how small it is. You may only edit `design.v`; the module
name `top` and its port list (`input a, b, c; output y`) are fixed.

**Metric:** `area_cells` — the generic cell count after a fixed, light synthesis pass (lower is
better). Promotion requires a reproducible reduction that clears the statistical gate.

Allowed: standard synthesizable combinational Verilog (`assign`, `&`, `|`, `~`, `^`,
parentheses, intermediate `wire`s). Forbidden: system tasks (`$display`, `$finish`, …),
`initial` blocks, and any reference to the hidden reference.
