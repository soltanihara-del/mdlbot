#!/bin/sh
set -eu

umask 077

read_secret() {
    secret_path="$1"
    if [ ! -r "${secret_path}" ] || [ -L "${secret_path}" ]; then
        printf 'PostgreSQL role secret is unavailable or unsafe.\n' >&2
        exit 78
    fi
    tr -d '\r\n' < "${secret_path}"
}

: "${POSTGRES_APP_PASSWORD_FILE:?POSTGRES_APP_PASSWORD_FILE is required}"
: "${POSTGRES_BACKUP_PASSWORD_FILE:?POSTGRES_BACKUP_PASSWORD_FILE is required}"
: "${POSTGRES_MONITOR_PASSWORD_FILE:?POSTGRES_MONITOR_PASSWORD_FILE is required}"

app_password="$(read_secret "${POSTGRES_APP_PASSWORD_FILE}")"
backup_password="$(read_secret "${POSTGRES_BACKUP_PASSWORD_FILE}")"
monitor_password="$(read_secret "${POSTGRES_MONITOR_PASSWORD_FILE}")"

for password in "${app_password}" "${backup_password}" "${monitor_password}"; do
    if [ "${#password}" -lt 32 ]; then
        printf 'PostgreSQL role passwords must contain at least 32 characters.\n' >&2
        exit 78
    fi
done

MDLBOT_APP_PASSWORD="${app_password}"
MDLBOT_BACKUP_PASSWORD="${backup_password}"
MDLBOT_MONITOR_PASSWORD="${monitor_password}"
export MDLBOT_APP_PASSWORD MDLBOT_BACKUP_PASSWORD MDLBOT_MONITOR_PASSWORD

psql --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
    --set=ON_ERROR_STOP=1 \
    --set=database_name="${POSTGRES_DB}" <<'SQL'
\getenv app_password MDLBOT_APP_PASSWORD
\getenv backup_password MDLBOT_BACKUP_PASSWORD
\getenv monitor_password MDLBOT_MONITOR_PASSWORD

SELECT format('CREATE ROLE mdlbot_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mdlbot_app') \gexec
SELECT format('ALTER ROLE mdlbot_app PASSWORD %L', :'app_password') \gexec

SELECT format('CREATE ROLE mdlbot_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'backup_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mdlbot_backup') \gexec
SELECT format('ALTER ROLE mdlbot_backup PASSWORD %L', :'backup_password') \gexec

SELECT format('CREATE ROLE mdlbot_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT PASSWORD %L', :'monitor_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mdlbot_monitor') \gexec
SELECT format('ALTER ROLE mdlbot_monitor PASSWORD %L', :'monitor_password') \gexec
ALTER ROLE mdlbot_monitor INHERIT;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE :"database_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO mdlbot_app, mdlbot_backup, mdlbot_monitor;
GRANT USAGE ON SCHEMA public TO mdlbot_app, mdlbot_backup;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mdlbot_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mdlbot_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mdlbot_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO mdlbot_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mdlbot_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO mdlbot_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mdlbot_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO mdlbot_backup;
GRANT pg_monitor TO mdlbot_monitor;
SQL

unset app_password backup_password monitor_password
unset MDLBOT_APP_PASSWORD MDLBOT_BACKUP_PASSWORD MDLBOT_MONITOR_PASSWORD
