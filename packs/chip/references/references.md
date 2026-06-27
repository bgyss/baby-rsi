# Chip Pack References

Pinned, offline Yosys-based vocabulary for the initial chip tasks. The evaluator runs fully
offline under a hard timeout; correctness (formal equivalence to a controller-owned reference)
is a hard precondition for any area credit.

## RTL transformations (area-reduction tasks)

The area proxy is the generic-cell count after a **fixed, controller-owned light elaboration**
(`proc; opt_expr; opt_clean; techmap; opt_clean`). It does *not* run global boolean
minimization, so a more economical RTL description yields fewer cells. Prefer:

- Factor shared sub-expressions: `(a & b) | (a & c)` ⟶ `a & (b | c)`.
- Drop redundant or constant terms; avoid duplicated logic cones.
- Keep the module name and port list exactly as the reference declares them.

## Synthesis passes (recipe-tuning tasks)

A recipe is a newline-separated list of Yosys optimization passes applied to a fixed design.
Only these passes are accepted (anything else is rejected by the evaluator):

- `opt`, `opt -full`, `opt_expr`, `opt_clean`, `opt_merge`, `opt_reduce`
- `clean`, `flatten`, `share`, `memory_opt`, `wreduce`, `peepopt`
- `techmap`, `abc`, `abc -g AND,OR,XOR,NAND,NOR,XNOR`, `abc -g AND,OR`

`read_*`, `write_*`, `tee`, `exec`, `script`, `!`, and shell-style commands are forbidden.

## Equivalence

Equivalence is proven by a Yosys miter (`miter -equiv` + `sat -verify -prove-asserts`) of the
candidate against the controller-owned reference. A design that is not equivalent fails
regardless of its area.
