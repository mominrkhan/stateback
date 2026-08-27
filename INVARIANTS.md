# Stateback Correctness Invariants

**Status:** Canonical
**Purpose:** Define properties that MUST remain true regardless of implementation details.

Implementation code may change. These properties may not change accidentally.

Every implementation phase and reviewer MUST identify the invariants it touches and provide machine evidence where practical.

---

## INV-001 — Durable intent precedes consequential execution

A consequential provider mutation MUST NOT be attempted unless the corresponding Stateback operation and material intent are durably recorded in PostgreSQL.

**Why:** A crash after an unjournaled side effect would leave Stateback unable to know what it intended to do.

**Required evidence:**

- persistence tests;
- crash-boundary tests;
- code path analysis proving provider mutation is downstream of durable operation creation.

---

## INV-002 — Operation identity is immutable and unique

Each logical effect has one immutable `operation_id`.

An `operation_id` MUST NOT:

- be reused for a different material intent;
- change across retries;
- change across verification/reconciliation;
- be replaced merely because a worker restarts.

**Why:** Recovery and deduplication require stable logical identity.

---

## INV-003 — Material intent is immutable after authorization/execution begins

Once policy evaluation has authorized an intent, material effect identity or arguments MUST NOT be changed in place.

A materially changed request MUST create a new operation or trigger a new policy/approval cycle according to contract.

**Why:** Otherwise an approval or idempotency identity could authorize one action and execute another.

---

## INV-004 — Idempotency identity is stable across retries of one logical effect

If an effect uses an idempotency identity, the same logical operation MUST use the same idempotency identity across every safe retry.

A new attempt MUST NOT silently generate a new provider idempotency key for the same logical effect.

**Why:** Changing the key defeats provider deduplication.

---

## INV-005 — PostgreSQL is authoritative for Stateback lifecycle state

Canonical operation, attempt, policy, approval, audit, recovery, compensation, and outbox state MUST be recoverable from PostgreSQL.

NATS messages, process memory, caches, logs, UI state, and model output MUST NOT be the only authoritative representation of lifecycle truth.

**Why:** Stateback must survive worker/process/messaging restarts.

---

## INV-006 — External state and Stateback state remain distinct

Stateback MUST NOT infer external truth solely from local lifecycle state.

Claims such as "effect applied" MUST be supported by provider execution evidence or verification evidence under the relevant adapter contract.

**Why:** A local commit does not mutate the external provider, and an external mutation can occur without a successful local commit.

---

## INV-007 — Unknown is preserved as unknown until evidence resolves it

If available evidence cannot establish whether an external mutation occurred, the canonical outcome MUST remain `UNKNOWN`.

`UNKNOWN` MUST NOT be silently converted to:

- `NOT_APPLIED`;
- `APPLIED`;
- terminal failure;
- safe-to-retry.

**Why:** Blindly collapsing uncertainty causes duplicate or incorrect effects.

---

## INV-008 — Retry requires an explicit safety basis

A provider execution retry is legal only when at least one canonical safety basis applies, for example:

- the provider guarantees idempotency for the same stable key;
- verification establishes `NOT_APPLIED`;
- the effect is naturally idempotent under its declared semantics;
- another adapter-specific canonical rule proves duplicate invocation safe.

Absence of evidence is not a safety basis.

---

## INV-009 — An execution attempt is durable before provider mutation

A durable attempt record identifying the operation, attempt number/identity, and execution context MUST exist before Stateback crosses the provider mutation boundary.

An unresolved attempt after crash MUST be treated conservatively according to `FAILURE_MODEL.md`.

---

## INV-010 — Provider adapters do not own canonical lifecycle state

Provider adapters MUST return normalized evidence and capability semantics.

They MUST NOT directly decide or persist canonical operation-state transitions.

**Why:** Lifecycle correctness must remain centralized and testable independent of provider code.

---

## INV-011 — Every lifecycle transition is legal and atomic with its audit record

A canonical state change MUST:

1. be allowed by `STATE_MACHINES.md`;
2. be persisted atomically with the durable audit event describing the transition;
3. advance the operation version as required by contract.

No state transition may exist only in logs.

---

## INV-012 — Lifecycle transitions are concurrency-safe

Two workers or requests MUST NOT both successfully apply mutually incompatible transitions from the same operation version.

The implementation MUST use a concurrency-control mechanism grounded in PostgreSQL, such as row locking, compare-and-swap/version checks, or an equivalent proven mechanism.

---

## INV-013 — Concurrent execution of the same operation is controlled

Under healthy PostgreSQL coordination, Stateback MUST NOT intentionally run two concurrent provider mutation attempts for the same logical operation.

Redelivery/recovery may produce repeated attempts over time, but they MUST be serialized through canonical state and retry-safety rules.

---

## INV-014 — Provider-issued external identity is persisted when available

If a provider supplies a stable request/job/resource/transaction identifier relevant to recovery, Stateback MUST persist it as part of durable evidence before relying on it later.

---

## INV-015 — Verification is evidence gathering, not state guessing

Verification MUST query provider/external evidence capable of establishing the claim it returns.

A verification result MUST NOT be synthesized solely from:

- prior local state;
- elapsed time;
- absence of an exception;
- LLM output.

---

## INV-016 — Reconciliation is repeatable

Running reconciliation more than once with the same durable state and equivalent external evidence MUST NOT create unintended new external effects or illegal state transitions.

---

## INV-017 — Compensation is a separate consequential effect

A compensation MUST have its own:

- durable intent;
- attempt identity;
- provider evidence;
- failure/unknown semantics;
- verification/reconciliation path where supported;
- audit history.

