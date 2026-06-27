# Life-Science Pack References

Pinned, offline vocabulary and scoring rationale for the drug/life-science pack. Everything here
runs fully offline against pinned fixtures under a hard timeout — there is **no eval-time
download** and **no real-world action** in the execution plane. The only outside-world step is a
governed, human-executed wet-lab assay (Regime C), default-deny.

## Candidate representation

A candidate molecule is a **space-separated list of fragment tokens** from the controlled
vocabulary below (e.g. `scaffold aromatic_ring hbond_donor halogen`). Any token outside the
vocabulary is rejected by the evaluator. The candidate edits only its declared surface
(`molecule.txt` for screening, `candidate.txt` for confirmation) — never the scorer, the
thresholds, or the held-out surrogate.

| Fragment token | Meaning |
|---|---|
| `scaffold` | the core pharmacophore (required for any meaningful binding) |
| `hbond_donor` | a hydrogen-bond donor group |
| `hbond_acceptor` | a hydrogen-bond acceptor group |
| `halogen` | a halogen substituent (F/Cl) |
| `aromatic_ring` | an aromatic ring |
| `solubilizer` | a polar solubilizing group |
| `linker` | a flexible linker |
| `bulky_group` | a large lipophilic substituent |
| `polar_tail` | a polar tail group |

## Screening (Regime B, offline surrogate)

The screen scores a candidate with three pinned surrogate proxies (a docking/affinity model, an
ADMET lipophilicity proxy, and a synthesizability cost), shipped as offline weights in the
held-out fixture. Reasoning heuristics (structure–activity relationships):

- **Binding affinity (primary, higher is better).** `scaffold` contributes most; H-bonding
  groups and a halogen add affinity. Stacking weak contributors rarely beats a balanced set.
- **Drug-likeness (ADMET).** Predicted logP must stay within a window — too lipophilic
  (`aromatic_ring`, `halogen`, `bulky_group`) or too polar fails. A candidate that inflates
  binding by stacking lipophilic groups blows past the logP window and **fails outright**.
- **Synthesizability.** Each fragment has a synthesis cost; the total must stay under a ceiling.
  `bulky_group` is expensive. An un-synthesizable candidate cannot be promoted regardless of its
  predicted affinity.

A candidate is credited with a screen improvement only if it passes drug-likeness **and**
synthesizability and its predicted affinity beats the incumbent under the Goal 24 confidence
bound. The surrogate weights and thresholds are controller-owned (delivered via
`SIRO_HIDDEN_PATH`) and never shown to the agents.

## Confirmation (Regime C, governed wet-lab assay)

A candidate that clears the in-silico screen may be **proposed** (never authorized by an agent)
as a Goal 26 external experiment: a wet-lab assay measuring true potency. The assay is
human-approved (default-deny, identity/two-person rules, irreversible-aware) and human-executed
**outside** the system; the operator returns a signed result bound to the approval. Promotion to
*confirmed* requires that ingested, signed, approved result — never an in-silico score and never
model judgment. Screening-before-confirmation keeps these costly, irreversible assays few and
high-value.

## Safety / dual-use posture

The loop proposes and screens in-silico only. Any physical synthesis or assay is human-gated
through governance, default-deny. The pack ships no synthesis protocols, quantities, or
real-world instructions, and no agent tool can authorize or attach a wet-lab result.
