# 19 - Drug Discovery Testing, Deployment, and Wet-Lab Integration Plan

This plan refines how to take the current `siro` implementation from repository tests to a
bounded drug-discovery pilot. It is intentionally staged. The system may rank candidates,
prepare evidence packets, and propose governed confirmations. It must not synthesize compounds,
operate instruments, approve assays, attest results, or bypass qualified human review.

The life-science architecture is two-stage:

```text
offline screen -> statistical gate -> governed confirmation proposal -> human approval
-> lab-owned execution -> signed result ingest -> external-oracle gate -> archive + memory
```

## Non-Negotiable Boundaries

- The execution plane runs no synthesis, assay, ordering, instrument, LIMS, ELN, or network
  action.
- The control plane may propose an `EXTERNAL_EXPERIMENT`; it may not approve it.
- Wet-lab work happens outside `siro` under institutional procedures.
- A confirmation promotes only from a signed, approved, hash-bound result.
- Null, failed, contaminated, revoked, expired, unsigned, or mismatched results are retained as
  negative data and never promote.
- Drug-discovery outputs are research candidates, not medical advice, clinical decisions, or
  unsupervised treatment recommendations.

## Step 1 - Repository Health Gate

Purpose: verify the current code and docs before any domain work.

Commands:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro check-docs
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run pytest -q
```

Exit criteria:

- Docs, README status, goal manifest, and path-privacy checks pass.
- Static checks pass.
- Full tests pass, or platform-specific skips are documented.

## Step 2 - Focused Life-Science Regression Gate

Purpose: pin the load-bearing Goal 26/27 invariants.

Commands:

```zsh
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_external_experiment.py tests/test_life_science_pack.py -q
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_statistical_gate.py tests/test_packs.py -q
```

Exit criteria:

- Agents cannot self-approve or attest external results.
- The external adapter never touches the execution plane.
- Unapproved, revoked, unsigned, mismatched, and null results are rejected and logged.
- The life-science screen rejects hidden-surrogate peeking, unknown fragments, and gamed
  non-drug-like candidates.
- Screening-before-confirmation is enforced.

## Step 3 - Offline Screening Dry Run

Purpose: exercise the life-science pack without any external action.

Command:

```zsh
UV_CACHE_DIR=.uv-cache uv run siro run-research packs/life_science/tasks/screening/kinase_binding \
  --config config/tier0.life_science.yaml \
  --objective "Improve the candidate while preserving drug-likeness and synthesizability gates."
