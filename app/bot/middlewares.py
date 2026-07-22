"""Database, identity, access-policy, and localized error middleware."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import LanguageCallback
from app.bot.keyboards import forced_join_keyboard
from app.bot.repositories import AdminRepository, UserRepository
from app.core.errors import ApplicationError
from app.core.i18n import LocalizationService
from app.core.logging import get_logger
from app.core.redis import RedisManager
from app.db.models.identity import Ban, User
from app.db.models.product import ForcedJoinChannel
from app.db.session import Database


Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


def _telegram_user(update: Update):
    if update.message is not None:
        return update.message.from_user
    if update.callback_query is not None:
        return update.callback_query.from_user
    if update.inline_query is not None:
        return update.inline_query.from_user
    return None


async def _respond(update: Update, text: str, **kwargs: Any) -> None:
    if update.callback_query is not None:
        await update.callback_query.answer()
        if isinstance(update.callback_query.message, Message):
            await update.callback_query.message.answer(text, **kwargs)
        return
    if update.message is not None:
        await update.message.answer(text, **kwargs)


class ErrorMiddleware(BaseMiddleware):
    def __init__(self, i18n: LocalizationService) -> None:
        self._i18n = i18n
        self._log = get_logger("bot.errors")

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        try:
            return await handler(event, data)
        except ApplicationError as exc:
            locale = data.get("locale", "fa")
            key = {
                "permission_denied": "error-permission-denied",
                "dependency_unavailable": "error-dependency-unavailable",
                "settings_validation_error": "error-setting-validation",
            }.get(exc.code, "error-application")
            self._log.warning("bot_application_error", error_code=exc.code, context=exc.context)
            if isinstance(event, Update):
                await _respond(event, self._i18n.format(locale, key))
            return None


class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with self._database.transaction() as session:
            data["session"] = session
            return await handler(event, data)


class UserContextMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._users = UserRepository()
        self._admins = AdminRepository()

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        telegram = _telegram_user(event)
        if telegram is None or telegram.is_bot:
            return await handler(event, data)
        session: AsyncSession = data["session"]
        user = await self._users.get_or_create(session, telegram)
        data["user_record"] = user
        data["locale"] = user.language_code
        data["admin_record"] = await self._admins.for_user(session, user)
        return await handler(event, data)


class AccessPolicyMiddleware(BaseMiddleware):
    def __init__(
        self,
        i18n: LocalizationService,
        redis: RedisManager,
    ) -> None:
        self._i18n = i18n
        self._redis = redis

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        user: User | None = data.get("user_record")
        if user is None or user.language_selected_at is None:
            return await handler(event, data)
        if data.get("admin_record") is not None:
            return await handler(event, data)
        if event.message is not None and event.message.text == "/start":
            return await handler(event, data)
        if event.callback_query is not None and str(event.callback_query.data or "").startswith(
            "lang:"
        ):
            return await handler(event, data)

        session: AsyncSession = data["session"]
        locale: str = data["locale"]
        now = datetime.now(UTC)
        ban = await session.scalar(
            select(Ban).where(
                Ban.user_id == user.id,
                Ban.revoked_at.is_(None),
                Ban.starts_at <= now,
                or_(Ban.expires_at.is_(None), Ban.expires_at > now),
            )
        )
        if ban is not None:
            explanation = ban.public_reason_fa if locale == "fa" else ban.public_reason_en
            await _respond(event, self._i18n.format(locale, "access-banned", reason=explanation))
            return None

        channels = list(
            (
                await session.scalars(
                    select(ForcedJoinChannel)
                    .where(
                        ForcedJoinChannel.is_enabled.is_(True),
                        ForcedJoinChannel.deleted_at.is_(None),
                    )
                    .order_by(ForcedJoinChannel.display_order)
                )
            ).all()
        )
        if not channels:
            return await handler(event, data)
        bot: Bot = data["bot"]
        missing: list[ForcedJoinChannel] = []
        for channel in channels:
            cache_key = f"membership:{user.id}:{channel.telegram_chat_id}"
            cached = None
            try:
                cached = await self._redis.get_json(cache_key)
            except Exception:
                cached = None
            is_member = cached is True
            if cached is None:
                try:
                    member = await bot.get_chat_member(channel.telegram_chat_id, user.telegram_user_id)
                    is_member = member.status not in {
                        ChatMemberStatus.LEFT,
                        ChatMemberStatus.KICKED,
                    } and (member.status != ChatMemberStatus.RESTRICTED or bool(member.is_member))
                    await self._redis.set_json(
                        cache_key,
                        is_member,
                        ttl_seconds=channel.membership_cache_seconds,
                    )
                except Exception:
                    await _respond(event, self._i18n.format(locale, "error-dependency-unavailable"))
                    return None
            if not is_member:
                missing.append(channel)
        if missing:
            labels = [
                ((channel.title_fa if locale == "fa" else channel.title_en), channel.join_url)
                for channel in missing
            ]
            await _respond(
                event,
                self._i18n.format(locale, "forced-join-required"),
                reply_markup=forced_join_keyboard(labels),
            )
            return None
        return await handler(event, data)
