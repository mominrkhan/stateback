# Compensation Contract

**Status:** Canonical v1
**Owns:** compensation capability, compensation intent, identity, outcome, and relationship to the original operation.

---

## 1. Core principle

Compensation is another consequential effect.

It is not:

- database rollback;
- deletion of original history;
- proof the original effect never happened.

It receives the same safety discipline as original execution.

---

## 2. Compensation kind

Canonical `CompensationKind`:

```text
NONE
EXACT
APPROXIMATE
MITIGATING
```

### `NONE`

No automated compensating action is supported.

### `EXACT`

The provider/effect has a compensating action intended to restore the relevant external state to the pre-effect state under documented assumptions.

"Exact" must not be claimed if irreversible external consequences remain.

### `APPROXIMATE`

A compensating action moves external state toward the prior state but may not reproduce it exactly.

### `MITIGATING`

A compensating action reduces harm without restoring the previous state.

---

## 3. `Compensation`

```text
Compensation {
  contract_version: "v1"
  compensation_id: opaque_id
  original_operation_id: opaque_id

  kind: CompensationKind
  state: CompensationState
  version: integer

  intent_digest: string
  arguments_mode: enum<INLINE | REFERENCE>
  arguments: optional<json>
  arguments_ref: optional<string>

  idempotency_identity: string

  requested_by: PrincipalRef
  policy_decision_id: optional<opaque_id>

  created_at: timestamp
  updated_at: timestamp
}
```

Canonical `CompensationState` is defined in `STATE_MACHINES.md`.

---

## 4. Eligibility

Compensation is legal only when:

1. provider/effect descriptor declares compensation kind other than `NONE`;
2. original operation state permits compensation;
3. policy/operator authorization permits it;
4. required original evidence/identifiers exist;
5. material compensation intent is durable before provider mutation.

The runtime must not infer compensation from a naming convention such as `create -> delete`.

---

## 5. Identity

Compensation has:

- its own `compensation_id`;
- its own stable idempotency identity;
- its own attempt IDs;
- its own external operation ID if provider returns one.

The compensation idempotency identity is distinct from the original effect identity but remains stable across retries of the same compensation.

---

## 6. `CompensationAttempt`

```text
CompensationAttempt {
  contract_version: "v1"
  compensation_attempt_id: opaque_id
  compensation_id: opaque_id
  attempt_number: integer
  state: AttemptState

  started_at: timestamp
  completed_at: optional<timestamp>

  provider_idempotency_key: optional<string>
  external_operation_id: optional<string>

  outcome: optional<EffectOutcome>
  evidence: optional<ProviderEvidence>
  error: optional<NormalizedError>
}
```

Unresolved `STARTED` compensation attempts are potentially unknown.

---

## 7. Exact compensation evidence

`EXACT` compensation may be marked successful only when provider/effect contract supplies evidence sufficient to establish the defined restored postcondition.

A provider returning HTTP 200 to a deletion call is not automatically proof of exact restoration if other relevant state remains.

---

## 8. Approximate and mitigating compensation

The operator/API/UI must expose the declared kind.

`COMPENSATED` means:

> the declared compensation objective was established as applied.

It does not upgrade an `APPROXIMATE` or `MITIGATING` action to exact rollback.

---

## 9. Compensation verification

Where supported, compensation verification uses the canonical verification model targeted at `COMPENSATION`.

If compensation outcome is ambiguous:

- parent operation -> `COMPENSATION_UNKNOWN`;
- compensation record -> `UNKNOWN`;
- no blind compensation retry unless safe-retry basis exists.

---

## 10. Original history

The original operation retains:

- original intent;
- original execution attempts;
- original evidence;
- original success/failure/unknown history;
- compensation reference.

Compensation appends new history.

Audit/query APIs should be able to present:

```text
original effect applied
then
exact compensation applied
```

rather than rewriting it as "no effect."

---

## 11. Compensation of failed operations

A parent `FAILED` operation may enter compensation only when there is known partial/mitigatable external state and the canonical capability/policy says compensation is meaningful.

A simple provider rejection with `NOT_APPLIED` should not create meaningless compensation.

---

## 12. Tests

Cover:

- unsupported compensation;
- exact success;
- approximate success;
- mitigating success;
- known compensation failure;
- compensation timeout -> unknown;
- provider succeeds then local crash;
- verification of compensation;
- duplicate compensation command;
- concurrent compensation attempts;
- stable idempotency identity across retries;
- original history preserved.
