# Provider Adapter Contract

**Status:** Canonical v1
**Owns:** provider capability declarations, execution/verification/compensation boundary, evidence normalization.

A provider adapter is a semantic boundary, not a thin wrapper around an SDK call.

---

## 1. Core rule

Adapters answer:

> Given this canonical effect request, what does this provider actually support and what evidence can it return?

Adapters do **not** answer:

> What canonical Stateback lifecycle state should the operation become?

The runtime/transition service owns lifecycle decisions.

---

## 2. Capability enums

### `Mutability`

```text
READ_ONLY
MUTATING
```

### `IdempotencyMode`

```text
NONE
NATURAL
PROVIDER_KEY
```

Meaning:

- `NONE`: repeating the provider mutation may produce additional effects.
- `NATURAL`: repeated equivalent invocation is inherently idempotent under documented effect semantics.
- `PROVIDER_KEY`: provider supports a client-supplied idempotency/deduplication key with documented semantics.

### `VerificationMode`

```text
NONE
READ_BACK
OPERATION_LOOKUP
CUSTOM
```

### `CompensationKind`

```text
NONE
EXACT
APPROXIMATE
MITIGATING
```

---

## 3. `EffectDescriptor`

Every provider action exposed for managed use has one descriptor.

```text
EffectDescriptor {
  contract_version: "v1"
  effect: EffectRef
  mutability: Mutability
  risk_level: RiskLevel
  idempotency_mode: IdempotencyMode
  verification_mode: VerificationMode
  compensation_kind: CompensationKind

  supports_external_operation_id: boolean
  immediate_response_can_prove_applied: boolean
  immediate_response_can_prove_not_applied: boolean

  provider_key_semantics: optional<ProviderKeySemantics>
  documentation: string
}
```

Capability declarations are testable claims.

An adapter MUST NOT declare a stronger capability than the provider contract/tests establish.

---

## 4. `ProviderKeySemantics`

Required when `idempotency_mode = PROVIDER_KEY`.

```text
ProviderKeySemantics {
  scope: string
  replay_window: optional<string>
  same_key_same_request_required: boolean
  conflicting_request_behavior: string
  response_replay_behavior: string
}
```

The implementation may structure this more strongly, but these facts must be documented and testable.

If a provider only deduplicates for a finite window, Stateback must not treat that as timeless exactly-once behavior.

---

## 5. Adapter interface

Language-neutral conceptual interface:

```text
ProviderAdapter {
  descriptor(effect_ref) -> EffectDescriptor

  validate_execution(request) -> ValidationResult

  verification_resource_ids(request) -> list<string>
      # pure, deterministic identities persisted before provider invocation

  execute(context, request) -> ExecutionEvidence

  verify(context, verification_request) -> VerificationEvidence
      # only if descriptor says verification supported

  compensate(context, compensation_request) -> CompensationEvidence
      # only if compensation supported
}
```

A concrete language may use protocols/interfaces/classes. Semantics are normative.

---

## 6. Execution context

```text
ProviderExecutionContext {
  operation_id: opaque_id
  attempt_id: opaque_id
  idempotency_identity: string
  provider_idempotency_key: optional<string>
  correlation_id: optional<string>
  deadline: optional<timestamp>
}
```

The context may include internal tracing/configuration, but must not expose Stateback lifecycle mutation methods to the adapter.

---

## 7. Execution request

```text
ProviderExecutionRequest {
  effect: EffectRef
  arguments: json
}
```

Material arguments come from the canonical persisted intent or its secure durable reference.

The adapter must not silently alter material intent.

Provider-specific defaults that materially change behavior must be part of canonicalized request semantics.

Before invoking a consequential provider mutation, the runtime persists the adapter's
`verification_resource_ids(request)` on the started attempt. This method MUST be pure,
deterministic, perform no provider I/O, and return the non-secret target identities needed
to verify an ambiguous outcome after a process crash. Execution evidence may add identities,
but MUST NOT erase these pre-boundary verification targets.

---

## 8. Execution evidence

```text
ExecutionEvidence {
  outcome: EffectOutcome
  evidence: optional<ProviderEvidence>
  error: optional<NormalizedError>
  external_operation_id: optional<string>
  external_resource_ids: list<string>
}
```

