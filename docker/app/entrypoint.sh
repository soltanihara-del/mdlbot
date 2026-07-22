#!/bin/sh
set -eu

umask 077

require_secret_file() {
    variable_name="$1"
    eval "secret_path=\${${variable_name}:-}"
    if [ -z "${secret_path}" ] || [ ! -r "${secret_path}" ]; then
        printf 'Required secret file is unavailable: %s\n' "${variable_name}" >&2
        exit 78
    fi
    if [ -L "${secret_path}" ]; then
        printf 'Secret file must not be a symbolic link: %s\n' "${variable_name}" >&2
        exit 78
    fi
}

if [ "${DATABASE_REQUIRED:-0}" = "1" ]; then
    require_secret_file DATABASE_PASSWORD_FILE
    : "${POSTGRES_HOST:?POSTGRES_HOST is required}"
    : "${POSTGRES_PORT:=5432}"
    : "${POSTGRES_DB:?POSTGRES_DB is required}"
    : "${POSTGRES_USER:?POSTGRES_USER is required}"
    DATABASE_URL="$(${PATH%%:*}/python - "${DATABASE_PASSWORD_FILE}" <<'PY'
import pathlib
import sys
import urllib.parse
import os

password = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
if not password:
    raise SystemExit("database password is empty")
user = urllib.parse.quote(os.environ["POSTGRES_USER"], safe="")
escaped = urllib.parse.quote(password, safe="")
host = os.environ["POSTGRES_HOST"]
port = os.environ.get("POSTGRES_PORT", "5432")
database = urllib.parse.quote(os.environ["POSTGRES_DB"], safe="")
print(f"postgresql+psycopg://{user}:{escaped}@{host}:{port}/{database}")
PY
)"
    export DATABASE_URL
fi

if [ "${REDIS_REQUIRED:-0}" = "1" ]; then
    require_secret_file REDIS_PASSWORD_FILE
    : "${REDIS_HOST:?REDIS_HOST is required}"
    : "${REDIS_PORT:=6379}"
    REDIS_URL="$(${PATH%%:*}/python - "${REDIS_PASSWORD_FILE}" <<'PY'
import pathlib
import sys
import urllib.parse
import os

password = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
if not password:
    raise SystemExit("redis password is empty")
escaped = urllib.parse.quote(password, safe="")
host = os.environ["REDIS_HOST"]
port = os.environ.get("REDIS_PORT", "6379")
print(f"redis://:{escaped}@{host}:{port}/0")
PY
)"
    export REDIS_URL
fi

if [ "$#" -eq 0 ]; then
    printf 'A service command is required.\n' >&2
    exit 64
fi

exec "$@"
