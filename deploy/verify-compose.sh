#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
project="stateback-release-smoke-$$"
secret_dir=$(mktemp -d /tmp/stateback-release-secrets.XXXXXX)
cp "$repository_root"/deploy/examples/* "$secret_dir"/

compose() {
    docker compose -p "$project" -f "$repository_root/deploy/compose.yaml" "$@"
}

quarantine() {
    docker compose -p "$project" --profile operator \
        -f "$repository_root/deploy/compose.yaml" \
        -f "$repository_root/deploy/quarantine.compose.yaml" "$@"
}

export STATEBACK_FRONTEND_BIND="127.0.0.1:18080"
export STATEBACK_DATABASE_OWNER_PASSWORD_FILE="$secret_dir/database-owner-password.example"
export STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE="$secret_dir/database-runtime-password.example"
export STATEBACK_DATABASE_MIGRATION_URL_FILE="$secret_dir/database-migration-url.example"
export STATEBACK_DATABASE_RUNTIME_URL_FILE="$secret_dir/database-runtime-url.example"
export STATEBACK_NATS_CONFIG_FILE="$secret_dir/nats.conf.example"
export STATEBACK_NATS_URL_FILE="$secret_dir/nats-url.example"
export STATEBACK_NATS_BOOTSTRAP_URL_FILE="$secret_dir/nats-bootstrap-url.example"
export STATEBACK_NATS_QUARANTINE_URL_FILE="$secret_dir/nats-quarantine-url.example"
export STATEBACK_POLICY_CONFIG_FILE="$secret_dir/policy.json.example"
export STATEBACK_AUTH_CONFIG_FILE="$secret_dir/auth.json.example"
export STATEBACK_GITHUB_CONFIGURED="1"
export STATEBACK_OUTBOX_RECOVERY_AFTER_SECONDS="2"
export STATEBACK_OUTBOX_RECOVERY_MAX_REPUBLISHES="3"

compose config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
expected = {
    "migrate": ({"STATEBACK_DATABASE_URL_FILE"}, {"database_migration_url"}),
    "api": (
        {
            "STATEBACK_API_PORT",
            "STATEBACK_AUTH_CONFIG_FILE",
            "STATEBACK_DATABASE_URL_FILE",
            "STATEBACK_GITHUB_CONFIGURED",
            "STATEBACK_POLICY_CONFIG_FILE",
        },
        {"auth_config", "database_runtime_url", "policy_config"},
    ),
    "relay": (
        {
            "STATEBACK_DATABASE_URL_FILE",
            "STATEBACK_NATS_REPLICAS",
            "STATEBACK_NATS_URL_FILE",
            "STATEBACK_OUTBOX_RECOVERY_AFTER_SECONDS",
            "STATEBACK_OUTBOX_RECOVERY_MAX_REPUBLISHES",
        },
        {"database_runtime_url", "nats_url"},
    ),
    "worker": (
        {
            "STATEBACK_DATABASE_URL_FILE",
            "STATEBACK_NATS_REPLICAS",
            "STATEBACK_NATS_URL_FILE",
            "STATEBACK_POLICY_CONFIG_FILE",
        },
        {"database_runtime_url", "nats_url", "policy_config"},
    ),
}
for name, (environment, secrets) in expected.items():
    service = services[name]
    assert set(service.get("environment", {})) == environment, name
    assert {item["source"] for item in service.get("secrets", [])} == secrets, name
'

STATEBACK_GITHUB_TOKEN_FILE="$repository_root/deploy/examples/github-token.example" \
docker compose -p "$project-provider-matrix" \
    -f "$repository_root/deploy/compose.yaml" \
    -f "$repository_root/deploy/github.compose.yaml" \
    config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
api = services["api"]
worker = services["worker"]
assert api["environment"]["STATEBACK_GITHUB_CONFIGURED"] == "1"
assert "STATEBACK_GITHUB_TOKEN_FILE" not in api["environment"]
assert "github_token" not in {item["source"] for item in api.get("secrets", [])}
assert worker["environment"]["STATEBACK_GITHUB_TOKEN_FILE"] == "/run/secrets/github_token"
assert "github_token" in {item["source"] for item in worker["secrets"]}
'

docker compose -p "$project-quarantine-matrix" --profile operator \
    -f "$repository_root/deploy/compose.yaml" \
    -f "$repository_root/deploy/quarantine.compose.yaml" \
    config --format json | python3 -c '
import json, sys
service = json.load(sys.stdin)["services"]["quarantine"]
assert set(service["environment"]) == {
    "STATEBACK_NATS_QUARANTINE_URL_FILE",
    "STATEBACK_NATS_REPLICAS",
}
assert {item["source"] for item in service["secrets"]} == {"nats_quarantine_url"}
assert set(service["networks"]) == {"backend"}
'

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        compose logs --no-color postgres migrate api relay worker nats nats-init \
            >&2 || true
    fi
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    case "$secret_dir" in
        /tmp/stateback-release-secrets.*)
            find "$secret_dir" -type f -delete
            rmdir "$secret_dir"
            ;;
    esac
    return "$status"
}
trap cleanup EXIT INT TERM

compose up -d --wait

curl --fail --silent http://127.0.0.1:18080/ | grep --quiet '<div id="root"></div>'
curl --fail --silent http://127.0.0.1:18080/health/ready | grep --quiet '"ready"'
test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18080/v1/operations/not-an-id)" = "401"

docker exec "$project-relay-1" python -c '
import asyncio
import os
from pathlib import Path
import nats

async def publish():
    client = await nats.connect(Path(os.environ["STATEBACK_NATS_URL_FILE"]).read_text().strip())
    await client.jetstream().publish("stateback.work.v1", b"not-json")
    await client.close()

asyncio.run(publish())
'
poison_diagnostic=$(quarantine run --rm --no-deps quarantine quarantine-inspect)
poison_digest=$(printf '%s' "$poison_diagnostic" | python3 -c \
    'import json,sys; value=json.load(sys.stdin); assert value["diagnostic_type"] == "POISON_MESSAGE"; print(value["payload_sha256"])')
quarantine run --rm --no-deps \
    -e STATEBACK_QUARANTINE_DISCARD_SHA256="$poison_digest" \
    quarantine quarantine-discard | grep --quiet '"status":"discarded"'

docker exec "$project-relay-1" python -c '
import asyncio
import os
from pathlib import Path
import nats
from stateback.domain.enums import CONTRACT_VERSION, WorkCommand
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import WorkMessageV1
from stateback.domain.time import UtcTimestamp
from stateback.messaging.codec import encode_work_message

async def publish():
    message = WorkMessageV1(
        contract_version=CONTRACT_VERSION,
        message_id=OpaqueId(value="00000000-0000-4000-8000-00000000f101"),
        outbox_event_id=OpaqueId(value="00000000-0000-4000-8000-00000000f102"),
        operation_id=OpaqueId(value="00000000-0000-4000-8000-00000000f103"),
        expected_operation_version=1,
        command=WorkCommand.EXECUTE,
        correlation_id="release-quarantine-probe",
        created_at=UtcTimestamp.from_wire("2026-08-17T00:00:00.000000Z"),
    )
    client = await nats.connect(Path(os.environ["STATEBACK_NATS_URL_FILE"]).read_text().strip())
    await client.jetstream().publish("stateback.work.v1", encode_work_message(message))
    await client.close()

asyncio.run(publish())
'
replay_diagnostic=$(quarantine run --rm --no-deps quarantine quarantine-inspect)
replay_message_id=$(printf '%s' "$replay_diagnostic" | python3 -c \
    'import json,sys; value=json.load(sys.stdin); assert value["diagnostic_type"] == "DELIVERY_EXHAUSTED"; assert value["replay_available"] is True; print(value["message_id"])')
quarantine run --rm --no-deps \
    -e STATEBACK_QUARANTINE_REPLAY_MESSAGE_ID="$replay_message_id" \
    quarantine quarantine-replay | grep --quiet '"status":"replayed"'
replayed_diagnostic=$(quarantine run --rm --no-deps quarantine quarantine-inspect)
replayed_digest=$(printf '%s' "$replayed_diagnostic" | python3 -c \
    'import json,sys; value=json.load(sys.stdin); assert value["message_id"] == "00000000-0000-4000-8000-00000000f101"; print(value["payload_sha256"])')
quarantine run --rm --no-deps \
    -e STATEBACK_QUARANTINE_DISCARD_SHA256="$replayed_digest" \
    quarantine quarantine-discard | grep --quiet '"status":"discarded"'

postgres_container="$project-postgres-1"
nats_container="$project-nats-1"

docker exec "$project-worker-1" python -c \
    "import urllib.request; request = urllib.request.Request('https://api.github.com', headers={'User-Agent': 'stateback-release-verifier'}, method='HEAD'); response = urllib.request.urlopen(request, timeout=10); assert response.status == 200"

compose stop worker

docker exec "$project-relay-1" python -c '
import asyncio
import os
from pathlib import Path

import nats
from nats.errors import TimeoutError
from nats.js.api import StorageType, StreamConfig

async def check():
    client = await nats.connect(
        Path(os.environ["STATEBACK_NATS_URL_FILE"]).read_text().strip()
    )
    js = client.jetstream()

    async def denied(awaitable, label):
        try:
            await awaitable
        except TimeoutError:
            return
        raise AssertionError(f"runtime credential performed {label}")

    name = "STATEBACK_V1"
    consumer = "stateback-worker-v1"
    info = await js.stream_info(name)
    expected_max_age = info.config.max_age
    expected_max_bytes = info.config.max_bytes

    info.config.max_age = 0.1
    await denied(js.update_stream(config=info.config), "stream update")
    await denied(js.delete_stream(name), "stream delete")
    await denied(js.purge_stream(name), "stream purge")
    await denied(js.delete_msg(name, 1), "message delete")
    await denied(js.delete_consumer(name, consumer), "consumer delete")
    await denied(
        js.add_stream(
            config=StreamConfig(
                name="STATEBACK_UNAUTHORIZED_PROBE",
                subjects=["stateback.unauthorized.probe"],
                storage=StorageType.MEMORY,
            )
        ),
        "arbitrary stream creation",
    )

    current = await js.stream_info(name)
    assert current.config.max_age == expected_max_age
    assert current.config.max_bytes == expected_max_bytes

    consumer_info = await js.consumer_info(name, consumer)
    expected_max_deliver = consumer_info.config.max_deliver
    expected_max_ack_pending = consumer_info.config.max_ack_pending
    consumer_info.config.max_deliver = 99
    consumer_info.config.max_ack_pending = 99
    await denied(
        js.add_consumer(name, config=consumer_info.config),
        "consumer reconfiguration",
    )
    current_consumer = await js.consumer_info(name, consumer)
    assert current_consumer.config.max_deliver == expected_max_deliver
    assert current_consumer.config.max_ack_pending == expected_max_ack_pending

    subscription = await js.pull_subscribe(
        "stateback.work.v1",
        durable=consumer,
        stream=name,
    )
    await js.publish("stateback.work.v1", b"stateback-production-permission-probe")
    messages = await subscription.fetch(1, timeout=2)
    assert messages[0].data == b"stateback-production-permission-probe"
    await messages[0].ack_sync(timeout=2)
    try:
        await subscription.fetch(1, timeout=1)
    except TimeoutError:
        pass
    else:
        raise AssertionError("acknowledged production probe redelivered")
    await client.close()

asyncio.run(check())
'

compose start worker
compose up -d --wait

docker exec -u postgres "$postgres_container" pg_dump \
    -U stateback_owner -d stateback -Fc -f /tmp/stateback-release-check.dump
docker exec -u postgres "$postgres_container" createdb \
    -U stateback_owner stateback_restore_check
docker exec -u postgres "$postgres_container" pg_restore \
    -U stateback_owner -d stateback_restore_check --exit-on-error \
    /tmp/stateback-release-check.dump
test "$(docker exec -u postgres "$postgres_container" psql \
    -U stateback_owner -d stateback_restore_check -Atc \
    'select count(*) from alembic_version;')" = "1"
test "$(docker exec -u postgres "$postgres_container" psql \
    -U stateback_owner -d stateback -Atc \
    "select has_schema_privilege('stateback_runtime','public','CREATE');")" = "f"
test "$(docker exec -u postgres "$postgres_container" psql \
    -U stateback_owner -d stateback -Atc \
    "select has_table_privilege('stateback_runtime','operations','SELECT,INSERT,UPDATE');")" = "t"
test "$(docker exec -u postgres "$postgres_container" psql \
    -U stateback_owner -d stateback -Atc \
    "select has_table_privilege('stateback_runtime','audit_events','SELECT,INSERT');")" = "t"

runtime_sql_must_fail() {
    if docker exec -u postgres "$postgres_container" psql \
        -U stateback_owner -d stateback -v ON_ERROR_STOP=1 \
        -c "SET ROLE stateback_runtime; $1" >/dev/null 2>&1; then
        echo "runtime database role performed forbidden mutation" >&2
        exit 1
    fi
}

runtime_sql_must_fail "UPDATE audit_events SET reason_code = reason_code WHERE false"
runtime_sql_must_fail "DELETE FROM audit_events WHERE false"
runtime_sql_must_fail "DELETE FROM operations WHERE false"
docker exec -u postgres "$postgres_container" psql \
    -U stateback_owner -d stateback -v ON_ERROR_STOP=1 \
    -c "CREATE SEQUENCE stateback_privilege_probe_sequence" >/dev/null
runtime_sql_must_fail "SELECT setval('stateback_privilege_probe_sequence', 2)"
docker exec -u postgres "$postgres_container" psql \
    -U stateback_owner -d stateback -v ON_ERROR_STOP=1 \
    -c "DROP SEQUENCE stateback_privilege_probe_sequence" >/dev/null

printf '%s\n' 'release-rotated-owner-password' \
    > "$STATEBACK_DATABASE_OWNER_PASSWORD_FILE.rotated"
STATEBACK_DATABASE_OWNER_PASSWORD_FILE="$STATEBACK_DATABASE_OWNER_PASSWORD_FILE.rotated"
export STATEBACK_DATABASE_OWNER_PASSWORD_FILE
printf '%s\n' 'release-rotated-runtime-password' \
    > "$STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE.rotated"
STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE="$STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE.rotated"
export STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE
printf '%s\n' \
    'postgresql+psycopg://stateback_owner:release-rotated-owner-password@postgres:5432/stateback' \
    > "$STATEBACK_DATABASE_MIGRATION_URL_FILE.rotated"
STATEBACK_DATABASE_MIGRATION_URL_FILE="$STATEBACK_DATABASE_MIGRATION_URL_FILE.rotated"
export STATEBACK_DATABASE_MIGRATION_URL_FILE
printf '%s\n' \
    'postgresql+psycopg://stateback_runtime:release-rotated-runtime-password@postgres:5432/stateback' \
    > "$STATEBACK_DATABASE_RUNTIME_URL_FILE.rotated"
STATEBACK_DATABASE_RUNTIME_URL_FILE="$STATEBACK_DATABASE_RUNTIME_URL_FILE.rotated"
export STATEBACK_DATABASE_RUNTIME_URL_FILE
STATEBACK_COMPOSE_PROJECT="$project" \
    "$repository_root/deploy/rotate-postgres-passwords.sh"
database_password_must_fail() {
    if compose exec -T api python -c \
        "import psycopg; psycopg.connect('$1').execute('select 1')" \
        >/dev/null 2>&1; then
        echo "old database password remains valid over the application network" >&2
        exit 1
    fi
}

database_password_must_fail \
    'postgresql://stateback_runtime:replace-with-a-different-random-runtime-password@postgres:5432/stateback'
database_password_must_fail \
    'postgresql://stateback_owner:replace-with-a-random-database-owner-password@postgres:5432/stateback'
compose up -d --force-recreate --wait migrate api relay worker frontend
compose exec -T api python -c \
    "import psycopg; psycopg.connect('postgresql://stateback_runtime:release-rotated-runtime-password@postgres:5432/stateback').execute('select 1')" \
    >/dev/null
compose exec -T api python -c \
    "import psycopg; psycopg.connect('postgresql://stateback_owner:release-rotated-owner-password@postgres:5432/stateback').execute('select 1')" \
    >/dev/null

jetstream=$(docker exec "$nats_container" wget -qO- \
    'http://127.0.0.1:8222/jsz?streams=true&consumers=true&config=true')
printf '%s' "$jetstream" | grep --quiet 'STATEBACK_V1'
printf '%s' "$jetstream" | grep --quiet 'STATEBACK_QUARANTINE_V1'
printf '%s' "$jetstream" | grep --quiet '"storage": "file"'
printf '%s' "$jetstream" | grep --quiet '"ack_policy": "explicit"'

compose stop worker
recovery_operation_id=$(python3 -c '
import json
import urllib.request

base = "http://127.0.0.1:18080"
body = json.dumps({
    "contract_version": "v1",
    "effect": {"provider": "github", "action": "create_issue", "version": "v1"},
    "arguments": {"owner": "acme", "repo": "sandbox", "title": "release recovery probe"},
    "metadata": {},
    "deployment_environment": "production",
}).encode()
request = urllib.request.Request(
    base + "/v1/operations",
    data=body,
    headers={
        "Authorization": "Bearer replace-with-a-random-caller-token",
        "Content-Type": "application/json",
        "Idempotency-Key": "release-message-loss-probe",
    },
)
with urllib.request.urlopen(request, timeout=5) as response:
    operation = json.load(response)
assert operation["state"] == "AWAITING_APPROVAL"
approval = json.dumps({
    "contract_version": "v1",
    "approval_id": operation["current_approval_id"],
    "expected_version": operation["version"],
    "decision": "APPROVED",
    "reason": "release recovery verification",
}).encode()
request = urllib.request.Request(
    base + "/v1/operator/operations/{}/approval".format(operation["operation_id"]),
    data=approval,
    headers={
        "Authorization": "Bearer replace-with-a-different-random-operator-token",
        "Content-Type": "application/json",
        "Idempotency-Key": "release-message-loss-approval",
        "X-Correlation-ID": "release-message-loss-correlation",
    },
)
with urllib.request.urlopen(request, timeout=5) as response:
    approved = json.load(response)
assert approved["state"] == "READY"
print(operation["operation_id"])
')

for _attempt in 1 2 3 4 5; do
    published_count=$(docker exec -u postgres "$postgres_container" psql \
        -U stateback_owner -d stateback -Atc \
        "select count(*) from outbox_events where aggregate_id = '$recovery_operation_id' and state = 'PUBLISHED';")
    [ "$published_count" -ge 1 ] && break
    sleep 1
done
[ "$published_count" -ge 1 ]

compose stop nats
sleep 2
docker exec "$project-relay-1" test ! -f /tmp/stateback-ready
compose rm -f nats nats-init
docker volume rm "${project}_nats_data" >/dev/null
compose up -d --wait nats nats-init
compose up -d --wait relay

for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    recovery_audit_count=$(docker exec -u postgres "$postgres_container" psql \
        -U stateback_owner -d stateback -Atc \
        "select count(*) from audit_events where operation_id = '$recovery_operation_id' and reason_code = 'messaging.recovery_republished';")
    [ "$recovery_audit_count" -ge 1 ] && break
    sleep 1
done
[ "$recovery_audit_count" -ge 1 ]

docker exec -e STATEBACK_RECOVERY_OPERATION_ID="$recovery_operation_id" \
    "$project-relay-1" python -c '
import asyncio
import os
from pathlib import Path
import nats
from stateback.messaging.codec import decode_work_message

async def retrieve():
    client = await nats.connect(Path(os.environ["STATEBACK_NATS_URL_FILE"]).read_text().strip())
    subscription = await client.jetstream().pull_subscribe(
        "stateback.work.v1", durable="stateback-worker-v1", stream="STATEBACK_V1"
    )
    message = (await subscription.fetch(1, timeout=5))[0]
    assert decode_work_message(message.data).operation_id.value == os.environ["STATEBACK_RECOVERY_OPERATION_ID"]
    await message.ack_sync(timeout=2)
    await client.close()

asyncio.run(retrieve())
'

compose start worker
compose up -d --wait
curl --fail --silent http://127.0.0.1:18080/health/ready | grep --quiet '"ready"'
compose stop nats
sleep 2
docker exec "$project-worker-1" test ! -f /tmp/stateback-ready
docker exec "$project-relay-1" test ! -f /tmp/stateback-ready
compose start nats
compose up -d --wait

compose stop postgres
sleep 2
if docker exec "$project-worker-1" stateback health >/dev/null 2>&1; then
    exit 1
fi
if docker exec "$project-relay-1" stateback health >/dev/null 2>&1; then
    exit 1
fi
if curl --fail --silent http://127.0.0.1:18080/health/ready >/dev/null 2>&1; then
    exit 1
fi
compose start postgres
compose up -d --wait

compose restart worker relay
compose up -d --wait
test "$(docker inspect --format '{{.RestartCount}}' "$project-worker-1")" = "0"
test "$(docker inspect --format '{{.RestartCount}}' "$project-relay-1")" = "0"
