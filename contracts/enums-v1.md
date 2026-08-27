# Stateback v1 enum contract

**Contract version:** `v1`

This document owns the exact v1 enum symbol strings defined by
`src/stateback/domain/enums.py`. Case and spelling are contractual wherever a
value is serialized or persisted. Renaming a value requires an explicit
compatibility and migration decision.

## `OperationState`

```text
PENDING_POLICY
AWAITING_APPROVAL
READY
EXECUTING
VERIFYING
UNKNOWN
SUCCEEDED
FAILED
DENIED
CANCELLED
COMPENSATING
COMPENSATION_UNKNOWN
COMPENSATED
COMPENSATION_FAILED
MANUAL_INTERVENTION
```

Legal edges are defined in `STATE_MACHINES.md`.

## `EffectOutcome`

```text
APPLIED
NOT_APPLIED
UNKNOWN
```

These values represent external-effect truth supported by evidence. They are
not operation lifecycle states.

## `AttemptState`

```text
STARTED
COMPLETED
```

## `RiskLevel`

```text
LOW
MODERATE
HIGH
CRITICAL
```

## `PrincipalType`

```text
AGENT
HUMAN
SERVICE
OPERATOR
```

## `ArgumentsMode`

```text
INLINE
REFERENCE
```

## `Mutability`

```text
READ_ONLY
MUTATING
```

## `IdempotencyMode`

```text
NONE
NATURAL
PROVIDER_KEY
```

## `VerificationMode`

```text
NONE
READ_BACK
OPERATION_LOOKUP
CUSTOM
```

## `CompensationKind`

```text
NONE
EXACT
APPROXIMATE
MITIGATING
```

`MITIGATING` does not claim exact restoration of external state.

## `EvidenceSource`

```text
EXECUTION_RESPONSE
OPERATION_LOOKUP
READ_BACK
CUSTOM
```

## `PolicyVerdict`

```text
ALLOW
DENY
REQUIRE_APPROVAL
```

## `ApprovalState`

```text
PENDING
APPROVED
REJECTED
EXPIRED
CANCELLED
```

## `CompensationState`

```text
PENDING
EXECUTING
VERIFYING
UNKNOWN
SUCCEEDED
FAILED
```

## `VerificationState`

```text
PENDING
IN_PROGRESS
COMPLETED
```

The current persisted verification model is request/result based and does not
expose a standalone generic verification-state transition table.

## `OutboxState`

```text
PENDING
PUBLISHED
```

## `WorkCommand`

```text
EXECUTE
VERIFY
COMPENSATE
```

## `ErrorKind`

```text
VALIDATION
POLICY
AUTHENTICATION
AUTHORIZATION
PROVIDER_REJECTED
RATE_LIMITED
TRANSIENT_TRANSPORT
PROVIDER_UNAVAILABLE
MALFORMED_PROVIDER_RESPONSE
PROVIDER_INCONSISTENT
PERSISTENCE
MESSAGING
CONCURRENCY_CONFLICT
UNSUPPORTED_CAPABILITY
UNSUPPORTED_CONTRACT_VERSION
SECURITY
INTERNAL
```

## `VerificationTarget`

```text
ORIGINAL_EFFECT
COMPENSATION
```

## `ReconciliationAction`

```text
MARK_SUCCEEDED
MARK_FAILED
MAKE_READY_FOR_SAFE_RETRY
REMAIN_UNKNOWN
REQUIRE_MANUAL_INTERVENTION
```

## `AuditEventType`

| Member | Wire value |
| --- | --- |
| `OPERATION_CREATED` | `operation.created.v1` |
| `POLICY_EVALUATED` | `policy.evaluated.v1` |
| `APPROVAL_REQUESTED` | `approval.requested.v1` |
| `APPROVAL_DECIDED` | `approval.decided.v1` |
| `OPERATION_TRANSITIONED` | `operation.transitioned.v1` |
| `EXECUTION_ATTEMPT_STARTED` | `execution.attempt_started.v1` |
| `EXECUTION_EVIDENCE_RECORDED` | `execution.evidence_recorded.v1` |
| `VERIFICATION_STARTED` | `verification.started.v1` |
| `VERIFICATION_COMPLETED` | `verification.completed.v1` |
| `RECONCILIATION_DECIDED` | `reconciliation.decided.v1` |
| `COMPENSATION_REQUESTED` | `compensation.requested.v1` |
| `COMPENSATION_ATTEMPTED` | `compensation.attempted.v1` |
| `COMPENSATION_RESULT` | `compensation.result.v1` |
| `OPERATOR_ACTION` | `operator.action.v1` |
| `OUTBOX_DIAGNOSTIC` | `outbox.diagnostic.v1` |
| `MANUAL_INTERVENTION_REASON` | `manual_intervention.reason.v1` |
| `SECURITY_CONTROL_DECISION` | `security.control_decision.v1` |

## `TransitionVerdict`

```text
LEGAL
ILLEGAL
```

## `RetrySafetyVerdict`

```text
SAFE
UNSAFE
NEEDS_CAPABILITY_PROOF
```

## `RetrySafetyBasis`

```text
EXECUTION_NOT_APPLIED
VERIFIED_NOT_APPLIED
NATURAL_IDEMPOTENCY
PROVIDER_NATIVE_IDEMPOTENCY
PROVIDER_SPECIFIC_CONTRACT
```

## `CrashInterpretation`

```text
NO_PROVIDER_ATTEMPT
POTENTIALLY_UNKNOWN
USE_DURABLE_EVIDENCE
```

## `ApprovalBindingVerdict`

```text
VALID
INVALID
```

## Operation-state sets

`FORWARD_TERMINAL_STATES` contains:

```text
SUCCEEDED
FAILED
DENIED
CANCELLED
COMPENSATED
COMPENSATION_FAILED
MANUAL_INTERVENTION
```

A forward-terminal state can still have an explicitly legal follow-up edge.

`ABSOLUTE_TERMINAL_STATES` contains:

```text
DENIED
CANCELLED
COMPENSATED
```

No legal v1 operation edge originates from an absolute-terminal state.

## Fixed v1 constants

```text
CONTRACT_VERSION = "v1"
INITIAL_OPERATION_VERSION = 1
INITIAL_COMPENSATION_VERSION = 1
INITIAL_ATTEMPT_NUMBER = 1
INITIAL_AUDIT_SEQUENCE = 1
```

## Stable Stateback identity convention

```text
sb:v1:op:{operation_id}
sb:v1:comp:{compensation_id}
```

These are not enum values, but are stable v1 identity conventions used by the
domain model and provider correlation logic.

## Change control

Any change to this document requires checking the enum module, strict
serializers/parsers, persistence/migrations, state machines, transition logic,
API/SDK/MCP/frontend consumers, provider descriptors, fixtures, contract tests,
and durable-history compatibility. An incompatible serialized-symbol change
should use an explicit contract-version transition rather than silently
changing `v1`.
