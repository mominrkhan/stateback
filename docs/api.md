# API, SDK, and MCP

## HTTP API

All public resources use `/v1` and carry `contract_version: "v1"`. Requests
require authenticated identity; mutation submission additionally requires an
`Idempotency-Key`.

```http
POST /v1/operations
Authorization: Bearer <caller-token>
Idempotency-Key: deploy-2026-08-21-001
Content-Type: application/json
```

```json
{
  "contract_version": "v1",
  "effect": {
    "provider": "github",
    "action": "create_issue",
    "version": "v1"
  },
  "arguments": {
    "owner": "your-github-organization",
    "repo": "your-isolated-sandbox-repository",
    "title": "Stateback integration test"
  },
  "metadata": {},
  "deployment_environment": "production"
}
```

Successful submission returns `202` and a durable operation representation.
It does not prove that a provider effect succeeded. Read the operation with
`GET /v1/operations/{operation_id}` and its ordered audit history with
`GET /v1/operations/{operation_id}/audit`.

Errors use a stable v1 envelope. Authentication, authorization, validation,
conflict, and infrastructure failures are transport errors; an operation in
`UNKNOWN`, `FAILED`, or `MANUAL_INTERVENTION` remains a durable operation state.

## Python SDK

```python
from stateback import Stateback

with Stateback.local() as stateback:
    operation = stateback.github.create_issue(
        owner="your-github-organization",
        repo="your-isolated-sandbox-repository",
        title="Stateback integration test",
        idempotency_key="deploy-2026-08-21-001",
    )
    status = operation.status()
```

Provider-native methods also cover issue comments, one-label additions,
pull-request creation, and expected-head-bound merge. Every mutating method
requires an `idempotency_key` that remains stable across caller retries of the
same intent. `Stateback.from_env()` reads `STATEBACK_API_URL` and
`STATEBACK_API_TOKEN`; that token is a Stateback caller identity, never a GitHub
credential. `AsyncStateback` provides equivalent async methods and handles.
The generic `StatebackClient.submit()` remains available for advanced effects.

`OperationHandle.wait()` observes canonical forward-terminal states only.
Its timeout or cancellation result is a client outcome and does not change the
operation.

## MCP

Run `stateback mcp` for a local stdio server or
`stateback mcp --print-config` for a generic command fragment. It discovers the
same local caller identity as `Stateback.local()`. Typed tools cover the five
GitHub effects plus operation status and audit. Merge submission remains
approval-gated. MCP input is untrusted; tools do not accept provider URLs,
credentials, shell commands, or a direct provider-execution escape hatch.

See `contracts/PUBLIC_API_CONTRACT.md` for exact schemas, compatibility rules,
pagination, and errors.
