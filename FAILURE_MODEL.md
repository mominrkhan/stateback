# Stateback Failure Model

**Status:** Canonical
**Purpose:** Define failure classes, what they do and do not prove, and the required recovery posture.

Stateback's foundational rule is:

> `exception != effect did not happen`

Failures are classified by evidence about external state, not by how alarming a local exception looks.

---

# 1. Canonical effect outcome

Every provider mutation attempt and verification attempt must normalize available evidence into one of:

```text
APPLIED
NOT_APPLIED
UNKNOWN
```

## `APPLIED`

Evidence is sufficient under the provider/effect contract to establish that the requested external effect occurred.

## `NOT_APPLIED`

Evidence is sufficient under the provider/effect contract to establish that the requested effect did not occur.

## `UNKNOWN`

Evidence is insufficient to establish either `APPLIED` or `NOT_APPLIED`.

`UNKNOWN` is the safe default when the provider boundary may have been crossed but no conclusive evidence exists.

---

# 2. Error classification is separate from effect outcome

A provider interaction may have both:

- an `EffectOutcome`; and
- an error classification.

Example:

```text
transport timeout
effect outcome: UNKNOWN
error class: TRANSIENT_TRANSPORT
```

Another example:

```text
provider rejects request before accepting it
effect outcome: NOT_APPLIED
error class: PROVIDER_REJECTED
```

Lifecycle decisions must primarily respect effect outcome and provider capabilities.

---

# 3. Canonical failure classes

The initial failure taxonomy uses stable IDs.

## FM-001 — Local validation failure before durable operation creation

**Example:** malformed public request.

**External effect evidence:** `NOT_APPLIED` by construction because provider execution is not reachable.

**Required behavior:** reject request; no operation is required unless API/audit policy intentionally records rejected submissions.

---

## FM-002 — Durable intent persistence failure

**Example:** PostgreSQL unavailable while creating operation.

**External effect evidence:** `NOT_APPLIED` because provider execution MUST NOT occur before durable intent.

**Required behavior:** return infrastructure failure; do not call provider.

---

## FM-003 — Policy deny

**External effect evidence:** `NOT_APPLIED`.

**Required behavior:** operation -> `DENIED`; no provider call.

---

## FM-004 — Approval absent/rejected/expired

**External effect evidence:** `NOT_APPLIED` if no earlier execution was permitted.

**Required behavior:** remain awaiting, transition denied, or cancel according to `STATE_MACHINES.md`. No provider call.

---

## FM-005 — Attempt-record persistence failure before provider call

Stateback could not durably create the attempt.

**External effect evidence:** `NOT_APPLIED` because provider mutation MUST remain unreachable.

**Required behavior:** keep/recover operation before execution; no provider call.

---

## FM-006 — Provider rejects before mutation with conclusive evidence

Examples:

- local provider SDK validation before network;
- provider response contract explicitly guarantees rejected request was not accepted/applied.

**Effect outcome:** `NOT_APPLIED`.

**Required behavior:** retry only if provider/policy error classification says retry is appropriate; otherwise `FAILED`.

---

## FM-007 — Transport timeout after provider request may have been sent

Examples:

- HTTP timeout;
- TCP reset after request transmission;
- SDK deadline exceeded;
- network partition.

**Effect outcome:** `UNKNOWN` unless adapter has provider-specific evidence proving otherwise.

**Required behavior:** operation -> `UNKNOWN` or verification path. No blind generic retry.

---

## FM-008 — Provider success externally, process crashes before local result persistence

**Effect outcome from durable perspective:** unresolved/`UNKNOWN`.

Even if the process observed success before dying, that observation was not durably recorded.

**Required behavior:** recovery uses provider idempotency/verification/external lookup. A second non-idempotent mutation is forbidden until safe.

---

## FM-009 — Provider result persisted, crash before operation-state transition

**Effect outcome:** whatever durable attempt evidence records.

**Required behavior:** recovery replays deterministic lifecycle decision from durable evidence; it does not call provider again merely because parent state is stale.

---

## FM-010 — Operation transition committed, outbox publish not attempted

**Effect outcome:** unaffected; canonical DB state is authoritative.

**Required behavior:** transactional outbox relay later publishes pending work.

---

## FM-011 — JetStream publish succeeds, outbox update fails

**Risk:** duplicate publication.

**Required behavior:** relay may publish again; consumers reload PostgreSQL and duplicate work must be operation-level safe.

---

## FM-012 — Duplicate or redelivered JetStream message

**Required behavior:** treat message as work notification/command, reload canonical state, no-op if stale/inapplicable.

