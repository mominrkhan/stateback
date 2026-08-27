# Verification and Reconciliation Contract

**Status:** Canonical v1
**Owns:** verification requests, evidence outcomes, reconciliation semantics, retry-safety determination after ambiguity.

---

## 1. Purpose

Verification answers:

> What can the external provider currently establish about the effect Stateback attempted?

Reconciliation answers:

> Given durable Stateback knowledge plus verification evidence, what legal lifecycle transition follows?

Verification gathers evidence. Reconciliation applies evidence. Keep them distinct.

---

## 2. Verification preconditions

Verification may run when:

- operation is `VERIFYING`;
- operation is `UNKNOWN` and provider/effect supports verification;
- operator requests supported verification from `MANUAL_INTERVENTION`;
- compensation verification is required by compensation lifecycle.

Verification must be read-only with respect to the target external effect unless the provider's only status mechanism has explicitly documented semantics.

---

## 3. `VerificationRequest`

```text
VerificationRequest {
  contract_version: "v1"
  verification_id: opaque_id
  operation_id: opaque_id
  operation_version: integer
  target: enum<ORIGINAL_EFFECT | COMPENSATION>
  target_attempt_id: optional<opaque_id>

  effect: EffectRef
  external_operation_id: optional<string>
  external_resource_ids: list<string>
  idempotency_identity: string
  provider_evidence_refs: list<opaque_id>

  requested_at: timestamp
}
```

The provider adapter may receive material verification arguments derived from durable intent, but credentials are not part of this persisted contract.

---

## 4. `VerificationResult`

```text
VerificationResult {
  contract_version: "v1"
  verification_id: opaque_id
  outcome: EffectOutcome
  evidence: ProviderEvidence
  error: optional<NormalizedError>
  completed_at: timestamp
}
```

Canonical outcome semantics are exactly:

- `APPLIED`;
- `NOT_APPLIED`;
- `UNKNOWN`.

No `PROBABLY_APPLIED` state exists in v1.

If a provider can only offer probabilistic/weak evidence, the adapter must either map it under an explicitly accepted custom evidence contract or return `UNKNOWN`.

---

## 5. Evidence requirements

### To return `APPLIED`

Evidence must establish the intended postcondition with sufficient specificity to distinguish it from an unrelated existing resource/action.

Examples may include:

- lookup by provider operation/request ID;
- resource ID created by the attempt;
- read-back containing operation-specific marker;
- provider idempotency-key lookup.

### To return `NOT_APPLIED`

Evidence must establish absence/non-execution under provider semantics.

Simple "not found" is not always sufficient if the provider is eventually consistent. The adapter contract must account for known visibility windows.

### To return `UNKNOWN`

Use when:

- verification transport fails ambiguously;
- provider evidence is incomplete;
- provider is eventually consistent and observation is too early;
- evidence conflicts;
- provider offers no suitable lookup;
- response is malformed.

---

## 6. Reconciliation input

```text
ReconciliationInput {
  operation: Operation
  attempts: list<ExecutionAttempt>
  verification_result: VerificationResult
  provider_descriptor: EffectDescriptor
  policy_obligations: PolicyObligations
}
```

Reconciliation is deterministic given canonical inputs.

---

## 7. Reconciliation output

```text
ReconciliationDecision {
  action: enum<
    MARK_SUCCEEDED |
    MARK_FAILED |
    MAKE_READY_FOR_SAFE_RETRY |
    REMAIN_UNKNOWN |
    REQUIRE_MANUAL_INTERVENTION
  >
  reason_code: string
}
```

This decision is not a direct public lifecycle enum. The Transition Service maps it only to transitions legal in `STATE_MACHINES.md`.

---

## 8. Safe retry after verification

`MAKE_READY_FOR_SAFE_RETRY` is legal when:

- verification result is `NOT_APPLIED` and policy allows another attempt; or
- another explicit provider capability proves replay safe.

A verification result of `UNKNOWN` alone cannot authorize retry for a non-idempotent effect.

---

## 9. Repeatability

Verification/reconciliation must be safe to invoke repeatedly.

Repeated verification may produce newer evidence. Older evidence remains durable.

Reconciliation must use current operation state/version and reject stale decisions.

---

## 10. Crash semantics

### Crash after verification call but before result persistence

Verification attempt remains unresolved. Re-run verification; do not infer its unpersisted observation.

### Crash after result persistence before transition

Recovery reuses durable result and applies reconciliation deterministically.

### Crash after transition

Reload canonical operation state; repeated command must no-op or follow current state.

---

## 11. Eventual consistency

Adapters for eventually consistent providers must document:

- visibility delay assumptions;
- whether `NOT_FOUND` can prove `NOT_APPLIED`;
- recommended verification timing/backoff;
- maximum useful automatic verification window.

Stateback must not turn an eventually consistent read into false certainty.

---

## 12. Manual evidence

v1 may allow an authorized operator to record external evidence only through an explicit operator workflow.

Manual evidence must include:

- actor;
- reason;
- evidence/reference;
- timestamp;
- target operation/version.

It cannot silently masquerade as adapter-generated provider evidence.

---

## 13. Tests

Required coverage includes:

- execution applied, response lost, verification finds applied;
- execution not applied, verification proves not applied;
- inconclusive verification;
- verification transport failure;
- eventual-consistency not-found;
- contradictory evidence;
- duplicate verification;
- stale reconciliation decision;
- crash after observation/before persistence;
- crash after persistence/before transition;
- provider with no verification support.
