# Stage 7 — Secure downloads, X-Accel-Redirect, and usage accounting

Stage 7 exposes completed files without proxying file bodies through Python. The bot creates an opaque HTTPS link only after rechecking the user's active file reference and plan. PostgreSQL stores a keyed hash of the token, never the raw token.

## Request flow

1. The user selects a file in the bilingual Telegram “My Files” view and requests a link.
2. The bot creates a random 256-bit token, an HMAC hash under the deployment download key, a policy snapshot, and an expiry no later than either the file or reference expiry.
3. The first `GET /d/{token}` atomically checks link state, file state, active-session limits, and creates an IP/User-Agent-bound session. The raw session value is returned only in a no-store `307` redirect.
4. The redirected request validates the token and session, link revocation, session expiry, IP, User-Agent, Range syntax, resume count, Range count, and connection limit.
5. The API returns only authorization metadata and `X-Accel-Redirect`. Nginx performs sendfile delivery from an internal, read-only alias with symlink protection and single-range enforcement.
6. Nginx writes the actual response bytes and non-secret record identifiers to its structured delivery log. A dedicated collector inserts bandwidth and egress usage idempotently and reconciles active connection counts.

## Security properties

- Download and future streaming keys are separate by design. The download key is mounted only in `api`, `bot`, and `usage-collector`.
- Token/session values, webhook paths, and internal storage keys are redacted from Nginx logs. Uvicorn access logging is disabled so it cannot independently record raw path tokens.
- Link, session, file, reference, and user checks occur under explicit transaction boundaries. Existing sessions can finish a one-time link after it becomes exhausted, while new sessions cannot be created.
- The source address and User-Agent are stored only as HMAC hashes. Nginx UUID correlation headers are hidden from the public response.
- The connection counter uses an atomic Redis script and a bounded TTL; PostgreSQL remains authoritative for durable session state and collected bytes.
- Content-Disposition uses an ASCII-safe fallback plus RFC 5987 UTF-8 encoding, preventing response-header injection while preserving Persian filenames.
- Nginx performs Range/resume delivery and keeps Python out of the file data plane. Dynamic plan rate limits use `X-Accel-Limit-Rate`.
- Collector replay is safe: `(log_source, request_id)` and usage idempotency keys prevent double charging after Redis cursor loss.

## Verification record

The complete local suite completed with 98 passing tests and one skipped destructive PostgreSQL test because `TEST_DATABASE_URL` was not configured. New tests cover exact download-key validation, canonical token shape, Content-Disposition injection resistance, session redirect/X-Accel responses, callback size, structured-log parsing, partial-line cursor safety, log redaction, secret scope, and the read-only Nginx log mount.

Python compilation and all dependency-independent tests were executed. Docker Engine, Nginx, PostgreSQL, Redis, and deployment TLS material were unavailable in the authoring environment, so live Range/resume transfer and end-to-end byte reconciliation are not claimed as executed here. They remain installer acceptance gates with explicit pass/fail reporting.
