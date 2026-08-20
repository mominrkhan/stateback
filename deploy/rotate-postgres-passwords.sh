#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${STATEBACK_COMPOSE_PROJECT:?set STATEBACK_COMPOSE_PROJECT to the running Compose project name}"
: "${STATEBACK_DATABASE_OWNER_PASSWORD_FILE:?set the new owner password file}"
: "${STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE:?set the new runtime password file}"

test -s "$STATEBACK_DATABASE_OWNER_PASSWORD_FILE"
test -s "$STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE"
test "$(wc -c < "$STATEBACK_DATABASE_OWNER_PASSWORD_FILE")" -le 4097
test "$(wc -c < "$STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE")" -le 4097
for password_file in \
    "$STATEBACK_DATABASE_OWNER_PASSWORD_FILE" \
    "$STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE"
do
    awk '
        NR > 1 { invalid = 1 }
        {
            line = $0
            sub(/\r$/, "", line)
            if (index(line, "\r") != 0) invalid = 1
            normalized = line
        }
        END { exit invalid || NR != 1 || length(normalized) == 0 }
    ' "$password_file"
done

compose() {
    docker compose -p "$STATEBACK_COMPOSE_PROJECT" \
        -f "$repository_root/deploy/compose.yaml" "$@"
}

owner_stage=/tmp/stateback-rotate-owner-password
runtime_stage=/tmp/stateback-rotate-runtime-password
cleanup() {
    compose exec -T -u postgres postgres rm -f \
        "$owner_stage" "$runtime_stage" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

compose cp "$STATEBACK_DATABASE_OWNER_PASSWORD_FILE" \
    "postgres:$owner_stage" >/dev/null 2>&1
compose cp "$STATEBACK_DATABASE_RUNTIME_PASSWORD_FILE" \
    "postgres:$runtime_stage" >/dev/null 2>&1
compose exec -T postgres chown postgres:postgres \
    "$owner_stage" "$runtime_stage"
compose exec -T postgres chmod 600 "$owner_stage" "$runtime_stage"

compose exec -T -u postgres postgres psql \
    --username stateback_owner \
    --dbname stateback \
    --set ON_ERROR_STOP=1 <<'SQL'
BEGIN;
SELECT format(
    'ALTER ROLE stateback_runtime PASSWORD %L',
    rtrim(pg_read_file('/tmp/stateback-rotate-runtime-password'), E'\r\n')
) \gexec
SELECT format(
    'ALTER ROLE stateback_owner PASSWORD %L',
    rtrim(pg_read_file('/tmp/stateback-rotate-owner-password'), E'\r\n')
) \gexec
COMMIT;
SQL
