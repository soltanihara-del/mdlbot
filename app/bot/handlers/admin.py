"""Permission-filtered, read-only Stage 5 Telegram administrator panel."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import AdminCallback
from app.bot.keyboards import ADMIN_SECTIONS, admin_menu
from app.bot.repositories import AdminRepository
from app.core.errors import PermissionDenied
from app.core.i18n import LocalizationService
from app.core.permissions import AuthorizationRequest, AuthorizationService
from app.db.models.admin import Admin, Setting
from app.db.models.identity import User


SECTION_PERMISSIONS = {section: permission for section, _label, permission in ADMIN_SECTIONS}
SECTION_LABELS = {section: label for section, label, _permission in ADMIN_SECTIONS}


def build_admin_router(
    i18n: LocalizationService,
    authorization: AuthorizationService,
) -> Router:
    router = Router(name="admin")
    repository = AdminRepository()

    async def allowed_navigation(session: AsyncSession, admin: Admin) -> set[str]:
        allowed: set[str] = set()
        for permission in sorted(set(SECTION_PERMISSIONS.values()) | {"dashboard.view"}):
            decision = await authorization.evaluate(
                session,
                AuthorizationRequest(admin_id=admin.id, permission=permission),
            )
            if decision.allowed:
                allowed.add(permission)
        return allowed

    @router.message(Command("admin"))
    async def panel(
        message: Message,
        admin_record: Admin | None,
        session: AsyncSession,
        locale: str,
    ) -> None:
        if admin_record is None:
            raise PermissionDenied("administrator account is required")
        await authorization.require(
            session,
            AuthorizationRequest(admin_id=admin_record.id, permission="dashboard.view"),
        )
        permissions = await allowed_navigation(session, admin_record)
        await message.answer(
            i18n.format(locale, "admin-panel-title"),
            reply_markup=admin_menu(i18n, locale, permissions),
        )

    @router.callback_query(AdminCallback.filter())
    async def section(
        callback: CallbackQuery,
        callback_data: AdminCallback,
        admin_record: Admin | None,
        session: AsyncSession,
        locale: str,
    ) -> None:
        if admin_record is None or callback_data.section not in SECTION_PERMISSIONS:
            raise PermissionDenied("administrator section is unavailable")
        permission = SECTION_PERMISSIONS[callback_data.section]
        await authorization.require(
            session,
            AuthorizationRequest(admin_id=admin_record.id, permission=permission),
        )
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if callback_data.section == "settings":
            count = int(await session.scalar(select(func.count()).select_from(Setting)) or 0)
            await callback.message.answer(i18n.format(locale, "admin-settings-summary", count=count))
            return
        if callback_data.section == "users":
            count = int(await session.scalar(select(func.count()).select_from(User)) or 0)
            await callback.message.answer(i18n.format(locale, "admin-users-summary", count=count))
            return
        await callback.message.answer(
            i18n.format(
                locale,
                "admin-section-opened",
                section=i18n.format(locale, SECTION_LABELS[callback_data.section]),
            )
        )

    @router.message(Command("dashboard"))
    async def dashboard(
        message: Message,
        admin_record: Admin | None,
        session: AsyncSession,
        locale: str,
    ) -> None:
        if admin_record is None:
            raise PermissionDenied("administrator account is required")
        await authorization.require(
            session,
            AuthorizationRequest(admin_id=admin_record.id, permission="dashboard.view"),
        )
        counts = await repository.dashboard_counts(session)
        await message.answer(i18n.format(locale, "admin-dashboard-summary", **counts))

    return router
