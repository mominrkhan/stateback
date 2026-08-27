# Stateback Canonical State Machines

**Status:** Canonical
**Purpose:** Define exact lifecycle states, transition legality, and transition preconditions.

Code MUST NOT invent additional operation lifecycle states or alternative meanings without updating this file and any affected contracts/ADRs.

State names are uppercase machine-facing symbols unless a contract explicitly maps them to another representation.

---

# 1. Core rule

Stateback uses explicit state machines rather than scattered booleans to represent material lifecycle progress.

A state transition is valid only when:

1. the source state matches the current durable state;
2. the transition is listed in this document;
3. all transition preconditions hold;
4. the transition is applied using canonical concurrency control;
5. the transition and its audit event are persisted atomically.

Provider adapters never apply these transitions directly.

---

# 2. Canonical `OperationState`

The operation lifecycle enum is:

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

No other operation state is canonical in v1.

---

# 3. State meanings

## `PENDING_POLICY`

Durable intent exists. No consequential provider execution is legal yet. Policy has not produced the current durable verdict.

## `AWAITING_APPROVAL`

Policy requires human/delegated approval. A valid approval bound to the current intent does not yet exist.

## `READY`

Policy/approval prerequisites are satisfied and the operation is eligible to begin or resume execution when runtime/retry rules allow.

`READY` does not mean the provider has been called.

## `EXECUTING`

A durable execution attempt has been created and Stateback may have crossed, or may be about to cross, the provider mutation boundary.

If a process dies while this state/attempt is unresolved, recovery must conservatively reason that provider execution **may** have occurred.

## `VERIFYING`

Stateback is gathering provider/external evidence to determine whether the desired effect is applied.

This state is used when canonical policy or recovery requires verification before final success/retry/failure can be established.

## `UNKNOWN`

Available evidence cannot establish whether the requested external effect was applied.

This state blocks blind normal retry. Progress requires verification/reconciliation, an explicitly proven safe-retry basis, or manual intervention.

## `SUCCEEDED`

Stateback has sufficient evidence under the provider/effect contract to classify the desired operation as successfully applied.

This does not imply the effect is irreversible or that compensation is impossible.

## `FAILED`

Stateback has sufficient evidence that the desired operation did not complete as requested and no automatic forward retry is currently legal/selected.

`FAILED` MUST NOT be used for an ambiguous external outcome.

## `DENIED`

Policy or approval explicitly rejected the operation before provider execution was permitted.

## `CANCELLED`

The operation was cancelled before a consequential execution attempt was permitted, or an approval request expired/cancelled under canonical policy.

`CANCELLED` is not legal after external execution may have occurred unless a future explicit state-machine revision defines such semantics.

## `COMPENSATING`

A durable compensation intent/attempt exists and Stateback is executing or verifying a compensating effect.

## `COMPENSATION_UNKNOWN`

Available evidence cannot establish whether the compensating effect was applied.

This state MUST NOT be treated as compensated or safe to retry without evidence/capability semantics.

## `COMPENSATED`

The canonical compensation objective has been established as applied according to its declared compensation semantics.

The original operation history remains intact.

## `COMPENSATION_FAILED`

Stateback has sufficient evidence that compensation did not achieve its requested objective and no automatic compensation retry is currently legal/selected.

## `MANUAL_INTERVENTION`

Automatic progress is unsafe or unsupported and an operator must decide or perform the next action.

This state is used for cases such as:

- irreducible unknown outcome;
- inconsistent provider evidence;
- unsupported recovery;
- repeated recovery/compensation exhaustion;
- security/policy block requiring operator disposition.

---

# 4. Operation transition table

The following transitions are legal in v1.

