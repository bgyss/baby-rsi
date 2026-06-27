# Math Pack References

Pinned proof vocabulary for the initial exact-regime tasks:

- `Nat.add_zero n`: proves `n + 0 = n`.
- `And.intro hp hq`: constructs a proof of `p ∧ q`.
- `h.left` / `h.right`: projections from a conjunction proof.

The evaluator rejects `sorry`, `axiom`, and `unsafe`; proofs must verify under the pinned
offline `lake build` invocation.
