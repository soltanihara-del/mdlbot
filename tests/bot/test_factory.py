from pathlib import Path

import pytest
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.factory import create_bot_components
from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError
from app.core.i18n import LocalizationService
from app.core.redis import RedisManager
from app.db.session import Database


def write_secret(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_factory_uses_redis_fsm_and_local_api(tmp_path) -> None:
    settings = RuntimeSettings(
        app_env="test",
        service_name="bot",
        database_url="postgresql+psycopg://user:password@db/app",
        redis_url="redis://:password@cache/0",
        bot_token_file=write_secret(
            tmp_path / "bot-token",
            "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
        ),
        internal_service_token_file=write_secret(tmp_path / "internal", "I" * 48),
        telegram_api_base_url="http://telegram-bot-api:8081",
        telegram_api_mode="local",
        locales_path="locales",
    )
    redis = RedisManager(settings)
    await redis.start()
    i18n = LocalizationService("locales")
    i18n.load()
    components = create_bot_components(settings, Database(settings), redis, i18n)
    try:
        assert isinstance(components.dispatcher.storage, RedisStorage)
        assert components.bot.session.api.is_local is True
        assert {router.name for router in components.dispatcher.sub_routers} == {"admin", "user"}
    finally:
        await components.bot.session.close()
        await redis.close()


@pytest.mark.asyncio
async def test_factory_rejects_malformed_bot_token(tmp_path) -> None:
    settings = RuntimeSettings(
        app_env="test",
        service_name="bot",
        database_url="postgresql+psycopg://user:password@db/app",
        redis_url="redis://cache/0",
        bot_token_file=write_secret(tmp_path / "bot-token", "not-a-token-but-long-enough-value"),
        internal_service_token_file=write_secret(tmp_path / "internal", "I" * 48),
        locales_path="locales",
    )
    redis = RedisManager(settings)
    await redis.start()
    i18n = LocalizationService("locales")
    i18n.load()
    try:
        with pytest.raises(ConfigurationError):
            create_bot_components(settings, Database(settings), redis, i18n)
    finally:
        await redis.close()
