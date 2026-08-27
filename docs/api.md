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
from stateback.sdk import StatebackClient

with StatebackClient(
    base_url="https://stateback.example",
    token="caller-token",
) as client:
    operation = client.submit(
        effect={"provider": "github", "action": "create_issue", "version": "v1"},
        arguments={
            "owner": "your-github-organization",
            "repo": "your-isolated-sandbox-repository",
            "title": "Stateback integration test",
        },
        idempotency_key="deploy-2026-08-21-001",
    )
    status = operation.status()
```

`OperationHandle.wait()` observes canonical forward-terminal states only.
Its timeout or cancellation result is a client outcome and does not change the
operation.

## MCP

The MCP server exposes the same managed operation path through
`stateback_submit_operation`, `stateback_get_operation`, and
`stateback_get_audit`. MCP input is untrusted. Tools do not accept provider
URLs, credentials, shell commands, or a direct provider-execution escape hatch.

See `contracts/PUBLIC_API_CONTRACT.md` for exact schemas, compatibility rules,
pagination, and errors.
