# Stateback System Overview

**Status:** Canonical
**Purpose:** Define Stateback's major components, responsibilities, trust boundaries, and data/control flow.

Exact lifecycle transitions are owned by `STATE_MACHINES.md`. Exact data/interface semantics are owned by `contracts/`.

---

## 1. Architectural thesis

Stateback is a transactional safety layer around external effects performed by AI agents.

The architecture is intentionally split between:

1. **authoritative durable state** — PostgreSQL;
2. **effect semantics and decision logic** — deterministic Stateback services;
3. **provider-specific evidence collection** — provider adapters;
4. **asynchronous coordination** — NATS JetStream;
5. **policy and approval** — explicit control plane;
6. **operator visibility and recovery** — audit-backed APIs/UI.

The central design rule is:

> Stateback decides what is legal from durable state and declared semantics, then asks provider adapters to perform or observe external actions. Provider adapters return evidence; they do not own lifecycle truth.

---

## 2. High-level architecture

```text
Agent / Application / MCP / SDK
              |
              v
      +------------------+
      |  Public Boundary |
      | API / SDK / MCP  |
      +---------+--------+
                |
                v
      +------------------+
      | Operation Service |
      +---------+---------+
                |
       +--------+---------+
       |                  |
       v                  v
+-------------+      +-------------+
| Policy      |      | Capability  |
| Engine      |      | Registry    |
+------+------+      +------+------+
       |                    |
       +---------+----------+
                 |
                 v
        +------------------+
        | Transition/       |
        | Runtime Service   |
        +----+---------+----+
             |         |
             |         +------------------+
             |                            |
             v                            v
      +-------------+             +---------------+
      | PostgreSQL  |             | Provider      |
      | Journal +   |             | Adapter       |
      | Audit       |             +-------+-------+
      +------+------+                     |
             |                            v
             |                    External Provider
             |
             v
      Transactional Outbox
             |
             v
      +-------------+
      | NATS        |
      | JetStream   |
      +------+------+
             |
             v
      +-------------+
      | Workers     |
      +------+------+
             |
             +----> reload PostgreSQL state
             +----> call Runtime Service
```

---

## 3. Authoritative systems

### 3.1 PostgreSQL

PostgreSQL is authoritative for Stateback-owned durable lifecycle information, including:

- operations;
- immutable/material intent snapshot or durable reference;
- operation state and version;
- policy decisions;
- approvals;
- execution attempts;
- provider evidence;
- external operation/resource identifiers;
- verification/reconciliation attempts;
- compensation records;
- append-only audit events;
- transactional outbox records;
- operator actions;
- recovery disposition.

A worker must be able to restart and reconstruct the legal next action without relying on in-memory state.

### 3.2 External provider

The provider is authoritative for its own external state.

PostgreSQL can authoritatively state:

> Stateback has evidence X and therefore currently classifies the operation as Y.

It cannot make a provider resource exist merely by storing `SUCCEEDED`.

### 3.3 JetStream

JetStream is authoritative for its own delivery/consumer state, but not for Stateback operation truth.

A message is a coordination artifact. Its lifecycle information may be stale by the time it is consumed.

---

## 4. Core components

## 4.1 Public boundary

Includes:

- HTTP/service API;
- developer SDK;
- MCP interface;
- internal application-service entry points.

Responsibilities:

- authenticate/identify caller where applicable;
- validate public request shape;
- translate request into canonical operation intent;
- return durable operation identity;
- expose status/audit information;
- never bypass operation creation/policy/journaling for managed mutating effects.

Does not own:

- provider retry logic;
- lifecycle transition policy;
- provider credentials;
- direct state-machine mutation.

---

## 4.2 Operation Service

The Operation Service owns creation and high-level orchestration of an operation.

Responsibilities:

- create immutable operation identity;
- canonicalize and persist material intent;
- compute/store intent digest;
- resolve effect descriptor/capabilities;
- invoke policy evaluation;
- create required audit events;
- transition to the next legal lifecycle state;
- schedule asynchronous work through the outbox when needed.

It does not directly implement provider-specific HTTP/SDK calls.

---

## 4.3 Policy Engine

Responsibilities:

- evaluate canonical policy inputs;
- return `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`;
- attach obligations such as required verification or automatic-recovery constraints where contracts allow;
- create explainable reason codes/metadata;
- remain deterministic for equivalent policy inputs/configuration;
- never call the provider as part of authorization.

Policy and provider mechanics are intentionally separate.

---

## 4.4 Approval Service

Responsibilities:

- persist approval requests;
- bind approval to `operation_id`, `operation_version`, and `intent_digest`;
- record approver identity and decision;
- detect stale/mismatched approvals;
- trigger a legal transition after approval/rejection/expiry.

Changing material intent invalidates prior approval.

---

## 4.5 Capability Registry

The registry exposes canonical effect metadata derived from provider adapter declarations.

Examples:

- mutation/read-only;
- risk level;
- idempotency mode;
- verification mode;
- compensation kind;
- external operation ID support;
- whether an immediate response can conclusively establish `APPLIED` or `NOT_APPLIED`.