Compensation MUST NOT be implemented as an unjournaled cleanup callback.

---

## INV-018 — Compensation does not erase history

After successful compensation, the original operation history MUST continue to show that the original effect occurred or may have occurred.

`COMPENSATED` means a compensating action succeeded; it does not mean the original effect "never happened."

---

## INV-019 — Compensation capability is explicit

Stateback MUST NOT infer reversibility from an action name or provider convention.

Compensation kind and support MUST come from the provider/effect capability contract.

---

## INV-020 — Policy precedes consequential execution

An operation MUST have a durable policy verdict permitting execution before the provider mutation boundary.

If policy requires approval, a valid approval MUST exist and be bound to the current material intent before execution.

---

## INV-021 — Approval is bound to immutable intent

A human approval MUST identify the exact approved material intent, normally through an immutable intent digest and policy context.

Any material change that would alter the approved action invalidates the old approval.

---

## INV-022 — Messaging is coordination, not authority

A worker receiving a JetStream message MUST reload canonical operation state from PostgreSQL before deciding what action is legal.

Message payload state MUST NOT override a newer canonical database state.

---

## INV-023 — Database state change and required asynchronous publication are not an unsafe dual write

When a canonical database transition requires later asynchronous work, the requirement to publish that work MUST be committed transactionally with the database transition, using the canonical transactional outbox design.

A successful database transition MUST NOT depend on a best-effort immediate message publish to remain discoverable.

---

## INV-024 — At-least-once delivery is safe at the operation level

Duplicate or redelivered JetStream messages MUST NOT, by themselves, create uncontrolled duplicate provider effects.

Workers MUST treat delivery as a wake-up/command to evaluate current canonical operation state.

---

## INV-025 — Stale work cannot override newer state

Messages, approvals, operator actions, or other commands carrying a stale operation version MUST NOT silently apply a transition that is incompatible with the current version.

---

## INV-026 — Audit history is append-only

Material audit events MUST NOT be rewritten to make the current outcome look cleaner.

Corrections are represented by later events.

This applies to:

- execution;
- verification;
- policy;
- approvals;
- recovery;
- compensation;
- operator actions.

---

## INV-027 — Failure semantics are normalized before lifecycle decisions

Provider exceptions, HTTP statuses, SDK errors, and malformed responses MUST be normalized into Stateback's canonical evidence/error model before lifecycle logic decides what to do.

Raw transport exception type MUST NOT directly determine retry safety.

---

## INV-028 — No universal exactly-once guarantee

No implementation, API, SDK, UI, documentation, or benchmark may state that Stateback guarantees exactly-once execution across arbitrary external systems.

Any stronger guarantee MUST be scoped to a specific provider/effect and document its assumptions.

---

## INV-029 — Contract semantics are versioned deliberately

Persisted/public contract changes MUST be backwards compatible or have an explicit migration/versioning plan.

A new enum meaning, event meaning, or durable field interpretation MUST NOT be introduced accidentally through serialization behavior.

---

## INV-030 — Secrets are not audit payloads

Provider credentials, private keys, access tokens, passwords, and equivalent secrets MUST NOT be persisted in ordinary operation/audit payloads or emitted to logs.

References or redacted metadata MAY be persisted when needed.

---

## INV-031 — Sensitive intent is handled according to an explicit persistence policy

Stateback MUST know whether material provider arguments are stored inline, redacted, encrypted, or durably referenced.

A provider adapter MUST NOT independently choose an incompatible persistence policy for sensitive arguments.

---

## INV-032 — Observability cannot become a competing source of truth

Metrics, traces, logs, dashboards, and frontend caches may reflect canonical state but MUST NOT be required to reconstruct or recover the authoritative lifecycle.

---

## INV-033 — Operator actions are attributable and auditable

Manual transitions, retries, approvals, compensation requests, or escalations MUST record the acting principal and reason.

Privileged operator action MUST NOT bypass canonical state transition rules.

---

## INV-034 — Semantic AI is non-authoritative

Optional LLM/model assistance MAY classify, summarize, or suggest.

It MUST NOT, by itself:

- declare an external effect applied;
- resolve an unknown outcome;
- authorize a consequential effect;
- override policy;
- create a legal state transition without deterministic validation.

---

## INV-035 — Benchmark baselines are immutable during ordinary implementation

Benchmark baselines, scoring, reference workloads, and competitor configuration MUST NOT be changed merely to improve Stateback's apparent performance or correctness.

Intentional benchmark methodology changes require explicit review and provenance.

---

## INV-036 — Core correctness is self-hostable

Stateback's core transactional correctness MUST NOT depend on a mandatory recurring paid SaaS or hosted proprietary control plane.

External providers being integrated may themselves be paid services; Stateback's core correctness mechanisms must remain independently operable.

---

## INV-037 — Crash recovery is defined at every external boundary

For every consequential external call, implementation and tests MUST have a coherent answer for a crash:

- immediately before the call;
- after the call may have been sent;
- after provider application but before local evidence persistence;
- after evidence persistence but before subsequent transition/publication.

---

## INV-038 — No hidden bypass around the effect boundary

Public API, SDK, MCP, worker, operator control plane, and provider integrations MUST route consequential managed effects through Stateback's canonical operation/policy/journal/runtime path.

A convenience API MUST NOT directly call the provider and bypass the transactional boundary.

---

# Invariant review checklist

For every significant implementation phase, reviewers must answer:

1. Which invariants does this phase enforce?
2. Which invariants can it violate?
3. Which invariants gained machine tests?
4. Which crash boundaries were tested?
5. Which external evidence claims were made, and what supports them?
6. Which concurrency races were considered?
7. Did any contract or state semantic change?
