# Messaging and Transactional Outbox Contract

**Status:** Canonical v1
**Owns:** database-to-message coordination, outbox records, JetStream work-message semantics, stale/duplicate handling.

---

## 1. Architectural rule

PostgreSQL is authoritative for Stateback lifecycle state.

NATS JetStream is used for durable coordination and delivery.

A message never overrides canonical PostgreSQL state.

---

## 2. Why an outbox is required

The following sequence is unsafe:

```text
commit operation READY
publish message
```

because a crash between the two can commit ready work that is never published.

The inverse order is also unsafe:

```text
publish message
commit operation READY
```

because a worker may receive work that the database does not yet authorize.

Stateback therefore uses a transactional outbox.

---

## 3. `OutboxEvent`

```text
OutboxEvent {
  contract_version: "v1"
  event_id: opaque_id
  state: enum<PENDING | PUBLISHED>

  aggregate_type: "operation"
  aggregate_id: opaque_id
  operation_version: integer

  command: WorkCommand
  created_at: timestamp
  published_at: optional<timestamp>

  correlation_id: optional<string>
}
```

The outbox row is inserted in the same PostgreSQL transaction as the state transition requiring asynchronous work.

---

## 4. Canonical `WorkCommand`

Initial v1 commands are:

```text
EXECUTE
VERIFY
COMPENSATE
```

Meaning:

### `EXECUTE`

Evaluate whether the operation is currently eligible for original effect execution.

### `VERIFY`

Evaluate whether verification/reconciliation is currently legal and perform it if appropriate.

### `COMPENSATE`

Evaluate whether compensation work is currently legal and perform it if appropriate.

These are commands to **reevaluate current durable state**, not instructions to blindly call a provider.

---

## 5. `WorkMessageV1`

```text
WorkMessageV1 {
  contract_version: "v1"
  message_id: opaque_id
  outbox_event_id: opaque_id

  operation_id: opaque_id
  expected_operation_version: integer
  command: WorkCommand

  correlation_id: optional<string>
  created_at: timestamp
}
```

Messages SHOULD remain small.

Do not duplicate complete operation state or provider arguments in JetStream messages when workers can load them from PostgreSQL.

---

## 6. Publication semantics

Outbox publisher:

1. selects a `PENDING` outbox row using concurrency-safe claiming;
2. serializes `WorkMessageV1`;
3. publishes to the correct JetStream subject;
4. receives provider acknowledgment from NATS;
5. marks outbox row `PUBLISHED`.

A crash after step 3 and before step 5 may publish the same event again.

Therefore duplicate message publication is expected and safe.

---

## 7. JetStream delivery semantics

Consumers MUST be designed for at-least-once delivery.

The worker must tolerate:

- duplicate delivery;
- redelivery after ack timeout;
- out-of-order arrival of stale work;
- worker restart;
- consumer restart;
- delayed delivery.

No exactly-once external-effect claim follows from JetStream durability.

---

## 8. Worker receive algorithm

For every message:

```text
validate schema/version
        |
load operation from PostgreSQL
        |
compare message expected version/current state
        |
is command still applicable?
   |              |
  no             yes
   |              |
ack/no-op      invoke canonical runtime
                  |
             persist outcome/state
                  |
                 ack
```

If the runtime returns an infrastructure condition that should be retried by message redelivery, the worker may leave message unacked/nak according to bounded delivery policy.

If the operation itself reaches `UNKNOWN` or `FAILED`, message retry must not be used as a hidden provider-effect retry mechanism.

---

## 9. Stale version semantics

If:

```text
message.expected_operation_version < operation.version
```

the worker MUST reload/reevaluate.

Usually the message is stale and can be acknowledged as a no-op if its command is no longer legal.

If version mismatch exposes a recoverable current state that still needs the same semantic work, the worker may invoke the runtime based on **current** state, not force the old transition.

---

## 10. Subject naming

Exact subject names are an implementation detail until public operational compatibility requires them.

Subject names MUST:

- be namespaced to Stateback;
- separate incompatible contract versions if needed;
- not encode secrets;
- not be treated as lifecycle truth.

A reasonable private implementation may use one work subject with command in payload.

---

## 11. Consumer acknowledgement

Ack timing must be downstream of durable Stateback handling.

Examples:

### State transition/evidence persisted, then crash before ack

Message redelivers. Worker reloads newer PostgreSQL state and safely no-ops or continues legal recovery.

### Provider effect may have happened, DB result not persisted

Worker dies before ack. Redelivery does **not** simply call provider again. Reloaded unresolved `EXECUTING`/attempt state routes through unknown-outcome recovery.

---

## 12. Poison messages

A permanently invalid message must not be redelivered forever.

Examples:

- unsupported contract version;
- malformed required field;
- impossible command enum;
- reference to nonexistent operation after defined grace/diagnostic policy.

The deployment should quarantine/dead-letter or otherwise surface such messages with diagnostic metadata.

A poison-message path MUST NOT mutate the referenced operation speculatively.

---

## 13. NATS outage

If JetStream is unavailable:

- database transitions requiring future work can still atomically insert outbox rows if policy permits;
- publisher retries later;
- pending work remains discoverable from PostgreSQL;
- Stateback must not mark work executed merely because an outbox record exists.

---

## 14. Outbox cleanup

Published outbox records may be archived/expired operationally only after required audit/debug retention and with no loss of canonical operation history.

Outbox is transport history, not the canonical audit log.

---

## 15. Tests

Required integration coverage:

- DB commit + publish success;
- DB commit + NATS unavailable;
- publish success + crash before `PUBLISHED`;
- duplicate published event;
- duplicate consumer delivery;
- stale message;
- concurrent workers;
- worker crash after provider effect/before persistence;
- worker crash after persistence/before ack;
- NATS restart;
- unsupported message version;
- poison message bounded handling.
