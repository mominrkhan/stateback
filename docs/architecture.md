# Architecture

This page describes the architecture implemented by the current Stateback
repository. Normative component ownership lives in `SYSTEM_OVERVIEW.md`; exact
lifecycle edges live in `STATE_MACHINES.md`.

## System boundary

Stateback sits between an agent/application and a consequential provider
effect:

```text
REST / Python SDK / MCP
          |
          v
 application service
 policy + approval
          |
          v
     PostgreSQL
 journal + audit + outbox
          |
          v
 outbox relay -> NATS JetStream -> worker
                                  |
                           reload PostgreSQL
                                  |
                                  v
                              runtime
                                  |
                                  v
                         provider adapter
                                  |
                                  v
                         external provider
```

PostgreSQL is authoritative for Stateback lifecycle state. The external
provider is authoritative for its resources. JetStream coordinates work but is
not the operation journal. Optional semantic summaries are advisory only.

## Durable submission and authorization

REST and MCP enter the shared application service; the synchronous Python SDK
uses the REST API. Submission validates the request and effect, persists the
operation and immutable material intent, evaluates policy, and records the
result before provider execution becomes legal.

Policy returns `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`. An approval is a durable
record bound to the operation identity/version, intent digest, policy decision,
approver, and expiry context. It is not a generic boolean and cannot authorize
changed intent.

Lifecycle mutation is centralized in the transition service. A listed state
edge is necessary but not sufficient: expected version, child records,
evidence, policy/approval binding, retry safety, and compensation consistency
are also checked where applicable.

## Transactional outbox

When a transition requires asynchronous work, Stateback commits the state
change, audit event, and outbox row together in PostgreSQL. The relay publishes
the durable outbox record later. Publication or acknowledgement races may
produce duplicates, so workers reload PostgreSQL and process a command only if
it remains applicable.

JetStream delivery never authorizes stale work or moves state backward.

## Provider execution boundary

Provider network I/O is deliberately outside the PostgreSQL transaction:

```text
load current operation
        |
persist EXECUTING claim + STARTED attempt
        |
      COMMIT
        |
        | crash gap
        v
invoke provider
        |
        | crash gap
        v
persist COMPLETED attempt + evidence/error
        |
      COMMIT
        |
apply legal lifecycle transition
```

This avoids holding a database transaction across network I/O and exposes the
unavoidable distributed-systems ambiguity. If the provider applies a mutation
before Stateback persists the result, recovery must verify or reconcile; it
must not infer non-application or blindly replay a non-idempotent effect.

## Providers and recovery

Provider adapters declare effect-specific capability through an
`EffectDescriptor`: mutability, risk, idempotency, verification, compensation,
external identity, and immediate-evidence semantics. Adapters validate and
return normalized evidence. They do not own operation transitions.

The real mutating effects registered by the release composition are:

```text
github.create_issue.v1
github.create_issue_comment.v1
github.add_label.v1
github.create_pull_request.v1
github.merge_pull_request.v1
```

Each descriptor states its own risk, idempotency, verification, compensation,
and external-identity semantics. Creation actions use positive operation-marker
verification, label addition is naturally state-idempotent, and merge binds an
expected head SHA. Conclusive validation/rejection paths can prove
`NOT_APPLIED`; transport ambiguity or malformed apparent success remains
`UNKNOWN`.

Stateback places an operation marker in the issue body. Direct read-back or
search that finds the marker is positive evidence. Not observing the marker is
inconclusive. Compensation closes the issue; closing is mitigation, not exact
rollback.

Recovery uses durable attempts and provider evidence to verify, reconcile,
establish a safe retry basis, or escalate. Automatic recovery is bounded.
Compensation has its own durable intent, attempts, evidence, uncertainty,
verification/reconciliation, and audit history.

## Current delivery topology

The work stream/consumer are `STATEBACK_V1` and `stateback-worker-v1`. The
quarantine stream/consumer are `STATEBACK_QUARANTINE_V1` and
`stateback-quarantine-operator-v1`. The work consumer uses explicit
acknowledgement, a bounded delivery count, `max_ack_pending = 1`, and one-message
pulls. This is a correctness-first serialized worker topology, not a
high-throughput concurrency claim.

Poison or exhausted work can be inspected, replayed with the expected original
message ID, or discarded with the expected payload SHA-256. These confirmation
requirements prevent an operator command from acting on a different payload.

## Local and hardened deployment

The root `compose.yaml` starts development infrastructure only: PostgreSQL
16.15 and NATS 2.12.6 with JetStream. API, relay, and worker processes are run
separately.

The hardened base topology in `deploy/compose.yaml` includes PostgreSQL,
migrations/database privileges, NATS, JetStream initialization, API, relay,
worker, and frontend. It uses non-root users, read-only filesystems, dropped
capabilities, `no-new-privileges`, secret files, a private backend network, a
separate provider-egress network, persistent database/broker volumes, and
digest-pinned PostgreSQL/NATS images.

Real GitHub execution is enabled with the checked-in
`deploy/github.compose.yaml` overlay. The overlay mounts
`STATEBACK_GITHUB_TOKEN_FILE` only into the worker and gives the API a
non-secret configured-capability signal. The base Compose file intentionally
does not mount the GitHub token by itself.

See the [deployment guide](deployment.md) for the exact production procedure.

## Current limitations

- Real provider breadth is limited to the five-effect GitHub workflow.
- The primary worker consumer is serialized.
- Operator queries are bounded operational reads, not an analytics system.
- The migration history contains the journal baseline and query indexes.
- The local `stateback dev` composition is single-project and development-only;
  production remains the separately hardened Compose topology.

None of these limits changes the authority model: PostgreSQL remains canonical,
`UNKNOWN` remains explicit, and provider guarantees remain effect-specific.
