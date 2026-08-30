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

## Use Stateback

Provider-native Python calls return a durable operation handle; submission is
not proof that GitHub applied the action. Keep each idempotency key stable when
retrying the same intended operation.

```python
from stateback import Stateback

sb = Stateback.local()
operation = sb.github.create_issue(
    owner="your-org",
    repo="your-sandbox",
    title="Agent discovered a problem",
    body="Details from the agent run.",
    idempotency_key="agent-run-123-issue-1",
)
print(operation.status().state)
```

Connect an MCP-capable agent through the local stdio server:

```bash
stateback mcp --print-config
stateback mcp
```

To experience response-loss recovery with one explicitly confirmed real
sandbox mutation:

```bash
stateback demo unknown --owner your-org --repo your-sandbox
```

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

Stateback 0.1 supports a focused GitHub workflow: create issue, comment on an
issue, add one label, create a pull request, and merge a pull request. Creation
effects use positive marker verification; inconclusive search absence remains
`UNKNOWN`. Adding the same label is naturally state-idempotent but Stateback
does not remove labels as compensation because a label may have pre-existed.
Pull-request merge binds an expected head SHA, requires approval under the
generated safe policy, and has no generic compensation.

GitHub is disabled by default. Local development is supported on macOS and
Linux. Provider credentials are loaded only by
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
