#!/bin/sh
set -eu

if ! runtime_password=$(awk '
    NR > 1 { invalid = 1 }
    {
        line = $0
        sub(/\r$/, "", line)
        if (index(line, "\r") != 0) invalid = 1
        normalized = line
    }
    END {
        if (invalid || NR != 1 || length(normalized) == 0) exit 1
        print normalized
    }
' /run/secrets/database_runtime_password); then
    echo "runtime database password must be one non-empty line" >&2
    exit 1
fi

psql --set ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set runtime_password="$runtime_password" <<-'SQL'
CREATE ROLE stateback_runtime LOGIN PASSWORD :'runtime_password';
GRANT CONNECT ON DATABASE stateback TO stateback_runtime;
GRANT USAGE ON SCHEMA public TO stateback_runtime;
SQL