```

Exit criteria:

- The candidate edits only `molecule.txt`.
- The hidden surrogate remains controller-owned.
- Statistical evidence records seeds, confidence, interval, and promotion decision.
- A candidate that improves predicted affinity by violating drug-likeness or synthesizability
  fails before promotion.

## Step 4 - Confirmation Proposal Dry Run

Purpose: verify that an assay can be proposed only after screening evidence exists.

Procedure:

1. Select a candidate that cleared the offline screen.
2. Call the confirmation proposal path for `packs/life_science/tasks/confirmation/kinase_assay`.
3. Leave the approval pending.
4. Evaluate the confirmation task before any result is ingested.

Exit criteria:

- Unscreened candidates raise `ConfirmationNotEarned`.
- Screen evidence is attached to the approval evidence trail.
- The confirmation adapter reports that it is awaiting an external result.
- No assay is approved, scheduled, or executed during this dry run.

## Step 5 - Governance Rehearsal With Mock Results

Purpose: prove the full external-oracle lifecycle without claiming scientific evidence.

Procedure:

1. Generate a confirmation request from a screen-clearing candidate.
2. Approve it with a human operator identity in a test ledger.
3. Ingest a clearly labeled mock signed result.
4. Export or inspect the governance packet.
5. Repeat with revoked, unsigned, mismatched-candidate, and null-result cases.

Exit criteria:

- The approved mock result resolves only for the exact candidate and proposal hash.
- Rejected results are logged with `REJECTED` status and reasons.
- Revocation after ingest removes the resolving result from promotion.
- The exported packet contains request, decision, provenance, signature, and result evidence.

## Step 6 - Target Deployment Rehearsal

Purpose: prove the host environment enforces isolation and record integrity.

Minimum deployment shape:

- A Linux/container runner for execution-plane tasks.
- Cgroup-backed memory and process ceilings for governed compute tiers.
- Deny-by-default execution-plane network policy.
- A separate control-plane environment for model provider credentials.
- Append-only or SQLite-backed ledgers persisted outside ephemeral worker directories.
- Backups for approvals, external results, attempt archives, and model-call ledgers.

Exit criteria:

- Hard-isolation tests pass in the target runner.
- Candidate processes cannot reach the network.
- Candidate environments contain no provider keys, lab credentials, or data-service tokens.
- Attempt, model-call, approval, and external-result ledgers persist across worker restarts.

## Step 7 - Lab Data Contract Before Instruments

Purpose: define what a wet-lab result must contain before connecting to a real lab workflow.

Required fields for a result contract:

- Approval request ID and governed action hash.
- Candidate identifier and exact submitted candidate payload.
- Assay name, version, batch ID, and protocol or SOP reference controlled by the lab.
- Sample ID, plate or vessel ID, run ID, and instrument export identifier.
- Primary metric, units, pass/fail status, and any required secondary metrics.
- Controls and quality flags at the level the lab already records them.
- Operator identity, timestamp, provenance URI or record ID, and signature.
- Null/failed/inconclusive reason when no usable measurement exists.

Exit criteria:

- The lab can produce the result contract without manual copy/paste of scientific values into
  free-form text.
- `siro` can reject malformed, unsigned, stale, mismatched, or revoked-result records.
- The contract is reviewed by the responsible scientist, automation engineer, and compliance or
  quality owner for the environment.

## Step 8 - Wet-Lab Integration Pilot

Purpose: ingest one low-risk real external result without automating wet-lab execution.

Procedure:

1. Choose a non-clinical, low-risk assay already approved by the lab.
2. Generate a confirmation proposal from a screen-clearing candidate.
3. Have qualified humans review scientific rationale, cost, risk, controls, and stop criteria.
4. Approve the exact proposal through the governance ledger.
5. Execute the assay entirely through lab-owned workflows.
6. Export or transform the lab result into the agreed result contract.
7. Ingest the signed result.
8. Verify the external-oracle decision, archive entry, memory update, and governance packet.

Exit criteria:

- The lab action is traceable to one live approval.
- `siro` has no authority over scheduling, sample handling, instrument control, or result
  attestation.
- A confirmed promotion is based on the signed external result, not the in-silico score.
- A failed or null assay becomes durable negative data.

## Step 9 - Automation Ideas, Ordered by Risk

Automate in this order, stopping whenever auditability or human control regresses:

1. **Read-only result import.** Parse LIMS/ELN/instrument exports into `ExternalResultRecord`
   drafts. Humans still sign and ingest.
2. **Schema validation service.** Validate units, required controls, candidate hash, approval
   status, and operator signature before ingestion.
3. **Governance packet export.** Produce a review packet for scientists and quality reviewers:
   screen evidence, proposal, approval, assay result, and rejection checks.
4. **Inventory and scheduling hints.** Suggest needed materials, plate capacity, and schedule
   windows, but do not reserve instruments or order materials automatically.
5. **Lab worklist draft generation.** Emit a draft worklist for a lab automation system to
   review and import under human control.
6. **Instrument adapter sandbox.** Build a dry-run adapter that targets simulated instruments
   or vendor test modes only.
7. **Human-triggered execution handoff.** Allow a human operator to attach the approved
   proposal to a lab-owned automation run, outside `siro`, with explicit confirmation.
8. **Closed-loop batching.** Group only pre-approved candidates into a batch proposal with a
   fixed cost/risk envelope and per-candidate traceability.

Do not automate:

- Compound ordering or synthesis authorization.
- Assay approval.
- Instrument execution from candidate code.
- Biosafety or compliance decisions.
- Clinical interpretation.
- Editing evaluator, gate, approval, or result-signing policy from inside the loop.

## Step 10 - Drug-Discovery Expansion Ideas

These are candidate pack extensions, not permissions to run real-world work:

- Add multiple offline screening tasks for selectivity, solubility, permeability, and toxicity
  proxies, each with hard secondary gates.
- Add counter-screen tasks where high target affinity but poor selectivity fails.
- Add uncertainty-aware ranking so confirmations prefer candidates with both strong predicted
  value and useful information gain.
- Add synthesis-feasibility tasks that score only route plausibility, not autonomous ordering.
- Add active-learning batch proposals that recommend a small diverse set for human review.
- Add assay-family adapters for potency, binding, cell viability, and ADME result schemas.
- Add calibration reports comparing surrogate scores against ingested external results.
- Add contamination, plate-edge, control-failure, and batch-effect negative-result categories.

## Standards and External Anchors to Review

Use these as planning inputs before production deployment. They do not replace legal,
quality, biosafety, or scientific review.

- FDA 21 CFR Part 11 for electronic records and signatures:
  <https://www.ecfr.gov/current/title-21/chapter-I/subchapter-A/part-11>
- FDA data integrity guidance for drug CGMP environments:
  <https://www.fda.gov/regulatory-information/search-fda-guidance-documents/data-integrity-and-compliance-drug-cgmp-questions-and-answers>
- ICH Q14 analytical procedure development:
  <https://database.ich.org/sites/default/files/ICH_Q14_Guideline_2023_1116.pdf>
- NIH/NCBI Assay Guidance Manual for assay development and screening concepts:
  <https://www.ncbi.nlm.nih.gov/books/NBK53196/>
- SiLA 2 for lab automation interface concepts:
  <https://sila-standard.com/>
- Allotrope Foundation standards for analytical data interoperability:
  <https://www.allotrope.org/>

## Promotion Decision

A drug-discovery deployment may move from dry run to real wet-lab integration only when all
of these are true:

- Repository, focused life-science, and target-isolation gates pass.
- The lab result contract exists and has qualified review.
- Governance identity, signatures, revocation, and packet export are exercised.
- A mock-result rehearsal covers accepted, rejected, revoked, unsigned, mismatched, and null
  outcomes.
- The first real assay is low-risk, human-approved, lab-owned, and traceable to one exact
  proposal.

Until then, `siro` should be treated as an auditable screening and proposal system, not a
wet-lab automation controller.
