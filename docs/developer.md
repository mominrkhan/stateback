# Developer guide

Stateback is not yet published on PyPI. Install the current source with Python
3.12:

```text
python -m pip install "stateback @ git+https://github.com/mominrkhan/stateback.git@main"
```

The package exposes the `stateback` command for the API, relay, and worker
processes in the supported Compose deployment. It does not start external
providers during import.

The REST API lives under `/v1`. `POST /v1/operations` requires bearer
authentication and an `Idempotency-Key`; acceptance returns a durable operation,
not proof of provider success. Use the SDK operation handle or status/audit
resources to observe canonical state.

The SDK distinguishes transport failures and client wait timeouts from durable
operation outcomes. MCP tools enter the same application service and do not
accept provider URLs, credentials, shell commands, or a direct-execution escape
hatch.

Read `contracts/PUBLIC_API_CONTRACT.md` and generated OpenAPI for exact v1
payloads. Unknown, verification, reconciliation, approval,
compensation, and manual-intervention states are intentional compatibility
semantics. See [API, SDK, and MCP](api.md) for a short integration example.
