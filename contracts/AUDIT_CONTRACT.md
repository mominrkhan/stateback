# Audit Contract

**Status:** Canonical v1
**Owns:** append-only material history needed to explain operation lifecycle and operator decisions.

---

## 1. Purpose

Stateback must be able to answer what happened without reconstructing truth from application logs.

The audit stream is a durable explanation of Stateback's knowledge and decisions.

It is not a replacement for the canonical operation aggregate; it is the append-only history supporting that aggregate.

---

## 2. `AuditEvent`

```text
AuditEvent {
  contract_version: "v1"
  audit_event_id: opaque_id
  operation_id: opaque_id
  sequence: integer

  event_type: string

  from_state: optional<OperationState>
  to_state: optional<OperationState>
  operation_version: integer

  actor: optional<PrincipalRef>
  reason_code: string
  data: json

  correlation_id: optional<string>
  created_at: timestamp
}
```

---

## 3. Sequence semantics

`sequence` is monotonically increasing per operation.

Two material events for the same operation must not share the same sequence.

The exact allocation mechanism is implementation-defined but must be concurrency-safe.

---

## 4. Atomic transition audit

When an event describes an operation state transition:

- operation state/version update;
- corresponding audit event;
- required outbox insert

must be committed in one PostgreSQL transaction.

It must be impossible for the durable operation to show a state transition with no corresponding material audit event because of a process crash.

---

## 5. Event-type categories

The exact event-type strings may be implemented as versioned canonical identifiers, but the audit model must cover at least:

- operation created;
- policy evaluated;
- approval requested;
- approval decision;
- state transition;
- execution attempt started;
- execution evidence recorded;
- verification started/completed;
- reconciliation decision;
- compensation requested/attempted/result;
- operator action;
- outbox/publication diagnostic if retained here;
- manual intervention reason;
- security-relevant control decision.

Avoid one generic `UPDATED` event with an opaque blob.

---

## 6. Data minimization

Audit data may contain:

- safe identifiers;
- reason codes;
- redacted provider evidence;
- state transition metadata;
- external non-secret IDs;
- policy explanation.

Audit data MUST NOT contain:

- access tokens;
- passwords;
- private keys;
- authorization headers;
- full credential objects;
- secrets embedded in provider responses.

Sensitive provider payloads should use a secure durable reference if retention is required.

---

## 7. Immutability

Audit events are append-only.

Do not:

- update old event content to match current state;
- delete failure events after eventual success;
- erase original-effect history after compensation;
- rewrite `UNKNOWN` history after later reconciliation.

Corrections are new events that reference/reason about prior history.

---

## 8. Operator attribution

Every privileged manual action must include an attributable actor.

Examples:

- approval/rejection;
- request verification;
- request safe retry;
- request compensation;
- move to manual intervention where explicitly supported;
- record manual evidence.

---

## 9. Query/reconstruction

Given an `operation_id`, operators should be able to retrieve ordered audit history and understand:

1. original intent;
2. policy/approval;
3. each attempt;
4. provider evidence;
5. unknown periods;
6. verification/recovery;
7. compensation;
8. operator actions;
9. final/current disposition.

The audit API may enrich events with current data, but raw durable events must remain accessible for debugging/forensics according to retention policy.

---

## 10. Integrity

At minimum, database constraints and transaction design must prevent:

- duplicate sequence within operation;
- audit event referencing nonexistent operation;
- transition event with impossible version relationship.

Cryptographic audit-chain signing is not required by v1 unless a later security decision introduces it.

---

## 11. Tests

- transition + audit atomicity;
- rollback leaves neither transition nor event;
- sequence uniqueness under concurrent writers;
- original unknown event remains after reconciliation;
- compensation does not rewrite original effect;
- secret-redaction tests;
- operator actor required for privileged actions.
