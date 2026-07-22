#!/bin/sh
set -eu

umask 077

: "${TELEGRAM_API_ID_FILE:?TELEGRAM_API_ID_FILE is required}"
: "${TELEGRAM_API_HASH_FILE:?TELEGRAM_API_HASH_FILE is required}"

for secret_file in "${TELEGRAM_API_ID_FILE}" "${TELEGRAM_API_HASH_FILE}"; do
    if [ ! -r "${secret_file}" ] || [ -L "${secret_file}" ]; then
        printf 'Telegram credential file is unavailable or unsafe.\n' >&2
        exit 78
    fi
done

TELEGRAM_API_ID="$(tr -d '\r\n' < "${TELEGRAM_API_ID_FILE}")"
TELEGRAM_API_HASH="$(tr -d '\r\n' < "${TELEGRAM_API_HASH_FILE}")"

case "${TELEGRAM_API_ID}" in
    ''|*[!0-9]*) printf 'Telegram API ID must be numeric.\n' >&2; exit 78 ;;
esac
case "${TELEGRAM_API_HASH}" in
    ''|*[!0-9a-fA-F]*) printf 'Telegram API hash must be hexadecimal.\n' >&2; exit 78 ;;
esac

export TELEGRAM_API_ID TELEGRAM_API_HASH
exec /opt/telegram-bot-api/bin/telegram-bot-api \
    --local \
    --http-port=8081 \
    --dir=/var/lib/telegram-bot-api \
    --temp-dir=/var/lib/telegram-bot-api/temp \
    --log=/dev/stderr \
    --verbosity=2
