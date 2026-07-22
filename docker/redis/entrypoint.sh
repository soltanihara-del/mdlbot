#!/bin/sh
set -eu

umask 077
: "${REDIS_PASSWORD_FILE:?REDIS_PASSWORD_FILE is required}"

if [ ! -r "${REDIS_PASSWORD_FILE}" ] || [ -L "${REDIS_PASSWORD_FILE}" ]; then
    printf 'Redis password file is unavailable or unsafe.\n' >&2
    exit 78
fi

password="$(tr -d '\r\n' < "${REDIS_PASSWORD_FILE}")"
if [ "${#password}" -lt 32 ]; then
    printf 'Redis password must contain at least 32 characters.\n' >&2
    exit 78
fi

install -m 0600 /etc/redis/redis.conf /run/redis/redis.conf
printf '\nrequirepass %s\nmasterauth %s\n' "${password}" "${password}" >> /run/redis/redis.conf
unset password

exec redis-server /run/redis/redis.conf
