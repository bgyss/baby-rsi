# Goal Prompt 15 - Hard Resource Isolation Backend

## Goal

Replace best-effort portable resource monitoring with a hard isolation backend for serious
scale-up. This goal addresses the governed-compute refinement from
`../14_project_retrospective.md`: memory enforcement must be reliable before Tier 2 compute
scale-up is trusted.

The current local sandbox remains useful for development. This goal adds a stricter backend
for Linux/container execution where memory, process, wall-clock, filesystem, and network
limits can be enforced by the operating system.

Depends on Goals 02, 04, 09, 11.

## Requirements

- Add a sandbox backend abstraction, for example:
  - `local` backend: current temp-dir + `sitecustomize` + timeout behavior,
  - `linux_guarded` backend: cgroups/process limits/firewall or container-backed isolation.
- Implement hard limits for the guarded backend:
  - wall-clock deadline,
  - memory ceiling via cgroups or equivalent,
  - process count ceiling,
  - output size ceiling,
  - read/write filesystem boundary,
  - no execution-plane network,
  - scrubbed environment with no credentials.
- Track process-tree resource usage, not only parent RSS.
- Split tests into:
  - portable local sandbox tests,
  - hard-isolation tests that run only when the target backend is available.
- Update `scale.py` so governed compute tiers can require a hard backend above a configured
  tier.
- Update docs to make clear that the portable local backend is a developer fallback, not the
  production isolation story.

## Acceptance criteria

- On a supported Linux/container environment, memory breaches reliably raise
  `BudgetExceeded(kind="memory_mb")` and archive a negative attempt.
- Process-tree memory is counted; a child process cannot avoid the limit by forking.
- Execution-plane network probes fail under the hard backend.
- Credentials are absent from the execution environment under both backends.
- Wall-clock breaches continue to halt and archive consistently.
- The full local suite passes on the portable backend, with hard-isolation tests skipped
  clearly when the backend is unavailable.
- Tier 2 compute tiers above the configured threshold refuse to run on the portable backend
  unless explicitly configured for local development.

## Constraints

- Do not relax any existing sandbox invariant.
- Do not add autonomous package installation to candidate execution.
- Do not let a candidate choose the sandbox backend or resource limits.
- Do not require Docker or a specific container runtime for basic Tier 0 local development;
  the hard backend is additive.

## Self-improvement

This goal strengthens the validation step of `../13_self_improvement_loop.md`: larger or
longer experiments must still be bounded by objective, enforceable limits.

- **Records**: resource breaches, backend identity, peak resource usage, and negative
  attempts in the archive.
- **Reflects / proposes**: loops may propose larger compute only after smaller-tier success;
  backend failures become data for refinement.
- **Validated / gated**: promotion under governed compute requires successful execution on
  an approved backend with reproducible metrics.
- **Bounds**: compute expansion, backend policy changes, and execution-plane network changes
  remain human-gated.