Capability declarations are part of the provider contract and are testable claims.

---

## 4.6 Transition Service

The Transition Service is the only ordinary component permitted to apply canonical lifecycle transitions.

Responsibilities:

- validate current state;
- validate requested transition;
- validate transition preconditions;
- apply concurrency/version protection;
- update operation state/version;
- append audit event atomically;
- write outbox record atomically when the transition requires async work.

Provider adapters and UI code must not mutate lifecycle fields directly.

---

## 4.7 Execution Runtime

Responsibilities:

- claim an operation that is legally ready for execution;
- create the durable attempt before crossing provider mutation boundary;
- construct provider execution context;
- call provider adapter;
- normalize adapter evidence;
- persist material evidence/external identifiers;
- select the next legal transition;
- route ambiguous outcomes to verification/recovery;
- enforce safe-retry rules;
- never use generic exception retry around mutating provider calls.

The synchronous runtime is the semantic kernel. Distributed workers call into the same runtime rather than reimplementing it.

---

## 4.8 Provider Adapter

A provider adapter translates canonical Stateback effect semantics to one provider.

Responsibilities:

- declare capabilities per effect/action;
- validate provider-specific request material before mutation;
- perform execution;
- pass stable Stateback idempotency identity to provider when supported;
- normalize provider result to canonical `EffectOutcome`;
- persistable external identity/evidence returned via contract;
- implement verification/reconciliation when supported;
- implement compensation when supported;
- sanitize error/evidence fields.

Adapters MUST NOT:

- directly update operation state;
- silently retry mutating calls;
- invent idempotency guarantees;
- map a timeout to `NOT_APPLIED` without evidence;
- log secrets.

---

## 4.9 Verification/Reconciliation Service

Responsibilities:

- determine whether a provider/effect supports verification;
- create persisted verification attempts;
- call adapter verification/lookup/read-back;
- normalize evidence to `APPLIED`, `NOT_APPLIED`, or `UNKNOWN`;
- apply legal recovery transition;
- permit retry only when a canonical safety basis exists;
- remain safe under repeat invocation.

Verification is evidence gathering. Reconciliation applies that evidence to Stateback's durable knowledge.

---

## 4.10 Compensation Service

Responsibilities:

- determine compensation eligibility from declared capability + policy;
- persist compensation intent before external compensation;
- assign its own attempt identity;
- execute through adapter compensation boundary;
- normalize evidence;
- verify/reconcile compensation when supported;
- preserve original operation history;
- surface approximate/mitigating nature explicitly.

Compensation is not an update that changes the original operation result to "never happened."

---

## 4.11 PostgreSQL Journal Repository

Responsibilities:

- transactionally persist canonical aggregates;
- provide concurrency-safe transition primitives;
- expose recovery scans;
- persist outbox records;
- preserve append-only audit;
- support migrations with Alembic.

The repository layer must not hide meaningful transaction boundaries.

---

## 4.12 Transactional Outbox

Purpose:

Eliminate an unsafe database/message dual write.

When a state transition requires asynchronous work:

```text
BEGIN PostgreSQL transaction
  validate transition
  update operation
  append audit event
  insert outbox event
COMMIT
```

A separate relay publishes the durable outbox event to JetStream.

If publish fails, the outbox row remains discoverable and can be retried.

After successful publish, publication status is recorded idempotently.

The outbox does not guarantee exactly-once message delivery; it guarantees the need to publish is durably coupled to the state transition.

---

## 4.13 JetStream Relay and Workers

### Relay

- reads unpublished outbox records;
- publishes versioned messages;
- records publication;
- tolerates duplicate publication.

### Worker

On message receipt:

1. validate message version/schema;
2. load operation from PostgreSQL;
3. compare current operation version/state with message intent;
4. determine whether work is still legal;
5. call canonical runtime service;
6. persist result;
7. acknowledge according to failure semantics.

A stale or duplicate message usually becomes a no-op after canonical-state reload.

---

## 4.14 Audit Service / Query Model

Stateback should make operation reconstruction easy without turning logs into truth.

The audit/query layer should expose:

- intent summary;
- actor;
- policy decision;
- approval;
- lifecycle timeline;
- execution attempts;
- idempotency identity metadata;
- provider evidence;
- external identity;
- verification/reconciliation;
- compensation;
- operator interventions.

The query model may denormalize for read performance only if canonical records remain authoritative.

---

## 4.15 Operator Control Plane

Provides carefully authorized actions such as:

- approve/reject;
- request verification/reconciliation;
- request safe retry when the runtime proves it is eligible;
- request compensation when eligible;
- acknowledge/escalate manual intervention.

Operator actions:

- must not bypass state-machine rules;
- must be attributable;
- must create audit events;
- must be subject to authorization.

---

## 4.16 Optional Semantic-AI Layer

Optional local semantic AI (for example Ollama/Qwen3 in development) may:

