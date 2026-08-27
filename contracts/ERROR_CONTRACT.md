# Normalized Error Contract

**Status:** Canonical v1
**Owns:** normalized error categories and relationship between local/provider error and external effect outcome.

---

## 1. Principle

An error answers:

> What went wrong in the interaction?

`EffectOutcome` answers:

> What can we establish about whether the external mutation occurred?

These are different questions.

A timeout error may coexist with `UNKNOWN`.

A provider rejection error may coexist with `NOT_APPLIED`.

---

## 2. Canonical `ErrorKind`

```text
VALIDATION
POLICY
AUTHENTICATION
AUTHORIZATION
PROVIDER_REJECTED
RATE_LIMITED
TRANSIENT_TRANSPORT
PROVIDER_UNAVAILABLE
MALFORMED_PROVIDER_RESPONSE
PROVIDER_INCONSISTENT
PERSISTENCE
MESSAGING
CONCURRENCY_CONFLICT
UNSUPPORTED_CAPABILITY
UNSUPPORTED_CONTRACT_VERSION
SECURITY
INTERNAL
```

New error kinds require contract review.

---

## 3. `NormalizedError`

```text
NormalizedError {
  contract_version: "v1"
  kind: ErrorKind
  code: string
  message: string

  retryable_infrastructure: boolean
  provider_http_status: optional<integer>
  provider_error_code: optional<string>
  retry_after_seconds: optional<integer>

  details: json
}
```

Requirements:

- `message` must be safe to persist/log.
- secrets are prohibited.
- `code` is stable enough for programmatic handling within its contract version.
- `retryable_infrastructure` refers to retrying the failed infrastructure interaction, not automatically retrying the consequential effect.

---

## 4. Effect retry must not derive from error alone

Forbidden:

```text
if error.kind in TRANSIENT:
    retry provider mutation
```

Required:

```text
consider:
  effect outcome
  idempotency mode
  verification evidence
  policy
  attempt budget
```

A `TRANSIENT_TRANSPORT` error with `UNKNOWN` outcome may make provider mutation retry unsafe.

---

## 5. Error mapping examples

| Provider/local condition | Effect outcome | Error kind |
|---|---|---|
| local argument validation before call | `NOT_APPLIED` | `VALIDATION` |
| policy denies | `NOT_APPLIED` | `POLICY` |
| provider 4xx documented as rejected before acceptance | `NOT_APPLIED` | `PROVIDER_REJECTED` |
| timeout after request transmission | `UNKNOWN` | `TRANSIENT_TRANSPORT` |
| provider 503 with documented no-accept semantics | `NOT_APPLIED` | `PROVIDER_UNAVAILABLE` |
| provider 503 with ambiguous acceptance | `UNKNOWN` | `PROVIDER_UNAVAILABLE` |
| malformed response after possible effect | `UNKNOWN` | `MALFORMED_PROVIDER_RESPONSE` |
| DB write fails after provider effect | `UNKNOWN` from durable perspective | `PERSISTENCE` |
| stale operation version | no new effect attempted | `CONCURRENCY_CONFLICT` |

---

## 6. Public error exposure

Public API/SDK errors must distinguish:

1. request/transport failure to submit/query Stateback;
2. durable Stateback operation state;
3. provider effect outcome.

For example, an API request returning successfully with operation state `UNKNOWN` is not an HTTP transport failure.

Similarly, an HTTP 500 returned to a client after operation creation does not prove no operation exists; request-idempotency/public API design must account for that in its phase.

---

## 7. Internal exceptions

Internal code may use exceptions, result types, or both.

Regardless of implementation style:

- provider boundary must normalize external errors;
- lifecycle logic must not depend on raw SDK exception classes;
- persistent error information must conform to this contract.

---

## 8. Tests

- every adapter maps representative provider errors;
- no secret fields leak;
- unknown transport error remains `UNKNOWN`;
- provider rejection can be `NOT_APPLIED`;
- infrastructure retry flag does not trigger effect retry automatically;
- serialization rejects unsupported enum values.