Message duplication MUST NOT imply provider duplication.

---

## FM-013 — Concurrent workers claim the same ready operation

**Required behavior:** PostgreSQL concurrency control permits only one compatible execution claim for the same operation version.

Losing worker reloads and exits/no-ops.

---

## FM-014 — Worker crashes after execution claim but before provider call

Durable state may be `EXECUTING` with `STARTED` attempt even though provider was never called.

**Effect outcome:** conservatively `UNKNOWN` because Stateback cannot atomically prove the exact instruction boundary across process death.

**Required behavior:** use idempotency/verification/recovery rules. This may create conservative extra manual/reconciliation work, which is safer than duplicate effects.

---

## FM-015 — Verification transport failure

**Effect outcome of verification:** `UNKNOWN`.

**Required behavior:** original operation remains unresolved unless other evidence is sufficient. Verification failure is not proof the original effect failed.

---

## FM-016 — Verification establishes effect applied

**Effect outcome:** `APPLIED`.

**Required behavior:** reconcile operation to legal success disposition.

---

## FM-017 — Verification establishes effect not applied

**Effect outcome:** `NOT_APPLIED`.

**Required behavior:** retry may become legal if policy and capability permit; otherwise fail/escalate.

---

## FM-018 — Verification evidence is contradictory or provider-inconsistent

Examples:

- operation lookup says succeeded but read-back contradicts;
- provider returns impossible schema/state combination.

**Effect outcome:** normally `UNKNOWN`.

**Required behavior:** preserve evidence, avoid destructive guessing, transition to `MANUAL_INTERVENTION` when deterministic reconciliation cannot choose safely.

---

## FM-019 — Malformed provider response

If the request may have reached the provider and response cannot be safely interpreted:

**Effect outcome:** `UNKNOWN`.

If malformed data is detected entirely before mutation, adapter may return `NOT_APPLIED`.

---

## FM-020 — Provider rate limit / temporary service unavailable

Effect outcome depends on whether provider contract proves request was rejected before acceptance.

- conclusive rejection -> `NOT_APPLIED`;
- ambiguous transport/acceptance -> `UNKNOWN`.

Retry timing alone does not determine safety.

---

## FM-021 — Database unavailable before provider call

**Effect outcome:** `NOT_APPLIED` if execution has not crossed provider boundary.

**Required behavior:** pause/fail infrastructure path; do not execute without durable state.

---

## FM-022 — Database unavailable after provider call

Provider may have applied effect, but Stateback cannot persist evidence.

**Effect outcome:** `UNKNOWN` from durable perspective.

**Required behavior:** do not rely on worker memory. On DB recovery, reconcile from durable attempt start + provider evidence mechanisms.

---

## FM-023 — NATS unavailable

Canonical operation state remains in PostgreSQL.

**Required behavior:**

- operation creation/transition may still commit outbox;
- relay retries publication later;
- no state loss;
- API may report queued/recoverable status rather than pretend work executed.

---

## FM-024 — NATS message loss outside expected JetStream durability

Even if a message is lost, the durable outbox/recovery scan must make required work discoverable.

Messaging failure cannot make the operation permanently invisible.

---

## FM-025 — Compensation known failure

Provider evidence establishes compensation did not apply.

**Effect outcome:** `NOT_APPLIED`.

**Required behavior:** `COMPENSATION_FAILED`, safe retry if explicitly legal, or manual intervention.

---

## FM-026 — Compensation ambiguous outcome

**Effect outcome:** `UNKNOWN`.

**Required behavior:** `COMPENSATION_UNKNOWN`; verify/reconcile before another non-idempotent compensation attempt.

---

## FM-027 — Compensation succeeds externally, local process crashes

Same rule as original execution.

From durable perspective, outcome may be unknown until provider evidence is recovered.

The original operation history remains intact.

---

## FM-028 — Stale approval / TOCTOU mismatch

Approval references an older operation version or different `intent_digest`.

**Required behavior:** reject approval use; do not execute.

This is authorization failure, not provider failure.

---

## FM-029 — Stale operator action

An operator tries to retry/compensate/transition based on stale state.

**Required behavior:** version/state precondition fails; operator must reload current state.

---

## FM-030 — Unsupported contract/event version

A consumer receives a message or payload version it cannot safely interpret.

**Required behavior:** do not guess. Reject/quarantine according to operational policy and record diagnosable evidence.

---

## FM-031 — Provider credential/authentication failure

Outcome classification depends on provider semantics.

If provider conclusively rejects before mutation, `NOT_APPLIED`.

