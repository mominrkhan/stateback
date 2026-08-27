# Development

This page lists commands and configuration supported by the current
repository. It does not present planned commands as implemented behavior.

## Prerequisites

- Python `>=3.12,<3.13` (CI uses Python 3.12)
- `uv == 0.12.5`
- Docker with Compose support for infrastructure-backed tests
- Node.js and npm for the frontend

The repository does not pin a Node engine version, so no specific Node version
is claimed here.

## Install

From the repository root:

```bash
uv sync --frozen
```

For local infrastructure, copy the safe placeholder configuration and export
it into the current shell:

```bash
cp .env.example .env
set -a
. ./.env
set +a
```

Never commit a real `.env` or provider credential.

## Local PostgreSQL and NATS

The root `compose.yaml` starts PostgreSQL 16.15 and NATS 2.12.6 with JetStream.
It does not start the API, relay, worker, or frontend.

```bash
docker compose up -d --wait
docker compose ps
```

Apply the schema with:

```bash
uv run alembic upgrade head
```

Stop infrastructure with `docker compose down`. Adding `-v` destroys the named
local PostgreSQL and NATS volumes and should be used only when that data is
intentionally being discarded.

## Backend verification

The deterministic backend checks used by CI are:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -m unit
git diff --check
```

With local infrastructure running and `.env` exported:

```bash
STATEBACK_RUN_INTEGRATION=1 uv run pytest -m integration
uv run alembic upgrade head
```

Contract tests can be selected with:

```bash
uv run pytest -m contract
```

Do not modify canonical fixtures or weaken assertions merely to obtain a green
build.

## Package and documentation

`pyproject.toml` uses `README.md` as package metadata and includes it in the
source distribution.

```bash
uv build
uv run mkdocs build --strict
```

The sdist must include `README.md`, `LICENSE`, `pyproject.toml`, and
`src/stateback/`. The generated `site/` directory is build output and must not
be committed.

## Frontend

```bash
npm --prefix frontend ci
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

The repository also provides:

```bash
npm --prefix frontend run dev
npm --prefix frontend run test:e2e
```

The Playwright suite requires its expected backend/environment.

## Current CLI

The console entry point is `stateback.deployment.processes:main` and currently
exposes:

```text
api
relay
worker
health
nats-init
db-privileges
quarantine-inspect
quarantine-replay
quarantine-discard
```

Use it as:

```bash
uv run stateback <process>
```

`stateback init`, `stateback dev`, and `stateback provider add ...` are not
implemented.

## Application configuration

API, relay, and worker processes can be run separately after infrastructure,
migrations, and JetStream initialization are ready.

Policy is loaded from `STATEBACK_POLICY_CONFIG_FILE`; the API also requires
`STATEBACK_AUTH_CONFIG_FILE`. Examples are in `deploy/examples/`. The API uses
`STATEBACK_GITHUB_CONFIGURED=0|1` to validate whether the GitHub capability is
configured without receiving the provider credential.

The `nats-init` process reads `STATEBACK_NATS_BOOTSTRAP_URL_FILE` or
`STATEBACK_NATS_BOOTSTRAP_URL`. Relay and worker read `STATEBACK_NATS_URL_FILE`
or `STATEBACK_NATS_URL`. For local NATS:

```bash
STATEBACK_NATS_BOOTSTRAP_URL=nats://127.0.0.1:4222 \
  uv run stateback nats-init
```

Stateback validates existing stream/consumer safety-critical settings and
fails closed when they differ from the expected configuration.

The provider-executing worker reads `STATEBACK_GITHUB_TOKEN_FILE`. Do not run a
worker with a real token unless real GitHub issue mutation is intended.

Optional semantic summaries are disabled unless all three variables are set:

```text
STATEBACK_SEMANTIC_OLLAMA_URL
STATEBACK_SEMANTIC_OLLAMA_MODEL
STATEBACK_SEMANTIC_OLLAMA_TIMEOUT
```

The semantic subsystem is local, optional, and non-authoritative.

## Relay, worker, and quarantine settings

Current relay defaults are:

```text
STATEBACK_RELAY_BATCH=100
STATEBACK_RELAY_INTERVAL_MS=250
STATEBACK_OUTBOX_RECOVERY_AFTER_SECONDS=300
STATEBACK_OUTBOX_RECOVERY_MAX_REPUBLISHES=3
```

JetStream provisioning uses `STATEBACK_NATS_REPLICAS` and
`STATEBACK_WORKER_MAX_DELIVERIES` (default 5). The work consumer uses explicit
acknowledgement, a 60-second acknowledgement wait, `max_ack_pending = 1`, and
one-message pulls.

Quarantine access reads `STATEBACK_NATS_QUARANTINE_URL_FILE` or
`STATEBACK_NATS_QUARANTINE_URL`. Replay requires the expected
`STATEBACK_QUARANTINE_REPLAY_MESSAGE_ID`; discard requires the expected
`STATEBACK_QUARANTINE_DISCARD_SHA256`.

## GitHub sandbox tests

The opt-in sandbox path performs a real mutation and requires:

```text
STATEBACK_RUN_GITHUB_SANDBOX=1
STATEBACK_GITHUB_SANDBOX_CONFIRM_MUTATION=1
STATEBACK_GITHUB_TOKEN
STATEBACK_GITHUB_SANDBOX_OWNER
STATEBACK_GITHUB_SANDBOX_REPO
```

Use only an isolated non-production repository and a fine-grained, revocable
token with Issues write access. Never commit the token.

## Hardened production Compose

Production deployment uses `deploy/compose.yaml`; real GitHub execution adds
the checked-in `deploy/github.compose.yaml` overlay and
`STATEBACK_GITHUB_TOKEN_FILE`. Quarantine operator commands use
`deploy/quarantine.compose.yaml`.

Validate the base Compose model using the same example-file environment as CI,
or run the repository's isolated verifier:

```bash
deploy/verify-compose.sh
```

The verifier is materially broader than `docker compose ... config`: it starts
an isolated production-shaped project and exercises security, persistence,
messaging, recovery, credential isolation, and restart behavior. See the
[deployment guide](deployment.md) before running it.
