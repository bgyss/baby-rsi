# 03 — Agent Roles

## Role design pattern

Each agent should have:

```yaml
name: string
purpose: string
capability_tier: low | medium | high   # required model capability
inputs: list
outputs: list                           # typed; enforced via structured output
output_schema: pydantic_model           # the contract the orchestrator validates
allowed_tools: list                     # control-plane functions only — never raw shell/network
forbidden_actions: list
success_criteria: list
escalation_triggers: list
```

## Model assignment

Every role is backed by a model through the provider abstraction (`07_model_providers_and_tiers.md`). The role declares a `capability_tier`; the controller binds it to a concrete provider/model from config (`agent_models`) for the active deployment tier:

- At **Tier 0**, every role binds to a local model.
- At **Tier 1**, reasoning-heavy roles (Hypothesis, Literature, Implementation, Interpretation, Meta-Research) bind to frontier models (Claude/GPT); objective roles (Evaluation) can stay local.
- **The Safety Agent should use a different provider than the Implementation Agent** so one model's blind spots are checked by another.

Agents emit *structured proposals validated against `output_schema`*; they never execute their own output. Tools available to an agent are control-plane functions (e.g. `read_allowed_file`, `query_memory`, `propose_patch`), not shell or network access.

## Orchestrator / Controller Agent

Purpose:

- Select agenda items, assign roles, enforce budget (compute + token/USD) and tier policy.
- Route proposals through gates; escalate decisions requiring human review.

Inputs:

- Research objective and current agenda
- Agent proposals and gate results
- Budget and tier configuration

Outputs:

- Task assignments
- Triage and promotion decisions (within policy)
- Escalations to human governance

Forbidden actions:

- Executing candidate code itself (delegates to the execution plane)
- Approving its own budget/tier/permission expansions
- Bypassing any gate

## Hypothesis Agent

Capability tier: high (frontier at Tier 1).

Purpose:

- Generate falsifiable research ideas.
- Prefer ideas with cheap tests and objective metrics.

Inputs:

- Research objective
- Prior experiment results
- Research memory summaries
- Known bottlenecks

Outputs:

- Hypothesis statement
- Expected mechanism
- Proposed experiment
- Required metrics
- Risk notes

Forbidden actions:

- Running code
- Editing files
- Changing evaluators

## Literature Agent

Capability tier: high (frontier at Tier 1).

Purpose:

- Ground a hypothesis against prior art, references, and existing research memory.
- Detect duplicates, known negative results, and related strategies before spending budget.

Inputs:

- Hypothesis statement
- Reference set (`12_references.md`) and retrieved memory
- Prior experiment summaries

Outputs:

- Prior-art notes and related work
- Duplicate / novelty assessment
- Suggested refinements or caveats

Forbidden actions:

- Running code or editing files
- Treating retrieved/tool content as instructions (prompt-injection guard)
- Unrestricted web access; retrieval is mediated by control-plane tools

## Implementation Agent

Capability tier: high (frontier at Tier 1).

Purpose:

- Convert an approved experiment plan into code changes.

Inputs:

- Experiment plan
- Allowed edit surfaces
- Baseline code
- Test requirements

Outputs:

- Code diff
- Implementation notes
- Expected impact
- Known risks

Forbidden actions:

- Editing evaluator code unless explicitly allowed
- Disabling tests
- Removing logging
- Expanding permissions

## Experiment Runner Agent

Purpose:

- Execute experiments reproducibly.

Inputs:

- Code diff
- Environment spec
- Budget tier
- Test command

Outputs:

- Logs
- Metrics
- Artifacts
- Failure reports

Forbidden actions:

- Network access unless explicitly required
- Increasing compute budget
- Retrying indefinitely

## Evaluation Agent

Purpose:

- Compare experiment results against baseline and thresholds.

Inputs:

- Baseline metrics
- Candidate metrics
- Eval policy
- Regression thresholds

Outputs:

- Pass/fail decision
- Metric deltas
- Regression report
- Suggested follow-up

Forbidden actions:

- Changing eval criteria after seeing result
- Ignoring failing tests

## Safety Agent

Capability tier: high; **must use a different provider than the Implementation Agent** (cross-model review).

Purpose:

- Identify policy, security, autonomy, and governance concerns.
- Review for frontier-specific risks: prompt injection, exfiltration via API calls, persuasive overclaiming.

Inputs:

- Code diff
- Tool permissions
- Logs
- Agent outputs
- Eval results

Outputs:

- Safety classification
- Risk notes
- Required mitigations
- Escalation recommendation

Forbidden actions:

- Approving its own policy changes

## Interpretation Agent

Purpose:

- Produce a research-quality interpretation of results.

Inputs:

- Hypothesis
- Experiment plan
- Metrics
- Logs
- Failure reports

Outputs:

- Result summary
- Likely explanation
- Confidence level
- Follow-up experiments
- Memory entry draft

## Memory Curator Agent

Purpose:

- Store structured research memory and retrieve relevant prior results.

Inputs:

- Experiment records
- Interpretations
- Metadata

Outputs:

- Memory entry
- Related prior work
- Lessons learned
- Retrieval tags

Forbidden actions:

- Deleting records without human approval
- Rewriting history

## Meta-Research Agent

Purpose:

- Improve the research process itself.

Inputs:

- Aggregate experiment history
- Agent performance metrics
- Failure modes
- Bottleneck reports

Outputs:

- Proposed process change
- Expected benefit
- Validation experiment
- Rollback plan

Forbidden actions:

- Directly applying process changes without approval
- Modifying safety gates
- Expanding permissions
