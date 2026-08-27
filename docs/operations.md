# Operator guide

PostgreSQL records are the authoritative source for operation state and audit
history. Never infer completion from a worker exit, JetStream acknowledgement,
HTTP timeout, UI state, or missing log line.

## Backup and restore

Take consistent PostgreSQL backups using the deployment's supported PostgreSQL
tooling and test restoration into an isolated environment. Protect backups as
sensitive production data. Preserve JetStream storage for pending work and
quarantine diagnostics, but do not treat it as a substitute for PostgreSQL.

For the Compose topology, use PostgreSQL 16 `pg_dump` in custom format and
`pg_restore --exit-on-error` into a newly created isolated database. Verify the
`alembic_version` row and audit/operation counts before accepting the backup.
Do not restore over a running production database. `deploy/verify-compose.sh`
performs this procedure against disposable volumes as release evidence.

After restore, keep execution workers stopped while operators compare durable
operation state with external provider evidence. Operations that may have
crossed a provider boundary must remain unknown or enter verification; never
blindly replay them because the restored database predates a response.

## Incident response

On suspected credential compromise, stop new API submission, relay, and worker
processes; revoke or rotate the affected credential; preserve PostgreSQL,
JetStream, and audit evidence; then inspect unknown/in-flight operations before
resuming. Do not broaden credentials or retry through a security boundary.

Poison or exhausted work is published to `stateback.quarantine.v1` before the
original delivery is terminated. Invalid payload bytes are represented only by
size and SHA-256. Valid v1 work includes a bounded canonical replay payload.
The isolated `STATEBACK_QUARANTINE_V1` stream has one exact operator consumer;
long-running API, relay, and worker processes do not receive its credential.
Inspect without acknowledgement:

```text
docker compose -f deploy/compose.yaml -f deploy/quarantine.compose.yaml \
  run --rm quarantine quarantine-inspect
```

After resolving the cause and checking PostgreSQL, replay only by confirming
the displayed `message_id`:

```text
docker compose -f deploy/compose.yaml -f deploy/quarantine.compose.yaml \
  run --rm -e STATEBACK_QUARANTINE_REPLAY_MESSAGE_ID=<message-id> \
  quarantine quarantine-replay
```

An invalid payload cannot be replayed. Acknowledge it only by confirming its
displayed `payload_sha256`:

```text
docker compose -f deploy/compose.yaml -f deploy/quarantine.compose.yaml \
  run --rm -e STATEBACK_QUARANTINE_DISCARD_SHA256=<payload-sha256> \
  quarantine quarantine-discard
```

Successful replay publishes the canonical work message before acknowledging
its diagnostic; the worker still reloads PostgreSQL and may safely no-op stale
work.

Deleting or purging the release stream is denied by its managed configuration.
If either managed stream/consumer has incompatible subjects, retention,
storage, replica count, message size, delivery, or delete/purge controls, relay
and worker fail startup instead of silently changing it.

If JetStream storage is lost after publication, the relay discovers old latest
published work whose canonical operation still requires the command. It appends
a new `PENDING` outbox event and an `outbox.diagnostic.v1` audit event, then uses
the normal publication path. Automatic rediscovery is limited by
`STATEBACK_OUTBOX_RECOVERY_MAX_REPUBLISHES` (default 3) per operation version
and command. An authorized operator transition starts a new bounded recovery
episode by advancing the operation version. On exhaustion,
`messaging.recovery_exhausted` is recorded once for that episode and no
more automatic messages are created. The same transaction moves the operation
to `MANUAL_INTERVENTION`, so operators can find it with the normal state filter.
Inspect the operation, PostgreSQL, JetStream, and transition audit before using
an available operator verification or compensation action. No public
original-effect safe-retry control is released in 0.1.0; when neither action is
available, retain `MANUAL_INTERVENTION` and follow deployment-specific supervised
remediation without rewriting outbox history.
Never reset a `PUBLISHED` row to `PENDING`; inspect the audit chain and current
operation state before any additional manual replay.

## Shutdown

Compose sends `SIGTERM`. Relay and worker stop fetching new work, drain NATS,
and rely on durable PostgreSQL/JetStream state for safe restart. A provider call
interrupted after transmission can remain `UNKNOWN`; restart never converts it
to failure or retries it blindly.

Readiness drops when relay or worker loses NATS and when their PostgreSQL check
fails. After either service recovers, inspect `UNKNOWN`, pending, redelivered,
and quarantined work plus provider evidence before authorizing any manual
replay.
