# Goal Prompt 18 - Provider Operations and Observability

## Goal

Make frontier-provider use operationally reliable and observable. This goal addresses the
provider-layer refinement in `../14_project_retrospective.md`: the stdlib HTTP layer is a
good auditable foundation, but production pilots need retries, error taxonomy, request IDs,
rate-limit handling, and spend visibility.

Depends on Goals 07, 08, 09, 14.

## Requirements

- Add a provider error taxonomy:
  - retryable transient failure,
  - provider rate limit,
  - authentication failure,
  - budget breach,
  - malformed response,
  - provider policy refusal,
  - non-retryable client/config error.
- Add bounded retry policy:
  - exponential backoff with jitter,
  - max attempts per call,
  - no retries after budget breach,
  - no retries for auth or configuration errors,
  - all attempts recorded or summarized in the audit ledger.
- Record provider request metadata where available:
  - provider request ID,
  - HTTP status class,
  - retry count,
  - latency,
  - final error kind,
  - model and provider version if returned.
- Add per-role concurrency limits and per-provider rate-limit settings in config.
- Add observability commands or reports:
  - spend by provider/model/role/task family,
  - latency percentiles,
  - retry/error rates,
  - cost per promotion,
  - escalation rate by provider/model.
- Add tests using injected transports only; no network calls in tests.

## Acceptance criteria

- Retryable injected failures retry up to the configured bound and then either succeed or
  raise a classified error.
- Auth/config failures do not retry.
- Budget breaches halt immediately and do not retry.
- Every model call still writes an auditable ledger entry or an auditable failed-call record.
- Observability summaries can attribute spend and errors by role and provider.
- Cross-model review enforcement remains unchanged.
- All provider tests run offline with injected transports.

## Constraints

- Do not add vendor SDKs unless there is a clear auditability reason. The single HTTP egress
  chokepoint remains the default.
- Do not broaden the egress allowlist.
- Do not hide provider failures behind generic exceptions.
- Do not let retry policy exceed configured token/USD budgets.
- Do not put API keys, raw secrets, or full hidden datasets into logs.

## Self-improvement

This goal improves the "observe" and "reflect" parts of `../13_self_improvement_loop.md`
for frontier-model usage.

- **Records**: provider errors, retries, latency, request metadata, and cost attribution.
- **Reflects / proposes**: the outer loop may propose role-model rebinding or prompt changes
  based on observed reliability and cost-per-promotion.
- **Validated / gated**: operational changes must pass offline injected-transport tests and
  preserve budget enforcement.
- **Bounds**: changing provider allowlists, budgets, or tier remains human-gated.
