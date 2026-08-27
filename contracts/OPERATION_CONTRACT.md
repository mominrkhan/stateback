# Operation Contract

**Status:** Canonical v1
**Owns:** operation identity, immutable intent, operation lifecycle aggregate, execution-attempt semantics.

---

## 1. Canonical enums

### `OperationState`

Exact values are owned by `STATE_MACHINES.md`:

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

### `EffectOutcome`

```text
APPLIED
NOT_APPLIED
UNKNOWN
```

Meaning:

- `APPLIED`: evidence establishes the requested mutation occurred.
- `NOT_APPLIED`: evidence establishes it did not occur.
- `UNKNOWN`: available evidence cannot establish either.

### `AttemptState`

```text
STARTED
COMPLETED
```

### `RiskLevel`

```text
LOW
MODERATE
HIGH
CRITICAL
```

---

## 2. `EffectRef`

Identifies the semantic effect implementation.

```text
EffectRef {
  provider: string
  action: string
  version: string
}
```

Requirements:

- `provider` is a stable provider identifier.
- `action` is stable within the provider adapter.
- `version` changes when the meaning/capability contract changes incompatibly.
- Human display labels are not identifiers.

Example:

```json
{
  "provider": "reference",
  "action": "create_resource",
  "version": "v1"
}
```

The example is illustrative, not a requirement that the first real provider use this action.

---

## 3. `PrincipalRef`

```text
PrincipalRef {
  type: enum<AGENT | HUMAN | SERVICE | OPERATOR>
  id: string
  display_name: optional<string>
}
```

`id` must be attributable within the deployment's authentication boundary.

No credential/token belongs in this structure.

---

## 4. `IntentEnvelope`

The durable intent identifies exactly what Stateback is responsible for.

```text
IntentEnvelope {
  effect: EffectRef
  arguments_mode: enum<INLINE | REFERENCE>
  arguments: optional<json>
  arguments_ref: optional<string>
  canonical_arguments_hash: string
  intent_digest: string
  requester: PrincipalRef
  requested_at: timestamp
  metadata: map<string, string>
}
```

Constraints:

- exactly one of `arguments` or `arguments_ref` is required according to `arguments_mode`;
- `canonical_arguments_hash` is over the material effect arguments after deterministic canonicalization;
- `intent_digest` binds the effect identity, material arguments, and other approval-relevant material specified by implementation contract;
- secrets must not be placed in metadata;
- material intent is immutable once policy authorization has begun.

The implementation must define one deterministic canonicalization algorithm and test it. Changing canonicalization in a way that changes approval/idempotency meaning is a compatibility change.

---

## 5. `Operation`

```text
Operation {
  contract_version: "v1"
  operation_id: opaque_id
  state: OperationState
  version: integer

  intent: IntentEnvelope
  risk_level: RiskLevel

  idempotency_identity: string

  current_policy_decision_id: optional<opaque_id>
  current_approval_id: optional<opaque_id>

  latest_attempt_id: optional<opaque_id>
  latest_verification_id: optional<opaque_id>
  compensation_id: optional<opaque_id>

  created_at: timestamp
  updated_at: timestamp
}
```

Normative requirements:

- `operation_id` is globally unique and immutable.
- `version` starts at a defined initial value and increases monotonically on every material lifecycle transition.
- `idempotency_identity` is stable across safe retries of this logical operation.
- state transitions must obey `STATE_MACHINES.md`.
- `updated_at` does not replace append-only audit history.
- pointers to "latest" records are convenience links; historical records remain durable.

The operation aggregate must not store plaintext provider credentials.

---

## 6. Idempotency identity

The canonical semantics are:

> One logical operation has one stable Stateback idempotency identity.

The concrete key format is implementation-defined, but it must:

- be deterministic/stable for the operation;
- not change per execution attempt;
- be safe to map/derive into provider-specific idempotency key formats;
- never be reused for a different material intent.

If a provider imposes length/character limits, the adapter may derive a provider key from the Stateback identity using a documented collision-resistant mapping. The mapping must be stable.

---

## 7. `ExecutionAttempt`

```text
ExecutionAttempt {
  contract_version: "v1"
  attempt_id: opaque_id
  operation_id: opaque_id
  attempt_number: integer
  state: AttemptState

  started_at: timestamp
  completed_at: optional<timestamp>

  provider_idempotency_key: optional<string>
  external_operation_id: optional<string>
  external_resource_ids: list<string>

  outcome: optional<EffectOutcome>
  evidence: optional<ProviderEvidence>
  error: optional<NormalizedError>

  correlation_id: optional<string>
}
```

Constraints:

- attempt is inserted as `STARTED` before provider mutation.
- `attempt_number` is monotonically increasing per operation and unique.
- completed attempt must have `outcome`.
- unresolved `STARTED` attempt after crash is not assumed `NOT_APPLIED`.
- attempts are append-only historical records; do not recycle IDs or numbers.
- provider key, if used, must map to the operation's stable idempotency identity.

---

## 8. `ProviderEvidence`

Provider evidence is intentionally generic enough to persist normalized evidence without exposing credentials.

```text
ProviderEvidence {
  source: enum<EXECUTION_RESPONSE | OPERATION_LOOKUP | READ_BACK | CUSTOM>
  provider: string
  observed_at: timestamp
  provider_status: optional<string>
  provider_request_id: optional<string>
  external_operation_id: optional<string>
  external_resource_ids: list<string>
  evidence_fields: json
  raw_reference: optional<string>
}
```

Requirements:

- `evidence_fields` must be sanitized.
- large/raw responses may be stored by durable reference according to security/data policy.
- secrets/auth headers must never be included.
- evidence is historical; newer evidence does not erase older evidence.

---

## 9. Operation creation preconditions

Creating an operation requires:

1. valid `EffectRef`;
2. valid material arguments;
3. attributable requester;
4. resolved risk level/effect descriptor;
5. durable ability to persist the operation.

A consequential provider call is forbidden if operation creation fails.

---

## 10. Operation status semantics

API/SDK/UI representations must not collapse operation states into a single boolean.

At minimum clients must be able to distinguish:

- waiting for policy/approval;
- ready/executing;
- verifying;
- unknown;
- succeeded;
- failed;
- denied/cancelled;
- compensation in progress/unknown/succeeded/failed;
- manual intervention.

A convenience high-level category may be added, but canonical state must remain available.

---

## 11. Immutability and changes

A material intent change creates a new logical operation or a canonical re-authorization flow that results in a new immutable intent revision. v1 does not support mutating the original intent in place.

Non-material metadata may be updated only if it cannot affect:

- provider call;
- approval;
- idempotency;
- policy;
- audit meaning.

---

## 12. Serialization and persistence tests

Implementations must test:

- every canonical enum round-trips;
- unknown enum value is rejected by strict internal readers;
- operation ID does not change;
- intent digest is stable for identical canonical input;
- materially different intent changes digest;
- attempt numbering uniqueness under concurrency;
- completed attempts require outcome;
- `UNKNOWN` round-trips distinctly from `FAILED` operation state.
