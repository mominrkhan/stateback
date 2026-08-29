# Stateback

**Transactions for AI agents.**

Stateback safely manages consequential AI-agent side effects with durable
intent, policy and approval, verification, recovery, compensation, and
first-class `UNKNOWN` outcomes when external truth cannot be established.

## Quickstart

Stateback is currently a pre-release development build and is not yet published
on PyPI. With Python 3.12, `uv`, Git, and Docker with Compose installed, install
the current source:

```bash
git clone https://github.com/mominrkhan/stateback.git
cd stateback
uv tool install .
cd ..
mkdir my-agent
cd my-agent
stateback init
stateback dev
```

`stateback init` creates local configuration and a safe default policy.
`stateback dev` starts the local runtime and opens the Operator UI at
<http://127.0.0.1:8080>.

Once the first PyPI release is published:

```bash
pip install stateback
```

## Connect GitHub

Authenticate the GitHub CLI, then configure Stateback:

```bash
gh auth login
stateback connect github
```

Restart `stateback dev` after changing provider configuration.

## Why Stateback

An API timeout or local exception does not prove that an external side effect
did not happen. The provider may have applied the mutation before the response
was lost or before Stateback could persist the result. Blindly retrying can then
duplicate a consequential action.

Stateback durably records intent before execution, applies policy and approval,
and records provider attempts and evidence. PostgreSQL remains authoritative;
NATS JetStream coordinates delivery.

External effects have three explicit outcomes:

- `APPLIED`: evidence establishes that the intended effect occurred.
- `NOT_APPLIED`: evidence establishes that it did not occur.
- `UNKNOWN`: available evidence establishes neither conclusion.

`UNKNOWN` remains explicit until verification or reconciliation supplies enough
evidence to resolve it. Stateback does not claim universal exactly-once
execution or ACID transactions across arbitrary external APIs.

## Current provider support

The only real mutating provider effect currently implemented is
`github.create_issue.v1`. It creates a GitHub issue, supports positive
verification through a Stateback operation marker, and can mitigate the effect
by closing the issue. Closing is compensation, not exact rollback. GitHub issue
creation has no provider idempotency key, so inconclusive evidence remains
`UNKNOWN` rather than making an unsafe retry.

GitHub is disabled by default. Provider credentials are loaded only by
provider-executing workers and are never exposed by the Operator UI.

## Documentation

- [Documentation index](docs/index.md)
- [Architecture](docs/architecture.md)
- [Safety model](docs/safety-model.md)
- [API, SDK, and MCP](docs/api.md)
- [Operator guide](docs/operator.md)
- [Deployment](docs/deployment.md)
- [Development](docs/development.md)

## Contributing

Source setup, tests, linting, type checking, frontend commands, and integration
infrastructure are documented in [Development](docs/development.md).

## License

Stateback is available under the [MIT License](LICENSE).