If the provider accepted work but credential/session failure occurs during subsequent status polling, original effect may remain `UNKNOWN`.

---

## FM-032 — Security policy violation / suspected credential compromise

**Required behavior:** fail closed for new consequential execution, preserve audit, and require operator/security resolution.

Stateback must not "retry through" a security boundary.

---

## FM-033 — Process restart with stale in-memory state

**Required behavior:** discard local lifecycle assumptions and reload PostgreSQL.

---

## FM-034 — Semantic AI unavailable or wrong

**Required behavior:** core deterministic correctness continues without semantic model output.

LLM failure must not make operation truth unknown if deterministic evidence is available, and LLM output must not resolve unknown external truth.

---

# 4. Recovery decision matrix

| Current evidence | Provider idempotency | Verification available | Automatic next action |
|---|---|---|---|
| `APPLIED` | any | not required by policy | success path |
| `APPLIED` | any | required | verify if contract requires final confirmation |
| `NOT_APPLIED` | any | any | retry if policy allows; otherwise fail |
| `UNKNOWN` | `PROVIDER_KEY` and stable key is safe for replay | optional | may retry if adapter contract explicitly guarantees duplicate key semantics; otherwise verify first |
| `UNKNOWN` | `NATURAL` | optional | may retry only if natural idempotency is explicit and tested |
| `UNKNOWN` | `NONE` | yes | verify/reconcile |
| `UNKNOWN` | `NONE` | no | manual intervention |
| contradictory evidence | any | any | manual intervention unless adapter defines deterministic reconciliation |

This matrix is a default. Provider/effect contracts may be stricter, never looser without explicit canonical decision.

---

# 5. Retry classification

A runtime retry policy must distinguish:

## Infrastructure retry

Retrying operations that do not cross the external mutation boundary, such as:

- reading PostgreSQL after transient failure;
- publishing a durable outbox record;
- fetching provider status if verification is itself safe/read-only.

These may use conventional bounded retry policies.

## Effect retry

Calling a mutating provider operation again.

This is subject to `INV-008` and must have an explicit safe-retry basis.

Do not wrap both categories in one generic retry decorator.

---

# 6. Crash boundary checklist

For every provider mutation, tests/review must reason through:

```text
persist operation intent
CRASH

persist attempt STARTED
CRASH

begin provider call
CRASH

provider applies effect
CRASH before Stateback persists evidence

persist provider evidence
CRASH before parent transition

transition state + audit + outbox
CRASH before publish

publish message
CRASH before mark outbox published
```

For compensation, run the same reasoning again because compensation is another side effect.

For verification:

```text
persist verification attempt
CRASH

query provider
CRASH

receive evidence
CRASH before persistence

persist verification evidence
CRASH before reconciliation transition
```

---

# 7. Bounded recovery and escalation

Stateback must not create infinite retry/reconciliation loops.

Automatic recovery must be bounded by:

- policy;
- provider rate limits;
- error class;
- attempt budget;
- elapsed recovery window where configured;
- evidence quality.

Exhaustion transitions to an explicit unresolved/manual state rather than silently abandoning the operation.

The exact numeric defaults are configuration/product decisions and are not fixed in this document.

---

# 8. Partial external effects

Some provider operations may create partial state before returning an error.

An adapter must not map "request failed" to `NOT_APPLIED` if provider semantics allow partial mutation.

Such an effect requires:

- provider-specific verification;
- compensation/mitigation capability where possible;
- or `UNKNOWN`/manual intervention.

---

# 9. Provider inconsistency rule

If provider evidence conflicts, Stateback preserves all material evidence and chooses the most conservative safe interpretation.

Do not overwrite earlier evidence to fit the latest response.

If deterministic provider-specific reconciliation cannot resolve conflict, use `MANUAL_INTERVENTION`.

---

# 10. Persistence corruption / invariant breach

If durable data violates a canonical invariant:

- do not auto-repair by guessing;
- stop automatic consequential execution for the affected operation;
- record diagnostic evidence;
- escalate to manual intervention/operational incident;
- fix through an explicit migration/repair procedure.

Silent repair of lifecycle history is prohibited.

---

# 11. Failure-model test requirement

Every phase that introduces a new external or distributed boundary must add tests for its relevant FM classes.

At minimum tests must include:

- known no-effect failure;
- ambiguous effect failure;
- crash after external success/before local persistence;
- duplicate/reentry;
- concurrency;
- provider malformed/inconsistent evidence;
- persistence outage;
- recovery restart.

Tests should use deterministic fault injection or synchronization rather than sleep-based races.
