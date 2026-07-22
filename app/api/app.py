"""Minimal Stage 4 API lifecycle and truthful health endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from html import escape
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app import __version__
from app.core.config import RuntimeSettings, load_settings
from app.core.i18n import LocalizationService
from app.core.errors import QuotaExceeded
from app.core.logging import configure_logging, get_logger
from app.core.redis import RedisManager
from app.db.session import Database
from app.api.webhook import WebhookProxy
from app.api.schemas.workers import (
    ClaimRequest,
    CompleteRequest,
    FailRequest,
    HeartbeatRequest,
)
from app.services.quota import QuotaService
from app.workers.control import WorkerControlService
from app.workers.auth import WorkerAuthenticator
from app.services.downloads import DownloadService, content_disposition
from app.core.errors import DownloadDenied
from app.services.streaming import StreamService
from app.core.errors import StreamDenied


def create_app(
    settings: RuntimeSettings | None = None,
    *,
    database: Database | None = None,
    redis: RedisManager | None = None,
    localization: LocalizationService | None = None,
    webhook_proxy: WebhookProxy | None = None,
    worker_control: WorkerControlService | None = None,
    worker_authenticator: WorkerAuthenticator | None = None,
    download_service: DownloadService | None = None,
    stream_service: StreamService | None = None,
) -> FastAPI:
    runtime = settings or load_settings("api")
    db = database or Database(runtime)
    cache = redis or RedisManager(runtime)
    i18n = localization or LocalizationService(runtime.locales_path)
    proxy = webhook_proxy or WebhookProxy(runtime)
    workers = worker_control or WorkerControlService(db, cache, QuotaService())
    worker_auth = worker_authenticator or WorkerAuthenticator(runtime)
    downloads = download_service or (
        DownloadService(runtime, cache) if runtime.download_signing_key_file is not None else None
    )
    streams = stream_service or (
        StreamService(runtime, cache) if runtime.stream_signing_key_file is not None else None
    )
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
        worker_credentials_configured = all(
            (
                runtime.external_worker_token_file,
                runtime.telegram_download_worker_token_file,
                runtime.telegram_upload_worker_token_file,
                runtime.media_worker_token_file,
            )
        )
        if runtime.app_env == "production" or worker_credentials_configured:
            worker_auth.start()
        if runtime.app_env == "production" and downloads is None:
            raise ValueError("DOWNLOAD_SIGNING_KEY_FILE is required in production")
        if runtime.app_env == "production" and streams is None:
            raise ValueError("STREAM_SIGNING_KEY_FILE is required in production")
        app.state.accepting_requests = True
        log.info("api_started", **runtime.safe_summary())
        try:
            yield
        finally:
            app.state.accepting_requests = False
            await proxy.close()
            worker_auth.close()
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
    app.state.worker_control = workers
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

    def authorize_worker(request: Request, job_type: str) -> JSONResponse | None:
        try:
            worker_auth.authenticate(job_type, request.headers.get("authorization"))
        except Exception:
            return JSONResponse({"ok": False}, status_code=status.HTTP_401_UNAUTHORIZED)
        return None

    @app.post("/internal/workers/claim", include_in_schema=False)
    async def worker_claim(request: Request, body: ClaimRequest) -> JSONResponse:
        denied = authorize_worker(request, body.job_type)
        if denied is not None:
            return denied
        job = await workers.claim(job_type=body.job_type, worker_id=body.worker_id)
        return JSONResponse({"ok": True, "job": job})

    @app.post("/internal/workers/heartbeat", include_in_schema=False)
    async def worker_heartbeat(request: Request, body: HeartbeatRequest) -> JSONResponse:
        job_type = request.headers.get("x-worker-job-type", "")
        denied = authorize_worker(request, job_type)
        if denied is not None:
            return denied
        try:
            accepted = await workers.heartbeat(
                job_id=body.job_id,
                generation=body.generation,
                lease=body.lease,
                progress=body.progress,
                expected_job_type=job_type,
            )
        except QuotaExceeded:
            return JSONResponse(
                {"ok": False, "code": "quota_topup_denied"},
                status_code=status.HTTP_409_CONFLICT,
            )
        return JSONResponse(
            {"ok": accepted},
            status_code=200 if accepted else status.HTTP_409_CONFLICT,
        )

    @app.post("/internal/workers/complete", include_in_schema=False)
    async def worker_complete(request: Request, body: CompleteRequest) -> JSONResponse:
        job_type = request.headers.get("x-worker-job-type", "")
        denied = authorize_worker(request, job_type)
        if denied is not None:
            return denied
        accepted = await workers.complete(
            job_id=body.job_id,
            generation=body.generation,
            lease=body.lease,
            result=body.result.model_dump(),
            stream=body.stream,
            group=body.group,
            message_id=body.message_id,
            expected_job_type=job_type,
        )
        return JSONResponse(
            {"ok": accepted},
            status_code=200 if accepted else status.HTTP_409_CONFLICT,
        )

    @app.post("/internal/workers/fail", include_in_schema=False)
    async def worker_fail(request: Request, body: FailRequest) -> JSONResponse:
        job_type = request.headers.get("x-worker-job-type", "")
        denied = authorize_worker(request, job_type)
        if denied is not None:
            return denied
        accepted = await workers.fail(
            job_id=body.job_id,
            generation=body.generation,
            lease=body.lease,
            error_code=body.error_code,
            actual_bytes=body.actual_bytes,
            stream=body.stream,
            group=body.group,
            message_id=body.message_id,
            expected_job_type=job_type,
        )
        return JSONResponse(
            {"ok": accepted},
            status_code=200 if accepted else status.HTTP_409_CONFLICT,
        )

    @app.get("/d/{token}", include_in_schema=False)
    async def direct_download(request: Request, token: str, s: str | None = None) -> Response:
        if downloads is None:
            return JSONResponse({"ok": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        source_ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client is not None else "unknown"
        )
        user_agent = request.headers.get("user-agent", "")
        try:
            async with db.transaction() as session:
                grant = await downloads.authorize(
                    session,
                    raw_token=token,
                    raw_session=s,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    range_header=request.headers.get("range"),
                )
        except DownloadDenied as exc:
            language = str(exc.context.get("language", runtime.default_locale))
            title = i18n.format(language, "download-error-title")
            message = i18n.format(language, "download-error-generic")
            body = (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                f"<title>{escape(title)}</title></head><body><main><h1>{escape(title)}</h1>"
                f"<p>{escape(message)}</p></main></body></html>"
            )
            return HTMLResponse(body, status_code=status.HTTP_404_NOT_FOUND, headers={"Cache-Control": "no-store"})
        if grant.redirect_url is not None:
            return RedirectResponse(
                grant.redirect_url,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        headers = {
            "X-Accel-Redirect": str(grant.internal_path),
            "Content-Type": grant.mime_type,
            "Content-Disposition": content_disposition(grant.filename),
            "ETag": grant.etag,
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "bytes",
            "X-MDLBot-Session-ID": str(grant.session_id),
            "X-MDLBot-Link-ID": str(grant.link_id),
            "X-MDLBot-File-ID": str(grant.file_id),
            "X-MDLBot-User-ID": str(grant.user_id),
            "X-MDLBot-Purpose": "download",
        }
        if grant.rate_bytes_per_second is not None:
            headers["X-Accel-Limit-Rate"] = str(grant.rate_bytes_per_second)
        return Response(status_code=status.HTTP_200_OK, headers=headers)

    async def player_page(token: str, media_kind: str) -> Response:
        if streams is None:
            return JSONResponse({"ok": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            async with db.session() as session:
                view = await streams.player_view(
                    session,
                    raw_token=token,
                    media_kind=media_kind,
                )
        except StreamDenied as exc:
            language = str(exc.context.get("language", runtime.default_locale))
            body = (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                f"<title>{escape(i18n.format(language, 'web-session-expired'))}</title>"
                "</head><body><main>"
                f"<p>{escape(i18n.format(language, 'web-session-expired'))}</p>"
                "</main></body></html>"
            )
            return HTMLResponse(body, status_code=404, headers={"Cache-Control": "no-store"})
        tag = "video" if media_kind == "video" else "audio"
        direction = "rtl" if view.language == "fa" else "ltr"
        title = i18n.format(view.language, "web-player-title")
        sources = (
            f'<source src="/hls/{token}/index.m3u8" type="application/vnd.apple.mpegurl">'
            if view.hls_available
            else ""
        )
        sources += f'<source src="/stream/{token}" type="{escape("video/mp4" if media_kind == "video" else "audio/mp4")}">'
        body = (
            f'<!doctype html><html lang="{view.language}" dir="{direction}">'
            '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{escape(title)}</title></head><body><main><h1>{escape(view.filename)}</h1>"
            f'<{tag} controls preload="metadata">{sources}</{tag}>'
            f"<p>{escape(i18n.format(view.language, 'web-player-help'))}</p>"
            "</main></body></html>"
        )
        return HTMLResponse(body, headers={"Cache-Control": "private, no-store"})

    @app.get("/watch/{token}", include_in_schema=False)
    async def watch(token: str) -> Response:
        return await player_page(token, "video")

    @app.get("/listen/{token}", include_in_schema=False)
    async def listen(token: str) -> Response:
        return await player_page(token, "audio")

    @app.get("/stream/{token}", include_in_schema=False)
    async def direct_stream(request: Request, token: str) -> Response:
        if streams is None:
            return JSONResponse({"ok": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        source_ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client is not None else "unknown"
        )
        try:
            async with db.transaction() as session:
                grant = await streams.authorize(
                    session,
                    raw_token=token,
                    source_ip=source_ip,
                    user_agent=request.headers.get("user-agent", ""),
                )
        except StreamDenied:
            return JSONResponse(
                {"ok": False},
                status_code=status.HTTP_404_NOT_FOUND,
                headers={"Cache-Control": "no-store"},
            )
        headers = {
            "X-Accel-Redirect": grant.internal_path,
            "Content-Type": grant.mime_type,
            "Content-Disposition": "inline",
            "ETag": grant.etag,
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "bytes",
            "X-MDLBot-Session-ID": str(grant.session_id),
            "X-MDLBot-Link-ID": str(grant.token_id),
            "X-MDLBot-File-ID": str(grant.file_id),
            "X-MDLBot-User-ID": str(grant.user_id),
            "X-MDLBot-Purpose": "stream",
        }
        if grant.rate_bytes_per_second is not None:
            headers["X-Accel-Limit-Rate"] = str(grant.rate_bytes_per_second)
        return Response(status_code=200, headers=headers)

    @app.get("/hls/{token}/index.m3u8", include_in_schema=False)
    async def hls_manifest(request: Request, token: str) -> Response:
        if streams is None:
            return JSONResponse({"ok": False}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        source_ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client is not None else "unknown"
        )
        try:
            async with db.transaction() as session:
                manifest = await streams.hls_manifest(
                    session,
                    raw_token=token,
                    source_ip=source_ip,
                    user_agent=request.headers.get("user-agent", ""),
                )
        except StreamDenied:
            return JSONResponse(
                {"ok": False},
                status_code=status.HTTP_404_NOT_FOUND,
                headers={"Cache-Control": "no-store"},
            )
        return Response(
            content=manifest.body,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.get("/hls/{token}/{sequence_number}.ts", include_in_schema=False)
    async def hls_segment(request: Request, token: str, sequence_number: int) -> Response:
        if streams is None or sequence_number < 0 or sequence_number > 100_000:
            return JSONResponse({"ok": False}, status_code=status.HTTP_404_NOT_FOUND)
        source_ip = request.headers.get("x-real-ip") or (
            request.client.host if request.client is not None else "unknown"
        )
        try:
            async with db.transaction() as session:
                grant = await streams.authorize_hls_segment(
                    session,
                    raw_token=token,
                    sequence_number=sequence_number,
                    source_ip=source_ip,
                    user_agent=request.headers.get("user-agent", ""),
                )
        except StreamDenied:
            return JSONResponse(
                {"ok": False},
                status_code=status.HTTP_404_NOT_FOUND,
                headers={"Cache-Control": "no-store"},
            )
        headers = {
            "X-Accel-Redirect": grant.internal_path,
            "Content-Type": grant.mime_type,
            "Content-Disposition": "inline",
            "ETag": grant.etag,
            "Cache-Control": "private, no-store",
            "X-MDLBot-Session-ID": str(grant.session_id),
            "X-MDLBot-Link-ID": str(grant.token_id),
            "X-MDLBot-File-ID": str(grant.file_id),
            "X-MDLBot-User-ID": str(grant.user_id),
            "X-MDLBot-Purpose": "stream",
        }
        if grant.rate_bytes_per_second is not None:
            headers["X-Accel-Limit-Rate"] = str(grant.rate_bytes_per_second)
        return Response(status_code=200, headers=headers)

    return app


application = create_app()
