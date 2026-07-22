import httpx
import pytest

from app.api.app import create_app
from app.bot.server import UpdateDeduplicator
from app.core.config import RuntimeSettings
from app.core.i18n import LocalizationService


class Dependency:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def healthcheck(self) -> bool:
        return True


class Proxy:
    def __init__(self) -> None:
        self.payloads = []

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def validate(self, path: str | None, secret: str | None) -> None:
        if path != "path-secret" or secret != "telegram-secret":
            raise PermissionError

    async def forward(self, payload) -> None:
        self.payloads.append(payload)


def build_webhook_app(proxy: Proxy):
    settings = RuntimeSettings(
        app_env="test",
        service_name="api",
        database_url="postgresql+psycopg://user:password@db/app",
        redis_url="redis://cache/0",
        locales_path="locales",
        log_format="console",
    )
    return create_app(
        settings,
        database=Dependency(),  # type: ignore[arg-type]
        redis=Dependency(),  # type: ignore[arg-type]
        localization=LocalizationService("locales"),
        webhook_proxy=proxy,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_public_webhook_requires_both_secrets_and_forwards_valid_update() -> None:
    proxy = Proxy()
    app = build_webhook_app(proxy)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.post("/telegram/webhook", json={"update_id": 1})
            assert denied.status_code == 403
            accepted = await client.post(
                "/telegram/webhook",
                json={"update_id": 1, "message": {"message_id": 1}},
                headers={
                    "X-MDLBot-Webhook-Path": "path-secret",
                    "X-Telegram-Bot-Api-Secret-Token": "telegram-secret",
                },
            )
            assert accepted.status_code == 200
    assert proxy.payloads == [{"update_id": 1, "message": {"message_id": 1}}]


def test_update_payload_digest_is_canonical() -> None:
    left = UpdateDeduplicator.digest({"update_id": 1, "message": {"text": "x"}})
    right = UpdateDeduplicator.digest({"message": {"text": "x"}, "update_id": 1})
    assert left == right
    assert len(left) == 32
