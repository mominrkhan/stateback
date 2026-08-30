# Contributing to Stateback

Stateback is correctness-sensitive infrastructure. Start with the
[development guide](docs/development.md) and the owning canonical contracts for
the behavior you intend to change.

Prerequisites are Python 3.12, `uv` 0.12.5, Node.js/npm, and Docker with Compose
for integration tests. Install locked dependencies with:

```bash
uv sync --frozen
npm --prefix frontend ci
```

Run the backend, frontend, documentation, package, and integration commands in
[Development](docs/development.md). Keep changes focused and add deterministic
evidence for both success and meaningful failure paths.

Changes to provider guarantees, `UNKNOWN` behavior, retry safety,
compensation, lifecycle semantics, or public contracts require corresponding
contract documentation and tests. A new provider effect must document risk,
idempotency, execution evidence, ambiguous outcomes, verification, safe retry,
and compensation limits before its endpoint code is accepted.

Report security issues privately as described in [SECURITY.md](SECURITY.md),
not through a public issue.
