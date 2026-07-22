# Stage 4 — Core runtime

Stage 4 turns the schema and container baseline into a runnable, fail-closed application core. It intentionally implements the API lifecycle and shared services only; bot handlers and workers remain assigned to their later stages.

## Delivered components

- Immutable Pydantic runtime configuration with secret-valued connection URLs and safe summaries.
- Strict Docker-secret reader that rejects symlinks, writable files, oversized data, malformed UTF-8, and NUL bytes.
- Structured JSON/console logging with recursive credential, URL-password, and Telegram-token redaction.
- Explicit async SQLAlchemy lifecycle. Application services never create engines at import time and never commit inside repositories/services.
- Redis RESP2-compatible lifecycle, JSON cache helpers, generation counters, and pub/sub invalidation. PostgreSQL remains authoritative.
- Version-controlled catalogs for 34 permissions, eight prepared roles, 33 typed settings, and nine settings profiles.
- Idempotent catalog/bootstrap operation and optional first Super Admin creation from a positive Telegram user ID.
- One RBAC evaluator shared by all future surfaces. Its order is Super Admin protection, administrator/session validity, explicit deny, explicit allow, base role, scope/risk rules, and default deny.
- Typed settings parsing for bytes, durations, bitrates, booleans, integers, decimals, enums, lists, and controlled JSON.
- Optimistic setting versions, immutable history, admin audit, and transactional outbox writes. Cache invalidation is explicitly post-commit.
- Strict Fluent startup validation for Persian and English: exact resource/key/variable/select parity, malformed-resource rejection, a markup allowlist, button-length validation, and escaped dynamic arguments.
- FastAPI liveness and readiness endpoints. Liveness is process-only; readiness independently checks PostgreSQL, Redis, and localization.

## Transaction and trust rules

`Database.session()` never commits. `Database.transaction()` is the only helper that owns a commit boundary. `SettingsService.update()` and `SettingsService.apply_profile()` flush their changes but leave commit/rollback to the caller. Call `invalidate_after_commit()` only after a successful commit.

Redis cannot grant access and is not read as settings truth. A missed invalidation is repaired by the durable outbox and generation polling in later worker stages.

High-risk permissions require an action-bound confirmation. Critical permissions and protected Super Admin changes require two distinct Super Admin approvals. Scope restrictions are cumulative and fail closed.

## Bootstrap and run

After secrets and the non-secret `.env` values are prepared:

```bash
docker compose --profile operations run --rm migrate
docker compose --profile operations run --rm bootstrap
docker compose up -d postgres redis api
docker compose exec api curl --fail http://127.0.0.1:8000/health/live
```

`INITIAL_SUPER_ADMIN_TELEGRAM_ID` is required by the Compose bootstrap service. Re-running bootstrap is safe: catalogs are synchronized by stable codes and UUIDs, existing setting values are preserved, and the selected user remains the initial Super Admin.

## Verification record

The local Stage 4 suite completed with 49 passing tests. One destructive PostgreSQL migration test was skipped because `TEST_DATABASE_URL` was not configured. No live Docker Engine, PostgreSQL, or Redis claim is made by that result.

Coverage includes Stage 2 metadata/migration contracts, Stage 3 Compose/security contracts, configuration and secret-file validation, log redaction, catalog integrity, typed settings and cross-setting invariants, scope enforcement, bilingual Fluent parity and safe rendering, and distinct liveness/readiness behavior.
