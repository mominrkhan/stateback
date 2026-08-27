# Safety model

Stateback's core safety rule is:

```text
local failure != proof of external non-application
```

A provider can apply a mutation while the response is lost, malformed, or
never durably recorded. Stateback therefore records what evidence proves
rather than interpreting exceptions as external truth.

## External-effect truth

Every execution and verification result uses one of three outcomes:

| Outcome | Meaning |
| --- | --- |
| `APPLIED` | Evidence establishes that the intended effect occurred. |
| `NOT_APPLIED` | Evidence establishes that the intended effect did not occur. |
| `UNKNOWN` | Available evidence establishes neither conclusion. |

Effect outcome is separate from lifecycle state and normalized error kind. A
transport timeout can be a retryable infrastructure error while the external
effect remains `UNKNOWN`.

## Durable boundary

Stateback persists the operation and material intent before a consequential
provider mutation is reachable. It then persists an execution claim and
`STARTED` attempt, commits, invokes the provider outside the transaction, and
persists the result/evidence afterward.

Crashes between these durable points are part of the model. An unresolved
`STARTED` attempt does not prove that the provider was called, but it also does
not prove that it was not called.

Stable Stateback identities survive restart and safe retry:

```text
sb:v1:op:{operation_id}
sb:v1:comp:{compensation_id}
```

Provider-native keys are used only when the effect descriptor declares and
defines their real semantics.

## Retry safety

Infrastructure retry and mutating-effect retry are different decisions.
Publishing a durable outbox row or performing safe read-only verification can
often be retried conventionally. Calling a mutating provider again requires an
explicit safety basis, such as:

- verified `NOT_APPLIED` evidence;
- natural idempotency that is explicitly declared and tested;
- provider-native idempotency with the same stable key and supported replay
  semantics; or
- another provider-specific contract proving replay cannot create an
  unintended additional effect.

A timeout, missing resource ID, elapsed time, absent log entry, worker crash,
or model belief is not a safe-retry basis.

## Verification and reconciliation

Verification gathers external evidence using read-back, operation lookup, or a
custom provider method. It does not infer provider truth from local state.

Reconciliation applies durable evidence through legal transitions. It may mark
success, mark failure when non-application is established, make an operation
ready when retry safety is proven, remain unknown, or require manual
intervention. Repeated reconciliation with equivalent evidence must not create
new external effects.

Automatic recovery is bounded by policy and attempt/recovery budgets. When
evidence cannot support safe progress, `MANUAL_INTERVENTION` is the correct
explicit disposition.

## Policy and approval

Policy is deterministic and precedes provider execution. It may allow, deny,
or require approval and can attach verification, attempt-budget,
automatic-compensation, reason, and expiry obligations.

Approval is durable and bound to immutable intent and policy context. A stale
version or mismatched intent digest cannot authorize execution. Approval does
not bypass the transition service or provider evidence requirements.

## Compensation

Compensation is another consequential external effect, not database rollback.
It has separate intent, attempts, evidence, verification/reconciliation,
unknown outcome, retry rules, and audit history.

Compensation kinds are `NONE`, `EXACT`, `APPROXIMATE`, and `MITIGATING`.
Success means the declared compensation objective was established; it does not
erase the original operation. GitHub issue compensation closes the issue and
is `MITIGATING`, not exact restoration.

## Messaging and quarantine

The transactional outbox commits required work with the PostgreSQL state
change. JetStream may duplicate or redeliver messages, so the worker reloads
canonical state and rejects stale/inapplicable commands. PostgreSQL remains
authoritative if the broker is delayed, unavailable, or loses delivery state.

Quarantine operations require identity/digest confirmation before replay or
discard. A diagnostic publication failure does not prove that the original
message was safely handled.

## Secrets and semantic assistance

Provider credentials belong in environment/secret-file configuration and are
not durable operation arguments, evidence, normalized errors, or audit data.
The GitHub deployment overlay mounts its credential only into the worker.

Optional local Ollama summaries are advisory. They cannot authorize effects,
change state, override provider evidence, or resolve `UNKNOWN`. The correctness
core works without an LLM or mandatory paid service.

## Exactly-once non-guarantee

Stateback does not claim universal exactly-once execution or ACID transactions
across arbitrary external APIs. Exactly-once-like outcomes, where achievable,
are specific to an effect and its combination of durable intent, stable
identity, idempotency, deduplication, external identity, verification,
reconciliation, and compensation.

Review the canonical `FAILURE_MODEL.md`, `INVARIANTS.md`, and
`STATE_MACHINES.md` before changing safety-sensitive behavior.
