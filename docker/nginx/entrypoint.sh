#!/bin/sh
set -eu

umask 077
: "${PUBLIC_DOMAIN:?PUBLIC_DOMAIN is required}"
: "${TELEGRAM_WEBHOOK_PATH_FILE:?TELEGRAM_WEBHOOK_PATH_FILE is required}"

if ! printf '%s' "${PUBLIC_DOMAIN}" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$' \
    || printf '%s' "${PUBLIC_DOMAIN}" | grep -q '\.\.'; then
    printf 'PUBLIC_DOMAIN is not a valid DNS name.\n' >&2
    exit 78
fi
if [ ! -r "${TELEGRAM_WEBHOOK_PATH_FILE}" ] || [ -L "${TELEGRAM_WEBHOOK_PATH_FILE}" ]; then
    printf 'Webhook path secret is unavailable or unsafe.\n' >&2
    exit 78
fi

WEBHOOK_PATH="$(tr -d '\r\n' < "${TELEGRAM_WEBHOOK_PATH_FILE}")"
if ! printf '%s' "${WEBHOOK_PATH}" | grep -Eq '^[A-Za-z0-9_-]{48,128}$'; then
    printf 'Webhook path secret must contain 48-128 URL-safe characters.\n' >&2
    exit 78
fi

for tls_file in /run/tls/fullchain.pem /run/tls/privkey.pem; do
    if [ ! -r "${tls_file}" ] || [ -L "${tls_file}" ]; then
        printf 'TLS material is unavailable or unsafe: %s\n' "${tls_file}" >&2
        exit 78
    fi
done

install -d -m 0750 /run/nginx/conf.d /run/nginx/client_temp /run/nginx/proxy_temp /run/nginx/fastcgi_temp /run/nginx/uwsgi_temp /run/nginx/scgi_temp
export PUBLIC_DOMAIN WEBHOOK_PATH
envsubst '${PUBLIC_DOMAIN} ${WEBHOOK_PATH}' \
    < /etc/nginx/templates/site.conf.template \
    > /run/nginx/conf.d/site.conf
unset WEBHOOK_PATH

exec "$@"
