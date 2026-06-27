# Confirm a screened candidate with a governed wet-lab assay

`candidate.txt` holds a candidate molecule (fragment-token representation) that has already
**cleared the in-silico screen**. This task confirms it with a real wet-lab dose-response assay
measuring true potency against the kinase target.

**This is a Regime C (external-oracle) task.** Nothing here runs in the execution plane. The
assay is:

1. **Proposed** — only for a candidate that cleared the screen (screening-before-confirmation).
   No agent authorizes it; the org emits a default-deny governed approval request.
2. **Approved** — by a human under the governance identity rules (default-deny, irreversible-aware).
3. **Executed** — by a human, in a wet lab, **outside** the system. The system holds no lab
   credentials and runs no part of the assay.
4. **Ingested** — the operator returns a *signed* result bound to the approval; the controller
   validates the binding and scores the candidate on it.

**Metric:** `measured_potency` (higher is better). A candidate promotes to *confirmed* **only**
on an ingested, signed assay result bound to a live approval — never on an in-silico score and
never on model judgment. An unapproved / expired / revoked / unsigned result never promotes;
null/failed assays are archived as first-class negatives.

**Dual-use note.** The physical synthesis and assay are human-gated through governance,
default-deny. The system proposes and screens only; it never performs or attaches a wet-lab step.
