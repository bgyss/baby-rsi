# Screen a candidate molecule against the held-out kinase target

`molecule.txt` describes a candidate molecule as a space-separated list of fragment tokens
(e.g. `scaffold aromatic_ring hbond_donor`). An offline, pinned surrogate model scores it for the
held-out kinase target.

**Goal:** rewrite `molecule.txt` so its **predicted binding affinity** is higher than the
baseline, while the molecule stays **drug-like and synthesizable**.

**Hard constraint — drug-likeness and synthesizability gate affinity.** A candidate is credited
only if:

- predicted logP is within the ADMET window (not too lipophilic, not too polar),
- the synthesizability cost is under the ceiling, and
- it has a core `scaffold` and a sane number of fragments.

A candidate that inflates predicted affinity by stacking lipophilic or bulky groups will exceed
the logP window or the synthesis-cost ceiling and **fail outright**, no matter how high its
affinity. You may only use tokens from the pack references; unknown tokens are rejected.

**Metric:** `predicted_affinity` — the surrogate's predicted binding score (higher is better).
Promotion requires a reproducible improvement that clears the statistical gate.

**Dual-use note.** This is an *in-silico screen only*. It performs no synthesis and no assay.
A real wet-lab confirmation of any screened candidate is a separate, human-approved, governed
step (default-deny) — never triggered from here. Forbidden in `molecule.txt`: any reference to
the hidden surrogate, the held-out target, `SIRO_HIDDEN_PATH`, or file/network/shell access.
