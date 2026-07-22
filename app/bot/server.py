"""Internal-only bot webhook processor with durable update deduplication."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any

from aiogram.types import Update
from fastapi import FastAPI, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import __version__
from app.bot.factory import BotComponents, create_bot_components
from app.core.config import RuntimeSettings, load_settings
from app.core.i18n import LocalizationService
from app.core.logging import configure_logging, get_logger
from app.core.redis import RedisManager
from app.core.secrets import read_secret_file
from app.db.models.jobs import WebhookUpdate
from app.db.session import Database
from app.bot.progress import ProgressNotifier


class UpdateDeduplicator:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def digest(payload: dict[str, Any]) -> bytes:
        canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).digest()

    async def claim(self, update_id: int, payload: dict[str, Any]) -> bool:
        digest = self.digest(payload)
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            inserted = await session.scalar(
                insert(WebhookUpdate)
                .values(
                    telegram_update_id=update_id,
                    update_type=next((key for key in payload if key != "update_id"), "unknown"),
                    payload_hash=digest,
                    status="processing",
                    received_at=now,
                )
                .on_conflict_do_nothing(index_elements=[WebhookUpdate.telegram_update_id])
                .returning(WebhookUpdate.id)
            )
            if inserted is not None:
                return True
            row = await session.scalar(
                select(WebhookUpdate)
                .where(WebhookUpdate.telegram_update_id == update_id)
                .with_for_update()
            )
            if row is None or not hmac.compare_digest(row.payload_hash, digest):
                raise ValueError("Telegram update ID was reused with a different payload")
            if row.status == "processed":
                return False
            if row.status == "processing" and row.updated_at > now - timedelta(minutes=2):
                return False
            row.status = "processing"
            row.received_at = now
            row.error_code = None
            await session.flush()
            return True

    async def finish(self, update_id: int, *, error_code: str | None = None) -> None:
        async with self._database.transaction() as session:
            row = await session.scalar(
                select(WebhookUpdate)
                .where(WebhookUpdate.telegram_update_id == update_id)
                .with_for_update()
            )
            if row is None:
                return
            row.status = "failed" if error_code else "processed"
            row.error_code = error_code
            row.processed_at = None if error_code else datetime.now(UTC)
            await session.flush()


def create_bot_app(settings: RuntimeSettings | None = None) -> FastAPI:
    runtime = settings or load_settings("bot")
    database = Database(runtime)
    redis = RedisManager(runtime)
    i18n = LocalizationService(runtime.locales_path)
    deduplicator = UpdateDeduplicator(database)
    log = get_logger("bot.server")
    internal_token = ""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal internal_token
        configure_logging(level=runtime.log_level, output_format=runtime.log_format)
        runtime.validate_dependencies()
        runtime.validate_bot_files(token=True, webhook=False)
        i18n.load()
        internal_token = read_secret_file(
            runtime.internal_service_token_file,  # type: ignore[arg-type]
            minimum_length=32,
        )
        await database.start()
        await redis.start()
        components = create_bot_components(runtime, database, redis, i18n)
        progress_stop = asyncio.Event()
        progress_task = asyncio.create_task(
            ProgressNotifier(database, redis, components.bot, i18n).run(progress_stop),
            name="bot-progress-notifier",
        )
        app.state.components = components
        app.state.ready = True
        log.info("bot_started", **runtime.safe_summary())
        try:
            yield
        finally:
            app.state.ready = False
            progress_stop.set()
            progress_task.cancel()
            await asyncio.gather(progress_task, return_exceptions=True)
            await components.bot.session.close()
            await redis.close()
            await database.close()
            internal_token = ""
            log.info("bot_stopped")

    app = FastAPI(
        title="mdlbot internal bot processor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.ready = False

    @app.get("/health/live", include_in_schema=False)
    async def live() -> dict[str, str]:
        return {"status": "alive", "service": "bot", "version": __version__}

    @app.get("/health/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        checks = {"postgresql": False, "redis": False, "localization": i18n.ready}
        try:
            checks["postgresql"] = await database.healthcheck()
        except Exception as exc:
            log.warning("bot_readiness_postgresql_failed", error_type=type(exc).__name__)
        try:
            checks["redis"] = await redis.healthcheck()
        except Exception as exc:
            log.warning("bot_readiness_redis_failed", error_type=type(exc).__name__)
        is_ready = bool(app.state.ready and all(checks.values()))
        return JSONResponse(
            {"status": "ready" if is_ready else "not_ready", "checks": checks},
            status_code=200 if is_ready else 503,
        )

    @app.post("/internal/telegram/webhook", include_in_schema=False)
    async def webhook(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        expected = f"Bearer {internal_token}"
        if not internal_token or authorization is None or not hmac.compare_digest(
            authorization,
            expected,
        ):
            return JSONResponse({"ok": False}, status_code=status.HTTP_401_UNAUTHORIZED)
        raw = await request.body()
        if len(raw) > 1024 * 1024:
            return JSONResponse({"ok": False}, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            payload = json.loads(raw)
            update_id = payload["update_id"]
            if not isinstance(payload, dict) or not isinstance(update_id, int) or update_id < 0:
                raise ValueError
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return JSONResponse({"ok": False}, status_code=status.HTTP_400_BAD_REQUEST)
        try:
            claimed = await deduplicator.claim(update_id, payload)
        except ValueError:
            return JSONResponse({"ok": False}, status_code=status.HTTP_409_CONFLICT)
        if not claimed:
            return JSONResponse({"ok": True, "duplicate": True})
        components: BotComponents = app.state.components
        try:
            update = Update.model_validate(payload, context={"bot": components.bot})
            await components.dispatcher.feed_update(components.bot, update)
        except Exception:
            await deduplicator.finish(update_id, error_code="handler_failed")
            raise
        await deduplicator.finish(update_id)
        return JSONResponse({"ok": True})

    return app


application = create_bot_app()
