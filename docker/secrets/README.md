# Docker secrets contract

Create the `secrets` directory on the deployment host with mode `0700`. Each
file below must be a single value with mode `0600`, owned by the deployment
operator. Never commit the directory, copy these values into `.env`, or pass
them as command-line arguments.

| File | Format |
|---|---|
| `bot_token` | Telegram BotFather token |
| `telegram_api_id` | Numeric Telegram application ID |
| `telegram_api_hash` | Telegram application hexadecimal hash |
| `telegram_webhook_path` | 48-128 URL-safe random characters |
| `telegram_webhook_secret_token` | 32 random bytes, hex encoded |
| `postgres_owner_password` | At least 32 random characters |
| `postgres_app_password` | At least 32 random characters |
| `postgres_backup_password` | At least 32 random characters |
| `postgres_monitor_password` | At least 32 random characters |
| `redis_password` | At least 32 random characters |
| `internal_service_token` | 32 random bytes, hex encoded |
| `download_signing_key` | 32 random bytes, hex encoded |
| `backup_encryption_key` | 32 random bytes, hex encoded |
| `grafana_admin_password` | At least 32 random characters |

For locally generated secrets, use a restrictive umask and OpenSSL:

```bash
install -d -m 0700 secrets
umask 077
openssl rand -hex 32 > secrets/telegram_webhook_path
openssl rand -hex 32 > secrets/telegram_webhook_secret_token
openssl rand -hex 32 > secrets/postgres_owner_password
openssl rand -hex 32 > secrets/postgres_app_password
openssl rand -hex 32 > secrets/postgres_backup_password
openssl rand -hex 32 > secrets/postgres_monitor_password
openssl rand -hex 32 > secrets/redis_password
openssl rand -hex 32 > secrets/internal_service_token
openssl rand -hex 32 > secrets/download_signing_key
openssl rand -hex 32 > secrets/backup_encryption_key
openssl rand -hex 32 > secrets/grafana_admin_password
chmod 0600 secrets/*
```

Enter `bot_token`, `telegram_api_id`, and `telegram_api_hash` separately from
their authoritative Telegram sources without placing them in shell history.
Stage 10 will provide an interactive installer that performs this safely.
