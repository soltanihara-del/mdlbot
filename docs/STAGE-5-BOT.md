# Stage 5 — Telegram bot and administration UI

Stage 5 adds the bilingual Telegram interaction layer using aiogram 3.30.0. The public webhook terminates at the API service, validates both the unguessable Nginx path proof and Telegram's secret-token header with constant-time comparisons, bounds and validates the JSON update, then forwards it to the internal-only bot service with a separate service credential.

## Delivered components

- Non-global bot construction with Docker-secret token loading and Local/official Bot API endpoint selection.
- Internal bot FastAPI process, independent liveness/readiness, authenticated webhook endpoint, and durable PostgreSQL update deduplication.
- Redis-backed aiogram FSM with bot-ID namespacing and bounded state/data lifetimes.
- Database, identity, localized-error, ban, and forced-membership middleware.
- First-run bilingual language selection with a dedicated `language_selected_at` migration; Telegram language is only a suggestion until the user explicitly chooses.
- Localized reply/inline keyboards and typed compact callback payloads that stay within Telegram's 64-byte limit.
- User `/start`, `/cancel`, `/help`, language/settings, account status, recent files, Telegram-file/direct-URL intake state transitions, and a durable support-ticket flow.
- Permission-filtered administrator menu, dashboard counts, settings/users summaries, and default-deny authorization at handler execution time.

Stage 5 deliberately stops file and URL workflows at their validated FSM intake boundary. Stage 6 owns the atomic quota reservation, durable job creation, dispatch, and progress flow; it will register the corresponding state handlers without weakening the transaction contract.

## Security properties

- The bot token is read from a non-symlink secret file and is never sent to the API, Nginx, logs, callbacks, or FSM data.
- The public webhook needs two independent proofs and cannot reach the aiogram dispatcher directly.
- The bot endpoint is not published on the host. Its service token is compared in constant time.
- Identical Telegram updates are idempotent. A failed handler marks its update failed for retry; a completed update is acknowledged as a duplicate without rerunning handlers.
- User-visible text is sourced from matching Persian/English Fluent resources. Dynamic user, filename, ban, and administration values are escaped before HTML rendering.
- Admin keyboard visibility is only a convenience; every callback re-runs the shared RBAC evaluator.

## Verification record

The complete local suite completed with 57 passing tests and one skipped destructive PostgreSQL test because `TEST_DATABASE_URL` was not configured. New coverage validates callback sizes, keyboard localization and permission filtering, malformed token rejection, Local Bot API configuration, Redis FSM construction, public webhook secret enforcement/forwarding, canonical update hashing, and the Stage 5 migration chain.

No live Telegram credential, PostgreSQL instance, Redis server, or Docker Engine was available in the authoring environment, so webhook registration and end-to-end Telegram delivery are not claimed as executed here. Those checks are acceptance gates for the Stage 10 installer.
