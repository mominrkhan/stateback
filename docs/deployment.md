# Self-hosted deployment

## Supported topology

Release `0.1.0` supports `deploy/compose.yaml`: Stateback API, relay, worker,
operator frontend, PostgreSQL 16, and NATS 2.12 with JetStream. Kubernetes and
managed-cloud deployment are not supported release surfaces. The published
Stateback runtime and frontend images support `linux/amd64` only.

The frontend binds to `127.0.0.1:8080` by default. Put an authenticated TLS
reverse proxy in front before exposing it beyond the host. PostgreSQL and NATS
remain on an internal Docker network and are not host-published. Only the
worker joins the separate `provider_egress` network so it can call configured
HTTPS providers; that network does not expose PostgreSQL or NATS.

## Required configuration

Copy the files under `deploy/examples/` to a directory outside the repository,
replace every placeholder with independently generated values, restrict file
permissions to the deployment operator, and export paths:

```text
STATEBACK_DATABASE_OWNER_PASSWORD_FILE=/secure/stateback/database-owner-password
STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE=/secure/stateback/database-runtime-password
STATEBACK_DATABASE_MIGRATION_URL_FILE=/secure/stateback/database-migration-url
STATEBACK_DATABASE_RUNTIME_URL_FILE=/secure/stateback/database-runtime-url
STATEBACK_NATS_CONFIG_FILE=/secure/stateback/nats.conf
STATEBACK_NATS_URL_FILE=/secure/stateback/nats-url
STATEBACK_NATS_BOOTSTRAP_URL_FILE=/secure/stateback/nats-bootstrap-url
STATEBACK_NATS_QUARANTINE_URL_FILE=/secure/stateback/nats-quarantine-url
STATEBACK_POLICY_CONFIG_FILE=/secure/stateback/policy.json
STATEBACK_AUTH_CONFIG_FILE=/secure/stateback/auth.json
```

The example policy requires explicit approval for all five supported GitHub
effects, including expected-head-bound pull-request merge. Rules
are evaluated in order and unmatched operations are denied. Review the policy
as production authorization configuration; never replace it with the
development allow-all engine.

For GitHub, copy `github-token.example` outside the repository, replace it with
a fine-grained isolated-repository credential, export
`STATEBACK_GITHUB_TOKEN_FILE`, and add `-f deploy/github.compose.yaml` to each
Compose command. The overlay mounts the credential only into the worker, which
performs provider calls. The API receives a non-secret configured-capability
signal for pre-durable validation and cannot read the provider credential.
Permissions must cover Issues: write and Pull requests: write for the effects
the deployment authorizes. Do not put the token in Compose,
images, Git, logs, or audit payloads.

Release `0.1.0` sends that credential only to the exact
`https://api.github.com` origin; custom GitHub API origins and path prefixes are
not supported. Redirects are rejected and provider response bodies are capped
at 1 MiB. An oversized response after a mutation remains unknown and requires
verification or reconciliation.

## Startup

```text
docker compose -f deploy/compose.yaml pull
docker compose -f deploy/compose.yaml up -d --wait
```

The one-shot migration service must complete before API, relay, or worker
startup. An incompatible or failed migration blocks readiness; processes must
not work around it.

`GET /health/live` reports process liveness. `GET /health/ready` also checks
PostgreSQL. Relay and worker health checks require both their NATS connection
and a successful PostgreSQL query. These checks expose no credentials or
lifecycle data.

The migration URL uses the `stateback_owner` role. API, relay, and worker use
the DML-only `stateback_runtime` role created during first database
initialization. Migration completion installs explicit table grants: runtime
may read and insert journal records, update only mutable lifecycle/outbox
tables, and cannot delete rows or mutate sequences. Do not give the runtime
role schema-creation or role-management privileges. Each service receives only
the secret files required for its assigned role; the verifier checks this
matrix for the base topology and GitHub overlay. NATS credentials are
deployment secrets; the release stream uses
file storage, work-queue retention, a durable explicit-ack consumer, bounded
delivery, and protected delete/purge operations.
The one-shot `nats-init` service uses a distinct bootstrap credential to create
the isolated work and quarantine streams and their durable consumers. Relay and
worker receive only the runtime credential, whose exact allowlist covers
Stateback's two data subjects, stream/consumer information, work pull delivery,
and acknowledgements. Runtime
cannot create, update, delete, or purge streams or consumers. Preserve this
credential separation when replacing the example configuration; message-level
flags alone do not restrict management requests. Every relay/worker startup
fails closed if any durability, retention, acknowledgement, delivery,
mutability, or bounded-redelivery setting differs from the release
configuration. The isolated verifier also proves a restricted
publish/pull/acknowledge cycle, durable quarantine retrieval/replay, and absence
of redelivery. Relay also scans PostgreSQL for an old latest `PUBLISHED` outbox
event whose operation still requires that command. It appends a new outbox
event plus `outbox.diagnostic.v1` audit evidence; it never rewinds published
history. `STATEBACK_OUTBOX_RECOVERY_AFTER_SECONDS` defaults to 300 and
`STATEBACK_OUTBOX_RECOVERY_MAX_REPUBLISHES` defaults to 3. After that persisted
per-operation-version/command budget is exhausted, relay appends one
`messaging.recovery_exhausted` transition audit, atomically moves the operation
to `MANUAL_INTERVENTION`, stops automatic republication, and requires operator
investigation of PostgreSQL and JetStream before further action. Any authorized
operator transition advances the operation version and begins a new bounded
recovery episode.

Run the isolated deployment verification before an upgrade or release:

```text
deploy/verify-compose.sh
```

It creates a uniquely named temporary Compose project, exercises migration,
readiness, authorization rejection, backup/restore, privilege separation,
the per-process secret matrix, denied audit/history deletion and sequence
mutation, JetStream configuration, non-mutating HTTPS provider connectivity
from the worker, quarantine retrieval/replay, JetStream storage-loss recovery,
database password rotation, and service restarts, then removes only that
temporary project and its volumes.

## Upgrade and recovery limitations

Back up PostgreSQL and the NATS JetStream volume before upgrade. Apply releases
one version at a time, run migrations before application processes, and keep
the prior images available. Database migrations are forward-only unless a
specific migration documents a safe downgrade. Restoring an older database
snapshot does not undo provider effects; reconcile external state separately.

Rotate caller/operator, NATS, and GitHub credentials by updating the external
secret files, revoking the old credential where applicable, and recreating only
the affected containers. Never rotate by editing an image or committing a
secret file.

PostgreSQL password files alone do not alter roles in an existing volume. For
owner/runtime rotation: take and verify a backup; retain protected copies of
the old password and URL files; create four new versioned files for both
passwords and both database URLs; update the corresponding
`STATEBACK_DATABASE_*_FILE` source paths; set `STATEBACK_COMPOSE_PROJECT` to the
running project name; then run `deploy/rotate-postgres-passwords.sh`. Do not
reuse a Compose secret name/path whose content was already materialized. The
helper validates the new host files, copies them to mode-0600 temporary files
in the local PostgreSQL container, changes both roles in one database
transaction without printing their contents, and removes the staged files on
exit. Recreate `migrate`,
`api`, `relay`, and `worker`, wait for readiness,
then verify old passwords fail before destroying the rollback copies. If role
rotation fails, the transaction changes neither role. If container recreation
fails after rotation, restore the old files, rerun the same script through the
local PostgreSQL container, and recreate the processes before reopening API or
worker traffic.
