# Tune a synthesis recipe for a fixed design

`circuit.v` is a **fixed, read-only** combinational design with redundant logic. You cannot
edit it. You edit only `recipe.txt`: a newline-separated, ordered list of Yosys optimization
passes applied to the design before it is mapped to generic cells and measured.

**Goal:** choose a recipe that synthesizes `circuit.v` to **fewer generic cells**.

**Hard constraint — correctness gates area.** After your recipe runs, the result is checked
for **formal equivalence** against the controller-owned reference (the original function). A
recipe that changes behavior fails outright.

**Metric:** `area_cells` — generic cell count after your recipe plus a fixed final mapping
(lower is better). Promotion requires a reproducible reduction that clears the statistical gate.

Allowed passes (one per line, optionally with flags): `opt`, `opt -full`, `opt_expr`,
`opt_clean`, `opt_merge`, `opt_reduce`, `clean`, `flatten`, `share`, `wreduce`, `peepopt`,
`memory_opt`, `techmap`, `abc`, `abc -g AND,OR`, `abc -g AND,OR,XOR,NAND,NOR,XNOR`. Anything
else (any `read_*`/`write_*`/`tee`/`exec`/`script`/`!`/shell command) is rejected.
