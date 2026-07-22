#!/bin/sh
set -eu

: "${REDIS_PASSWORD_FILE:?REDIS_PASSWORD_FILE is required}"
REDISCLI_AUTH="$(tr -d '\r\n' < "${REDIS_PASSWORD_FILE}")"
export REDISCLI_AUTH
[ "$(redis-cli --no-auth-warning --raw ping)" = "PONG" ]