| From | To | Trigger / required basis |
|---|---|---|
| creation | `PENDING_POLICY` | durable operation + intent created |
| `PENDING_POLICY` | `READY` | durable policy verdict `ALLOW` |
| `PENDING_POLICY` | `AWAITING_APPROVAL` | policy verdict `REQUIRE_APPROVAL` |
| `PENDING_POLICY` | `DENIED` | policy verdict `DENY` |
| `PENDING_POLICY` | `CANCELLED` | valid pre-execution cancellation |
| `AWAITING_APPROVAL` | `READY` | valid approval bound to current intent/version |
| `AWAITING_APPROVAL` | `DENIED` | explicit rejection |
| `AWAITING_APPROVAL` | `CANCELLED` | expiry or valid cancellation |
| `READY` | `EXECUTING` | execution claim + durable attempt created |
| `READY` | `CANCELLED` | cancellation before execution attempt |
| `READY` | `MANUAL_INTERVENTION` | bounded messaging recovery is exhausted before execution can be claimed |
| `EXECUTING` | `SUCCEEDED` | conclusive `APPLIED` evidence and no further verification required |
| `EXECUTING` | `VERIFYING` | verification required or appropriate after evidence |
| `EXECUTING` | `READY` | conclusive `NOT_APPLIED` plus canonical safe-retry decision |
| `EXECUTING` | `FAILED` | conclusive `NOT_APPLIED` and no selected/legal retry |
| `EXECUTING` | `UNKNOWN` | external outcome cannot be established |
| `EXECUTING` | `MANUAL_INTERVENTION` | bounded messaging recovery is exhausted before required execution/verification work can resume |
| `VERIFYING` | `SUCCEEDED` | verification establishes `APPLIED` |
| `VERIFYING` | `READY` | verification establishes `NOT_APPLIED` and retry is legal/selected |
| `VERIFYING` | `FAILED` | verification establishes `NOT_APPLIED` and retry is not legal/selected |
| `VERIFYING` | `UNKNOWN` | verification remains inconclusive or its own outcome is unknown |
| `VERIFYING` | `MANUAL_INTERVENTION` | contradictory/unsafe evidence or policy requires escalation |
| `UNKNOWN` | `VERIFYING` | verification/reconciliation can gather relevant evidence |
| `UNKNOWN` | `READY` | a canonical safety basis establishes that retry is safe |
| `UNKNOWN` | `SUCCEEDED` | reconciliation establishes `APPLIED` without requiring an intermediate persisted `VERIFYING` state in the same transaction/service operation |
| `UNKNOWN` | `FAILED` | reconciliation establishes `NOT_APPLIED` and no retry is legal/selected |
| `UNKNOWN` | `MANUAL_INTERVENTION` | outcome cannot be safely resolved automatically |
| `SUCCEEDED` | `COMPENSATING` | authorized/requested compensation is supported and durable compensation intent created |
| `FAILED` | `COMPENSATING` | a known partial/mitigatable effect requires compensation and capability/policy allow it |
| `MANUAL_INTERVENTION` | `VERIFYING` | authorized operator requests supported verification |
| `MANUAL_INTERVENTION` | `COMPENSATING` | operator-authorized compensation is legal and capability supports it |
| `MANUAL_INTERVENTION` | `READY` | operator action plus evidence establishes a canonical safe-retry basis |
| `COMPENSATING` | `COMPENSATED` | compensation evidence establishes applied compensation objective |
| `COMPENSATING` | `COMPENSATION_UNKNOWN` | compensation outcome is ambiguous |
| `COMPENSATING` | `COMPENSATION_FAILED` | compensation known not applied/unsuccessful and no automatic retry selected |
| `COMPENSATING` | `MANUAL_INTERVENTION` | contradictory/unsupported compensation condition |
| `COMPENSATION_UNKNOWN` | `COMPENSATING` | evidence/capability establishes safe compensation retry or verification is executed within compensation service |
| `COMPENSATION_UNKNOWN` | `COMPENSATED` | compensation reconciliation establishes applied objective |
| `COMPENSATION_UNKNOWN` | `COMPENSATION_FAILED` | reconciliation establishes non-application and retry is not legal/selected |
| `COMPENSATION_UNKNOWN` | `MANUAL_INTERVENTION` | cannot safely resolve |
| `COMPENSATION_FAILED` | `COMPENSATING` | explicitly authorized safe compensation retry |
| `COMPENSATION_FAILED` | `MANUAL_INTERVENTION` | operator escalation |

