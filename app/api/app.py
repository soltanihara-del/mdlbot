"""Minimal Stage 4 API lifecycle and truthful health endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app import __version__
from app.core.config import RuntimeSettings, load_settings
from app.core.i18n import LocalizationService
from app.core.logging import configure_logging, get_logger
from app.core.redis import RedisManager
from app.db.session import Database
from app.api.webhook import WebhookProxy


def create_app(
    settings: RuntimeSettings | None = None,
    *,
    database: Database | None = None,
    redis: RedisManager | None = None,
    localization: LocalizationService | None = None,
    webhook_proxy: WebhookProxy | None = None,
) -> FastAPI:
    runtime = settings or load_settings("api")
    db = database or Database(runtime)
    cache = redis or RedisManager(runtime)
    i18n = localization or LocalizationService(runtime.locales_path)
    proxy = webhook_proxy or WebhookProxy(runtime)
    log = get_logger("api")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(level=runtime.log_level, output_format=runtime.log_format)
        runtime.validate_dependencies()
        i18n.load()
        await db.start()
        await cache.start()
        webhook_configured = all(
            (
                runtime.telegram_webhook_path_file,
                runtime.telegram_webhook_secret_token_file,
                runtime.internal_service_token_file,
            )
        )
        if runtime.app_env == "production" or webhook_configured:
            await proxy.start()
        app.state.accepting_requests = True
        log.info("api_started", **runtime.safe_summary())
        try:
            yield
        finally:
            app.state.accepting_requests = False
            await proxy.close()
            await cache.close()
            await db.close()
            log.info("api_stopped")

    app = FastAPI(
        title="mdlbot internal API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = runtime
    app.state.database = db
    app.state.redis = cache
    app.state.localization = i18n
    app.state.webhook_proxy = proxy
    app.state.accepting_requests = False

    @app.get("/health/live", include_in_schema=False)
    async def liveness() -> dict[str, Any]:
        return {"status": "alive", "service": runtime.service_name, "version": __version__}

    @app.get("/health/ready", include_in_schema=False)
    async def readiness(request: Request) -> JSONResponse:
        checks: dict[str, bool] = {"localization": i18n.ready}
        try:
            checks["postgresql"] = await db.healthcheck()
        except Exception:
            checks["postgresql"] = False
        try:
            checks["redis"] = await cache.healthcheck()
        except Exception:
            checks["redis"] = False
        ready = bool(request.app.state.accepting_requests and all(checks.values()))
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    @app.post("/telegram/webhook", include_in_schema=False)
    async def telegram_webhook(request: Request) -> JSONResponse:
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse({"ok": False}, status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
        try:
            proxy.validate(
                request.headers.get("x-mdlbot-webhook-path"),
                request.headers.get("x-telegram-bot-api-secret-token"),
            )
        except PermissionError:
            return JSONResponse({"ok": False}, status_code=status.HTTP_403_FORBIDDEN)
        except Exception:
            return JSONResponse({"ok": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        raw = await request.body()
        if len(raw) > 1024 * 1024:
            return JSONResponse({"ok": False}, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("update_id"), int)
                or payload["update_id"] < 0
            ):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return JSONResponse({"ok": False}, status_code=status.HTTP_400_BAD_REQUEST)
        try:
            await proxy.forward(payload)
        except Exception:
            return JSONResponse({"ok": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return JSONResponse({"ok": True})

    return app


application = create_app()
