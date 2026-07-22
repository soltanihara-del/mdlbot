from pathlib import Path

import httpx
import pytest

from app.api.app import create_app
from app.core.config import RuntimeSettings
from app.core.i18n import LocalizationService


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


def build_app(*, database_healthy: bool = True):
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
