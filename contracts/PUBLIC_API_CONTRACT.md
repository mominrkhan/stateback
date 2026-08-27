# Stateback Public API, SDK, and MCP Contract v1

**Status:** Canonical
**Version:** `v1`
**Owns:** public request, response, pagination, compatibility, and error semantics

## Compatibility

HTTP resources live under `/v1`; JSON objects carry `contract_version: "v1"`.
Within v1, field meanings and canonical enum values do not change. New optional
fields may be added. Servers reject unknown request fields. SDK readers preserve
an unknown future state as an explicit unknown value rather than mapping it to
success or failure.

## Submit operation

`POST /v1/operations` requires an `Idempotency-Key` and authenticated `CALLER`.
The key is a non-empty opaque ASCII value of at most 200 characters. The server
deterministically derives the operation identity and all submit-side record IDs
from the authenticated principal plus key. Reuse with the same canonical intent
returns the existing operation; reuse with different intent returns
`idempotency_conflict`.

Request body:

```json
{
  "contract_version": "v1",
  "effect": {"provider": "...", "action": "...", "version": "..."},
  "arguments": {},
  "metadata": {"key": "value"},
  "deployment_environment": "production"
}
```

The requester comes only from authenticated identity. Accepted responses contain
a durable operation representation and use HTTP 202, including policy-denied or
approval-required operation states once durably created. Validation/policy
rejection before durable creation uses a structured 4xx error.

## Read resources

- `GET /v1/operations/{operation_id}` returns the exact canonical operation.
- `GET /v1/operations/{operation_id}/audit?after_sequence=&limit=` returns
  events ordered by ascending sequence.
- `limit` is 1–100, default 50. `next_after_sequence` is the last returned
  sequence when more records exist, otherwise null.

Reads never invoke a provider, create work, or mutate lifecycle state.

## Envelope and errors

Successful resources carry `contract_version`. Errors use:

```json
{
  "contract_version": "v1",
  "error": {
    "code": "stable_machine_code",
    "message": "safe human message",
    "retryable": false,
    "correlation_id": null
  }
}
```

Authentication (401), authorization (403), missing resource (404), conflict
(409), validation (422), throttling (429), and infrastructure failure (503) are
transport/client errors. A durable operation in `UNKNOWN`, `FAILED`,
`MANUAL_INTERVENTION`, or a compensation state is returned as operation state,
not converted into a transport error.

## SDK

The Python SDK models these payloads without defining a second lifecycle enum.
Submission returns an operation handle. `wait` stops only at canonical
forward-terminal states, accepts caller timeout/cancellation, uses bounded
backoff, and returns timeout as a client result without changing the operation.

## MCP

MCP mutation tools accept the same logical submit fields and return durable
operation identity/state. MCP read tools use the same read resources. MCP input
is untrusted. No tool accepts arbitrary provider URLs, credentials, shell
commands, or a direct provider-execution escape hatch.