- classify or summarize provider evidence;
- help explain operations;
- suggest policy context;
- assist operator triage.

It must remain advisory.

It cannot independently establish external truth, authorize effects, or apply lifecycle transitions.

---

## 5. Core data model

The exact contracts are under `contracts/`. Conceptually, the durable model includes:

```text
Operation
  operation_id
  state
  version
  intent
  intent_digest
  effect_descriptor
  requester
  risk_level
  idempotency_identity
  timestamps

PolicyDecision
Approval

ExecutionAttempt[]
  attempt_id
  started_at
  completed_at
  provider evidence
  external operation ID
  normalized effect outcome
  error metadata

VerificationAttempt[]
Compensation[]
AuditEvent[]
OutboxEvent[]
```

The design intentionally keeps:

- logical operation identity;
- individual provider attempts;
- verification attempts;
- compensation attempts

as separate concepts.

---

## 6. Canonical control flow

## 6.1 Operation creation

```text
request
  |
validate + identify actor
  |
resolve effect descriptor
  |
persist operation intent (PENDING_POLICY)
  |
audit
  |
evaluate policy
```

No provider mutation occurs before the durable operation exists.

## 6.2 Policy allow

```text
PENDING_POLICY
   |
 policy ALLOW
   |
 READY
   |
 outbox work record
```

## 6.3 Approval required

```text
PENDING_POLICY
   |
 REQUIRE_APPROVAL
   |
 AWAITING_APPROVAL
   |
 approval bound to intent digest
   |
 READY or DENIED/CANCELLED
```

## 6.4 Execution

```text
READY
  |
atomic claim + attempt creation
  |
EXECUTING
  |
provider call
  |
normalize evidence
  |
+----------------+----------------+
|                |                |
APPLIED      NOT_APPLIED       UNKNOWN
|                |                |
verify if     retry/fail          |
required         |                |
|                |                |
SUCCEEDED     READY/FAILED       UNKNOWN
                                  |
                              verification
```

Exact transitions are in `STATE_MACHINES.md`.

## 6.5 Recovery

```text
UNKNOWN
   |
create verification attempt
   |
external lookup/read-back
   |
APPLIED / NOT_APPLIED / UNKNOWN
   |
converge / safe retry / remain unresolved
```

## 6.6 Compensation

```text
eligible original operation
   |
persist compensation intent
   |
COMPENSATING
   |
provider compensation
   |
evidence / verification
   |
COMPENSATED
or COMPENSATION_UNKNOWN
or COMPENSATION_FAILED
```

---

## 7. Concurrency model

Stateback assumes multiple workers and duplicate messages are normal.

Concurrency correctness is anchored in PostgreSQL.

At minimum:

- operations have a monotonic version;
- transitions validate expected current state/version;
- provider execution claims are serialized;
- stale work cannot advance an incompatible lifecycle;
- outbox publication is idempotent;
- retries are separate durable attempts but share logical operation/idempotency identity.

The system must not depend on "only one worker will probably receive this."

---

## 8. Persistence boundaries

A provider call can never be part of the same ACID transaction as an arbitrary external API.

Therefore Stateback deliberately persists before and after the boundary.

Important durable points include:

1. operation intent;
2. policy/approval;
3. attempt start;
4. provider evidence;
5. lifecycle transition;
6. required outbox publication;
7. verification/compensation attempts.

Every crash between these points must have explicit recovery semantics.

---

## 9. Failure philosophy

When the process crosses an external boundary:

> A missing local result is not evidence that nothing happened.

The runtime should be conservative:

- if known not applied, it may retry according to policy;
- if applied, it progresses/compensates according to policy;
- if unknown, it verifies/reconciles or escalates;
- if the provider cannot provide evidence and no safe idempotency basis exists, manual intervention may be the correct terminal disposition.

This is a feature, not a failure of abstraction.

---

## 10. Security boundaries

High-value trust boundaries include:

- public caller -> Stateback API;
- operator -> control plane;
- Stateback -> provider credentials;
- worker -> PostgreSQL;
- worker -> JetStream;
- CI/release -> package registries;
- semantic AI -> advisory output only.

Credentials must be passed by secure configuration/secret mechanisms and not embedded in durable audit payloads.

Approval is authorization, not authentication; both must be designed explicitly.

---

## 11. Deployment shape

The initial production-shaped deployment may contain:

- Stateback API/service;
- Stateback worker(s);
- PostgreSQL;
- NATS with JetStream;
- optional outbox relay if not embedded;
- optional operator frontend;
- optional local semantic model.

The core must remain self-hostable.

Scaling should preserve semantics before optimizing throughput.

---

## 12. Non-architecture

The following are intentionally not defined by this file unless another canonical artifact decides them:

- final cloud vendor;
- final Kubernetes requirement;
- final public hosting model;
- final pricing;
- final first provider integration;
- final UI framework;
- exact Python module names;
- exact table names;
- exact REST path names.

Implementation may choose private structure consistent with contracts, but public or durable decisions require canonical ownership.