Rules:

- `APPLIED` requires provider-specific evidence sufficient under descriptor/adapter contract.
- `NOT_APPLIED` requires evidence the mutation did not occur.
- if request may have reached provider and result is not conclusive, return `UNKNOWN`.
- returning `UNKNOWN` is correct behavior, not adapter failure.

---

## 9. Exception normalization rule

No raw provider exception crosses into lifecycle logic unclassified.

Adapter code must catch/translate provider/transport errors at its boundary.

Examples:

### Local validation before network

```text
outcome = NOT_APPLIED
error.kind = VALIDATION
```

### Provider explicit rejection before acceptance

```text
outcome = NOT_APPLIED
error.kind = PROVIDER_REJECTED
```

### Timeout after request may have been transmitted

```text
outcome = UNKNOWN
error.kind = TRANSIENT_TRANSPORT
```

### Malformed response after possible acceptance

```text
outcome = UNKNOWN
error.kind = MALFORMED_PROVIDER_RESPONSE
```

---

## 10. Adapter retry prohibition

Mutating provider calls MUST NOT contain hidden automatic retries unless the adapter can prove the retry is safe under the effect's idempotency semantics and the behavior is part of the canonical contract.

Prefer disabling SDK-level mutation retries and letting Stateback runtime decide safe replay.

Read-only verification calls MAY use bounded infrastructure retries if doing so does not create consequential effects.

---

## 11. Verification interface

If verification is supported, adapter verification must gather evidence about the target external effect.

Possible methods:

- operation lookup using external operation/request ID;
- read-back of resource state;
- provider-specific query;
- custom evidence endpoint.

Verification returns:

```text
VerificationEvidence {
  outcome: EffectOutcome
  evidence: ProviderEvidence
  error: optional<NormalizedError>
}
```

`UNKNOWN` is legal.

Verification MUST NOT return `APPLIED` solely because Stateback previously called `execute`.

---

## 12. Compensation interface

If compensation is supported:

```text
CompensationRequest {
  original_operation_id: opaque_id
  compensation_id: opaque_id
  compensation_attempt_id: opaque_id
  original_evidence: list<ProviderEvidence>
  compensation_arguments: json
  idempotency_identity: string
  provider_idempotency_key: optional<string>
}
```

Return:

```text
CompensationEvidence {
  outcome: EffectOutcome
  evidence: optional<ProviderEvidence>
  error: optional<NormalizedError>
  external_operation_id: optional<string>
}
```

Compensation may itself use a provider-native key distinct from the original operation but stable across retries of the compensation.

---

## 13. No lifecycle mutation

Forbidden adapter behavior:

- `operation.state = SUCCEEDED`;
- direct database writes to operation lifecycle;
- direct outbox publication;
- deciding whether policy permits execution;
- converting unknown to failed for UI convenience;
- marking original operation compensated without compensation service.

---

## 14. Credential boundary

Adapters obtain provider credentials through approved runtime configuration/secret facilities.

They MUST NOT:

- store credentials in operation intent;
- put secrets in `ProviderEvidence`;
- return secrets through errors;
- log authorization headers/private keys;
- serialize client objects.

Credential identity metadata MAY be recorded if useful and non-secret, e.g. provider account/project identifier.

---

## 15. Sandbox and deterministic reference provider

Before a real adapter is accepted, a deterministic reference/fake adapter must be able to simulate:

- applied;
- not applied;
- timeout/unknown;
- external ID;
- provider-native idempotency;
- duplicate key;
- verification applied/not-applied/unknown;
- compensation success/failure/unknown;
- malformed evidence.

The fake is a correctness test instrument, not a benchmark baseline that can be changed to make Stateback appear safer.

---

## 16. Provider adapter acceptance

A production adapter must document and test:

1. exact effect/action semantics;
2. idempotency semantics and replay window;
3. what responses prove `APPLIED`;
4. what responses prove `NOT_APPLIED`;
5. ambiguous errors;
6. verification method;
7. compensation kind and limitations;
8. external IDs;
9. credential requirements;
10. sandbox strategy;
11. rate limit/transient handling;
12. redaction rules.

If any claim is uncertain, capability declaration must be conservative.
