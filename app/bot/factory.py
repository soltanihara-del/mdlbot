"""Construct aiogram objects without global network or secret side effects."""

from __future__ import annotations

from dataclasses import dataclass
import re

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage

from app.bot.handlers import build_admin_router, build_user_router
from app.bot.middlewares import (
    AccessPolicyMiddleware,
    DatabaseMiddleware,
    ErrorMiddleware,
    UserContextMiddleware,
)
from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError
from app.core.i18n import LocalizationService
from app.core.permissions import AuthorizationService
from app.core.redis import RedisManager
from app.core.secrets import read_secret_file
from app.db.session import Database
from app.core.settings import SettingsService
from app.services.admission import AdmissionService
from app.services.quota import QuotaService
from app.services.downloads import DownloadService


BOT_TOKEN_RE = re.compile(r"^[0-9]{6,}:[A-Za-z0-9_-]{20,}$")


@dataclass(frozen=True, slots=True)
class BotComponents:
    bot: Bot
    dispatcher: Dispatcher


def create_bot_components(
    settings: RuntimeSettings,
    database: Database,
    redis: RedisManager,
    i18n: LocalizationService,
) -> BotComponents:
    settings.validate_bot_files(token=True, webhook=False)
    token = read_secret_file(settings.bot_token_file, minimum_length=30)  # type: ignore[arg-type]
    if BOT_TOKEN_RE.fullmatch(token) is None:
        raise ConfigurationError("BOT_TOKEN_FILE contains an invalid Telegram bot token")

    http_session = AiohttpSession(limit=100)
    http_session.api = TelegramAPIServer.from_base(
        settings.telegram_api_base_url,
        is_local=settings.telegram_api_mode == "local",
    )
    bot = Bot(
        token=token,
        session=http_session,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    storage = RedisStorage(
        redis.client,
        key_builder=DefaultKeyBuilder(
            prefix=f"{settings.redis_key_prefix}:fsm",
            with_bot_id=True,
        ),
        state_ttl=86400,
        data_ttl=86400,
    )
    dispatcher = Dispatcher(storage=storage, name="mdlbot")
    dispatcher.update.outer_middleware(ErrorMiddleware(i18n))
    dispatcher.update.outer_middleware(DatabaseMiddleware(database))
    dispatcher.update.outer_middleware(UserContextMiddleware())
    dispatcher.update.outer_middleware(AccessPolicyMiddleware(i18n, redis))
    authorization = AuthorizationService()
    admission = AdmissionService(SettingsService(authorization, redis), QuotaService())
    downloads = (
        DownloadService(settings, redis)
        if settings.download_signing_key_file is not None
        else None
    )
    dispatcher.include_router(build_admin_router(i18n, authorization))
    dispatcher.include_router(build_user_router(i18n, admission, downloads))
    return BotComponents(bot=bot, dispatcher=dispatcher)
