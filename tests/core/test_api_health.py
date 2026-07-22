from pathlib import Path
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest

from app.api.app import create_app
from app.core.config import RuntimeSettings
from app.core.i18n import LocalizationService
from app.services.downloads import SessionGrant
from app.services.streaming import HlsManifest, PlayerView, StreamGrant


class Dependency:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.started = False

    async def healthcheck(self) -> bool:
        return self.healthy

    @asynccontextmanager
    async def transaction(self):
        yield object()

    @asynccontextmanager
    async def session(self):
        yield object()


class Downloads:
    async def authorize(self, _session, *, raw_token, raw_session, **_kwargs):
        if raw_session is None:
            return SessionGrant(
                session_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfba"),
                raw_session="S" * 43,
                redirect_url=f"/d/{raw_token}?s={'S' * 43}",
                internal_path=None,
                filename="file.bin",
                mime_type="application/octet-stream",
                etag='"abc"',
                rate_bytes_per_second=1024,
                language="en",
                link_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbb"),
                file_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbc"),
                user_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbd"),
            )
        return SessionGrant(
            session_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfba"),
            raw_session=None,
            redirect_url=None,
            internal_path="/__protected/files/aa/object",
            filename="file.bin",
            mime_type="application/octet-stream",
            etag='"abc"',
            rate_bytes_per_second=1024,
            language="en",
            link_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbb"),
            file_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbc"),
            user_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbd"),
        )


class Streams:
    async def player_view(self, _session, *, media_kind, **_kwargs):
        return PlayerView(
            filename="video.mp4",
            language="en",
            media_kind=media_kind,
            hls_available=True,
        )

    async def hls_manifest(self, _session, **_kwargs):
        return HlsManifest(body="#EXTM3U\n#EXT-X-ENDLIST\n")

    async def authorize_hls_segment(self, _session, **_kwargs):
        return StreamGrant(
            session_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfba"),
            token_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbb"),
            file_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbc"),
            user_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfbd"),
            internal_path="/__protected/hls/job/segment-000000.ts",
            mime_type="video/mp2t",
            etag='"segment"',
            rate_bytes_per_second=2048,
        )


def build_app(*, database_healthy: bool = True, downloads=None, streams=None):
    root = Path(__file__).parents[2]
    settings = RuntimeSettings(
        app_env="test",
        service_name="api",
        database_url="postgresql+psycopg://user:password@db/app",
        redis_url="redis://:password@cache/0",
        locales_path=root / "locales",
        log_format="console",
    )
    return create_app(
        settings,
        database=Dependency(database_healthy),  # type: ignore[arg-type]
        redis=Dependency(),  # type: ignore[arg-type]
        localization=LocalizationService(settings.locales_path),
        download_service=downloads,
        stream_service=streams,
    )


@pytest.mark.asyncio
async def test_liveness_and_readiness_are_distinct() -> None:
    app = build_app(database_healthy=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["postgresql"] is False


@pytest.mark.asyncio
async def test_readiness_succeeds_when_dependencies_are_healthy() -> None:
    app = build_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_download_route_creates_session_then_authorizes_x_accel() -> None:
    app = build_app(downloads=Downloads())
    token = "T" * 43
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            first = await client.get(f"/d/{token}")
            assert first.status_code == 307
            assert first.headers["location"] == f"/d/{token}?s={'S' * 43}"
            granted = await client.get(first.headers["location"])
    assert granted.status_code == 200
    assert granted.headers["x-accel-redirect"] == "/__protected/files/aa/object"
    assert granted.headers["x-accel-limit-rate"] == "1024"
    assert granted.headers["content-disposition"].startswith("attachment;")


@pytest.mark.asyncio
async def test_hls_player_manifest_and_segment_use_protected_delivery() -> None:
    app = build_app(streams=Streams())
    token = "T" * 43
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            player = await client.get(f"/watch/{token}")
            manifest = await client.get(f"/hls/{token}/index.m3u8")
            segment = await client.get(f"/hls/{token}/0.ts")
    assert player.status_code == 200
    assert f"/hls/{token}/index.m3u8" in player.text
    assert manifest.text.startswith("#EXTM3U")
    assert segment.headers["x-accel-redirect"].startswith("/__protected/hls/")
    assert segment.headers["x-mdlbot-purpose"] == "stream"
