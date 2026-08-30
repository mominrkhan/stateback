#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: test-installed-dev.sh WHEEL" >&2
  exit 2
fi

wheel=$1
api_port=${STATEBACK_E2E_API_PORT:-18080}
postgres_port=${STATEBACK_E2E_POSTGRES_PORT:-15432}
nats_port=${STATEBACK_E2E_NATS_PORT:-14222}
nats_monitor_port=${STATEBACK_E2E_NATS_MONITOR_PORT:-18222}
for port in "$api_port" "$postgres_port" "$nats_port" "$nats_monitor_port"; do
  if [[ ! $port =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
    echo "invalid Stateback E2E port" >&2
    exit 2
  fi
done

test_root=$(mktemp -d)
venv="$test_root/venv"
project="$test_root/project"
mkdir "$project"
python3.12 -m venv "$venv"
"$venv/bin/pip" install --quiet "$wheel"
"$venv/bin/stateback" --help >/dev/null
"$venv/bin/stateback" mcp --help >/dev/null
"$venv/bin/python" -c 'from stateback import Stateback; print(Stateback)' >/dev/null
cd "$project"
"$venv/bin/stateback" init --json > "$test_root/init-first.json"
cp .stateback/auth.json "$test_root/auth-before.json"
"$venv/bin/stateback" init --json > "$test_root/init-second.json"
cmp "$test_root/auth-before.json" .stateback/auth.json

perl -pi -e "s/api_port = 8080/api_port = $api_port/" stateback.toml
perl -pi -e "s/postgres_port = 5432/postgres_port = $postgres_port/" stateback.toml
perl -pi -e "s/nats_port = 4222/nats_port = $nats_port/" stateback.toml
perl -pi -e "s/nats_monitor_port = 8222/nats_monitor_port = $nats_monitor_port/" stateback.toml

compose_project=$("$venv/bin/python" -c 'from pathlib import Path; from stateback.cli.config import load_project_config; from stateback.cli.dev import _compose_project; print(_compose_project(load_project_config(Path("stateback.toml"))))')
dev_pid=""

cleanup() {
  if [[ -n $dev_pid ]] && kill -0 "$dev_pid" 2>/dev/null; then
    kill -INT "$dev_pid" 2>/dev/null || true
    wait "$dev_pid" 2>/dev/null || true
  fi
  containers=()
  while IFS= read -r container; do
    [[ -n $container ]] && containers+=("$container")
  done < <(docker ps -aq --filter "label=com.docker.compose.project=$compose_project")
  if ((${#containers[@]})); then
    docker rm -f "${containers[@]}" >/dev/null
  fi
  volumes=()
  while IFS= read -r volume; do
    [[ -n $volume ]] && volumes+=("$volume")
  done < <(
    docker volume ls -q --filter "label=com.docker.compose.project=$compose_project"
  )
  if ((${#volumes[@]})); then
    docker volume rm "${volumes[@]}" >/dev/null
  fi
}
trap cleanup EXIT INT TERM

start_dev() {
  local log=$1
  PYTHONUNBUFFERED=1 "$venv/bin/stateback" dev --no-browser > "$log" 2>&1 &
  dev_pid=$!
  for _attempt in $(seq 1 120); do
    if grep -q "Stateback is ready." "$log"; then
      return 0
    fi
    if ! kill -0 "$dev_pid" 2>/dev/null; then
      cat "$log"
      return 1
    fi
    sleep 1
  done
  cat "$log"
  return 1
}

stop_dev() {
  kill -INT "$dev_pid"
  wait "$dev_pid"
  dev_pid=""
}

assert_stopped() {
  [[ -z $(docker ps -aq --filter "label=com.docker.compose.project=$compose_project") ]]
  if pgrep -f "$venv/bin/python -m stateback.cli.main" >/dev/null; then
    echo "orphan Stateback child process detected" >&2
    return 1
  fi
  [[ ! -e .stateback/run/relay.ready ]]
  [[ ! -e .stateback/run/worker.ready ]]
  [[ ! -e .stateback/run/auth.json ]]
}

start_dev "$test_root/dev-first.log"
[[ -f .stateback/run/auth.json ]]
curl --silent --show-error --fail "http://127.0.0.1:$api_port/health/ready" >/dev/null
curl --silent --show-error --fail "http://127.0.0.1:$api_port/" | grep -q "Stateback Operator"
"$venv/bin/python" -c 'from stateback import Stateback; client = Stateback.local(); client.close()'
postgres_id=$(docker ps -q \
  --filter "label=com.docker.compose.project=$compose_project" \
  --filter "label=com.docker.compose.service=postgres")
[[ -n $postgres_id ]]
docker exec "$postgres_id" psql -U stateback -d stateback -v ON_ERROR_STOP=1 \
  -c "CREATE TABLE dev_e2e_persistence (value integer NOT NULL); INSERT INTO dev_e2e_persistence VALUES (1);" \
  >/dev/null
stop_dev
assert_stopped
volume_count=$(docker volume ls -q \
  --filter "label=com.docker.compose.project=$compose_project" | wc -l | tr -d ' ')
[[ $volume_count == 2 ]]

start_dev "$test_root/dev-second.log"
postgres_id=$(docker ps -q \
  --filter "label=com.docker.compose.project=$compose_project" \
  --filter "label=com.docker.compose.service=postgres")
persisted=$(docker exec "$postgres_id" psql -U stateback -d stateback -tAc \
  "SELECT count(*) FROM dev_e2e_persistence;")
[[ $persisted == 1 ]]
stop_dev
assert_stopped
[[ $(docker volume ls -q --filter "label=com.docker.compose.project=$compose_project" | wc -l | tr -d ' ') == 2 ]]

echo "installed-wheel stateback dev E2E passed"
