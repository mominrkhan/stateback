# Stateback

Stateback is a transactional safety layer for consequential external side
effects performed by AI agents: **Transactions for AI agents**.

Release `0.1.0` includes the durable PostgreSQL journal, explicit lifecycle and
audit history, policy and approval, JetStream relay/workers, unknown-outcome
verification and reconciliation, compensation, the optional GitHub issue
provider, public API, Python SDK, MCP tools, operator backend/frontend,
deterministic benchmark harness, and optional non-authoritative local semantic
summaries.

Product definition lives in `PRODUCT.md`. Do not treat this README as architecture.
Public deployment and usage documentation lives under `docs/`.
Start with `docs/architecture.md`, `docs/safety-model.md`, and
`docs/development.md`; exact lifecycle and enum symbols live in
`STATE_MACHINES.md` and `contracts/enums-v1.md`.

## Prerequisites

- uv 0.12.5
- Docker Engine with Compose v2
- Free local ports 5432, 4222, and 8222

## Setup

```text
uv sync --frozen
cp .env.example .env
```

## Commands

These commands are the repository contract. CI runs the same strings.

```text
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -m unit
docker compose up -d --wait
set -a && . ./.env && set +a
STATEBACK_RUN_INTEGRATION=1 uv run pytest -m integration
uv run alembic upgrade head
git diff --check
```

`docker compose down -v` destroys named volumes. Do not use it as a routine command.

For the production-shaped release topology, see `docs/deployment.md` and
`deploy/compose.yaml`. The root `compose.yaml` and `.env.example` remain local
development infrastructure. Public API, SDK, and MCP usage is documented in
`docs/api.md`; operator controls are documented in `docs/operator.md`.

## What Stateback does not claim

Stateback does not claim universal exactly-once execution across arbitrary
providers or exact rollback. Unknown provider outcomes remain unknown until
evidence resolves them, and GitHub issue closing is mitigating compensation.
See `PRODUCT.md`, `docs/guarantees.md`, and `ADR-0003`.