Any transition not listed here is illegal.

---

# 5. Terminality

Terminality has two meanings:

1. **normal forward execution terminal** — the original requested effect will not continue automatically;
2. **absolutely immutable terminal** — no later operator/compensation transition is legal.

Stateback v1 intentionally uses the first meaning for several states because compensation or operator recovery may still occur.

## Normal forward terminal states

- `SUCCEEDED`
- `FAILED`
- `DENIED`
- `CANCELLED`
- `COMPENSATED`
- `COMPENSATION_FAILED`
- `MANUAL_INTERVENTION`

`UNKNOWN` is not terminal; it is unresolved.

## Absolutely terminal under ordinary v1 behavior

- `DENIED`
- `CANCELLED`
- `COMPENSATED`

A future deliberate contract may add exceptional operator workflows, but ordinary runtime code MUST treat these as no-further-execution states.

`SUCCEEDED` may transition to compensation.

`FAILED` may transition to compensation only when a known partial/mitigatable effect and compensation capability justify it.

---

# 6. Execution attempt state machine

Operation state is not a substitute for individual attempt history.

Canonical `AttemptState`:

```text
STARTED
COMPLETED
```

`STARTED` means the durable attempt exists and provider invocation may have occurred.

`COMPLETED` means Stateback durably recorded the attempt's normalized result.

A completed attempt includes canonical `EffectOutcome`:

```text
APPLIED
NOT_APPLIED
UNKNOWN
```

An attempt that remains `STARTED` after process death is not assumed to be `NOT_APPLIED`. Recovery classifies it conservatively as potentially unknown.

Attempts are append-only historical records. They are never reset to reuse the same attempt identity.

---

# 7. Verification records

Canonical `VerificationState`:

```text
PENDING
IN_PROGRESS
COMPLETED
```

A completed verification result has a canonical `EffectOutcome`:

```text
APPLIED
NOT_APPLIED
UNKNOWN
```

and evidence metadata. The current persisted model is a `VerificationRequest`
plus an optional `VerificationResult`. It does not persist a generic
`VerificationState` field or expose an independent verification transition
table, even though `VerificationState` remains part of the v1 enum vocabulary.

Verification requests/results are separate durable records and may repeat.
Their orchestration is governed by recovery/transition commands and the parent
operation lifecycle. This document deliberately does not invent an independent
verification state machine.

A failed transport call during verification normally yields completed evidence outcome `UNKNOWN` plus normalized error information unless the adapter can prove another outcome.

---

# 8. Policy decision state

Policy evaluation creates an immutable `PolicyDecision` record with verdict:

```text
ALLOW
DENY
REQUIRE_APPROVAL
```

A policy decision is not mutated into another verdict.

If policy must be reevaluated, create a new policy decision record and apply only if state-machine preconditions permit.

---

# 9. Approval state machine

Canonical `ApprovalState`:

```text
PENDING
APPROVED
REJECTED
EXPIRED
CANCELLED
```

Legal transitions:

```text
PENDING -> APPROVED
PENDING -> REJECTED
PENDING -> EXPIRED
PENDING -> CANCELLED
```

All approval terminal states are immutable.

An `APPROVED` approval is usable only if:

- `operation_id` matches;
- bound `intent_digest` matches;
- bound operation/policy version requirements match;
- approval has not expired;
- actor is authorized;
- operation remains `AWAITING_APPROVAL`.

An approval does not itself directly call a provider. It authorizes a legal operation transition.

---

# 10. Compensation record state machine

Compensation has its own durable record in addition to the parent operation state.

Canonical `CompensationState`:

```text
PENDING
EXECUTING
VERIFYING
UNKNOWN
SUCCEEDED
FAILED
```

Legal transitions:

