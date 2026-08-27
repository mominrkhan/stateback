# ADR-0003 — Unknown Outcomes Are First-Class; No Universal Exactly-Once Claim

- **Status:** Accepted
- **Date:** 2026-08-14

## Context

Distributed calls to external systems have an unavoidable ambiguity window:

1. Stateback sends a request.
2. Provider may apply the effect.
3. Response is lost or the process crashes.
4. Stateback cannot atomically commit the provider's external state with its own database.

Calling this "failure" and retrying can duplicate the effect.

No runtime can create universal exactly-once semantics across arbitrary APIs without cooperation from those systems.

## Decision

Stateback uses canonical effect outcomes:

```text
APPLIED
NOT_APPLIED
UNKNOWN
```

`UNKNOWN` is persisted and exposed explicitly.

Stateback does not claim universal exactly-once execution.

Safe replay may be achieved for specific effects through combinations of:

- stable operation identity;
- provider-native idempotency keys;
- natural idempotency;
- verification/reconciliation;
- deduplication;
- compensation;
- state convergence.

## Consequences

### Positive

- Correct distributed-systems semantics.
- Prevents dangerous blind retry.
- Makes provider capability differences explicit.
- Allows honest product guarantees.

### Negative

- Some operations can remain unresolved and require manual intervention.
- UX is more nuanced than a simple success/failure model.
- Provider-specific verification work is necessary.

## Rejected alternatives

### Retry every transient exception

Rejected because "transient" describes the transport error, not whether the external effect happened.

### Market exactly-once and implement best-effort dedupe

Rejected because guarantees would exceed reality.

## Guardrail

Any documentation or API claiming exactly-once must scope that claim to a specific provider/effect and list the assumptions that make it true.