```text
PENDING -> EXECUTING
EXECUTING -> SUCCEEDED
EXECUTING -> VERIFYING
EXECUTING -> UNKNOWN
EXECUTING -> FAILED
VERIFYING -> SUCCEEDED
VERIFYING -> EXECUTING   # only when verified non-applied and retry is safe
VERIFYING -> UNKNOWN
VERIFYING -> FAILED
UNKNOWN -> VERIFYING
UNKNOWN -> EXECUTING     # only with safe-retry basis
UNKNOWN -> SUCCEEDED
UNKNOWN -> FAILED
FAILED -> EXECUTING      # only with explicit safe retry authorization
```

The parent operation state must remain consistent with compensation record state:

| Compensation record | Parent operation |
|---|---|
| `PENDING`, `EXECUTING`, `VERIFYING` | `COMPENSATING` |
| `UNKNOWN` | `COMPENSATION_UNKNOWN` |
| `SUCCEEDED` | `COMPENSATED` |
| `FAILED` | `COMPENSATION_FAILED` |

---

# 11. Outbox state machine

Canonical `OutboxState`:

```text
PENDING
PUBLISHED
```

A row is inserted as `PENDING` in the same PostgreSQL transaction as the canonical state change that requires asynchronous work.

The publisher MAY publish the same outbox record more than once if acknowledgement/update races occur.

After successful publication it transitions:

```text
PENDING -> PUBLISHED
```

`PUBLISHED` records are retained/archived according to operational policy and MUST NOT be changed back to `PENDING` merely to replay work. Explicit replay should create a new outbox event or use a controlled replay mechanism.

---

# 12. Work command semantics

JetStream work commands do not have authority to cause a transition merely because they were emitted.

On receipt, a worker:

1. validates the message;
2. loads the current operation;
3. compares the expected operation version where supplied;
4. decides whether the command is still applicable;
5. applies only transitions legal from current state.

A stale work command is a no-op or audit/debug signal, not a reason to roll state backward.

---

# 13. Crash-state interpretation

## Crash with operation `READY`

No provider attempt has been durably claimed for the current execution. Work can be rescheduled.

## Crash with operation `EXECUTING` and attempt `STARTED`

Provider execution may have occurred. Recovery MUST NOT assume non-execution.

The canonical next recovery disposition is `UNKNOWN`/verification unless the provider/effect contract supplies a stronger safe idempotency/recovery rule.

## Crash after provider result but before durable attempt completion

From durable Stateback perspective the attempt remains unresolved. Treat as potentially unknown.

## Crash after attempt result persistence but before next transition

Recovery reads the durable attempt evidence and applies the legal next transition idempotently.

## Crash after DB transition/outbox insert but before message publish

Outbox relay later publishes the durable work record.

## Crash after message publish but before outbox marked published

The relay may publish again. Duplicate delivery must be safe.

---

# 14. Safe retry preconditions

A transition to `READY` for another execution attempt is legal only when retry policy permits and at least one basis holds:

1. provider-native idempotency with the same stable key makes replay safe;
2. natural idempotency is explicitly declared and tested;
3. verification/reconciliation establishes `NOT_APPLIED`;
4. another provider-specific contract rule proves duplicate invocation cannot create an unintended additional effect.

The following are NOT sufficient:

- previous attempt timed out;
- worker died;
- no external ID was received;
- elapsed time passed;
- logs show no success;
- model believes request probably failed.

---

# 15. State/version concurrency rule

Every material operation transition increments `operation.version`.

Transition functions accept an expected state/version or acquire an equivalent PostgreSQL lock that prevents incompatible concurrent transitions.

A stale actor must reload and reevaluate.

The state machine MUST NOT be implemented as blind `UPDATE state = X WHERE operation_id = ...` without validating source semantics.

---

# 16. State-machine test requirements

Tests MUST cover:

- every legal transition;
- representative illegal transitions;
- every terminal-state restriction;
- stale version rejection;
- concurrent claim of `READY`;
- repeated application of the same recovery command;
- crash interpretation of unresolved `EXECUTING`;
- compensation-parent consistency;
- approval-intent mismatch;
- stale JetStream message behavior.

A table-driven/state-property test should be preferred so code and this document cannot drift silently.
