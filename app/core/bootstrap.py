"""Idempotent Stage 4 catalog and first-Super-Admin bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.catalogs import PERMISSIONS, PROFILES, ROLES, SETTINGS
from app.db.models.admin import Admin, AdminRole, Permission, RolePermission, Setting, SettingsProfile
from app.db.models.identity import User


CATALOG_NAMESPACE = UUID("e46c0ad7-b7ad-4d61-8850-5d1350ad85f2")


def catalog_id(kind: str, code: str) -> UUID:
    return uuid5(CATALOG_NAMESPACE, f"{kind}:{code}")


async def seed_catalogs(session: AsyncSession) -> None:
    permission_rows: dict[str, Permission] = {}
    for definition in PERMISSIONS:
        row = await session.scalar(select(Permission).where(Permission.code == definition.code))
        if row is None:
            row = Permission(id=catalog_id("permission", definition.code), code=definition.code)
            session.add(row)
        row.category = definition.category
        row.name_fa = definition.name_fa
        row.name_en = definition.name_en
        row.description_fa = definition.description_fa
        row.description_en = definition.description_en
        row.risk_level = definition.risk_level
        row.super_admin_only = definition.super_admin_only
        row.is_active = True
        permission_rows[definition.code] = row

    role_rows: dict[str, AdminRole] = {}
    for definition in ROLES:
        row = await session.scalar(select(AdminRole).where(AdminRole.code == definition.code))
        if row is None:
            row = AdminRole(id=catalog_id("role", definition.code), code=definition.code)
            session.add(row)
        row.name_fa = definition.name_fa
        row.name_en = definition.name_en
        row.description_fa = definition.description_fa
        row.description_en = definition.description_en
        row.is_system = True
        row.is_super_admin = definition.is_super_admin
        row.deleted_at = None
        role_rows[definition.code] = row
    await session.flush()

    for definition in ROLES:
        role = role_rows[definition.code]
        desired_ids = {permission_rows[code].id for code in definition.permissions}
        existing = list(
            (await session.scalars(select(RolePermission).where(RolePermission.role_id == role.id))).all()
        )
        existing_ids = {row.permission_id for row in existing}
        for permission_id in desired_ids - existing_ids:
            session.add(
                RolePermission(
                    id=catalog_id("role_permission", f"{role.id}:{permission_id}"),
                    role_id=role.id,
                    permission_id=permission_id,
                )
            )
        obsolete = existing_ids - desired_ids
        if obsolete:
            await session.execute(
                delete(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id.in_(obsolete),
                )
            )

    for definition in SETTINGS:
        row = await session.scalar(select(Setting).where(Setting.key == definition.key))
        if row is None:
            row = Setting(
                id=catalog_id("setting", definition.key),
                key=definition.key,
                value=definition.default,
                default_value=definition.default,
                version=1,
            )
            session.add(row)
        row.display_name_fa = definition.name_fa
        row.display_name_en = definition.name_en
        row.description_fa = definition.description_fa
        row.description_en = definition.description_en
        row.category = definition.category
        row.value_type = definition.value_type
        row.unit = definition.unit
        row.default_value = definition.default
        row.minimum = definition.minimum
        row.maximum = definition.maximum
        row.allowed_values = None if definition.allowed_values is None else list(definition.allowed_values)
        row.sensitive = False
        row.runtime_editable = definition.runtime_editable
        row.reload_type = definition.reload_type
        row.required_permission = definition.required_permission
        row.dependencies = dict(definition.dependencies or {})
        row.is_enabled = True

    for definition in PROFILES:
        row = await session.scalar(select(SettingsProfile).where(SettingsProfile.code == definition.code))
        if row is None:
            row = SettingsProfile(id=catalog_id("profile", definition.code), code=definition.code)
            session.add(row)
        row.name_fa = definition.name_fa
        row.name_en = definition.name_en
        row.description_fa = definition.description_fa
        row.description_en = definition.description_en
        row.values = dict(definition.values)
        row.is_system = definition.code != "custom"
        row.deleted_at = None
    await session.flush()


async def ensure_super_admin(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    language_code: str = "fa",
) -> Admin:
    if telegram_user_id <= 0:
        raise ValueError("initial Super Admin Telegram ID must be positive")
    if language_code not in {"fa", "en"}:
        raise ValueError("initial Super Admin language must be fa or en")
    role = await session.scalar(
        select(AdminRole).where(
            AdminRole.code == "super_admin",
            AdminRole.deleted_at.is_(None),
        )
    )
    if role is None:
        raise RuntimeError("catalogs must be seeded before creating the Super Admin")
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        user = User(
            telegram_user_id=telegram_user_id,
            language_code=language_code,
            status="active",
        )
        session.add(user)
        await session.flush()
    else:
        user.status = "active"
        user.deleted_at = None
    admin = await session.scalar(select(Admin).where(Admin.user_id == user.id))
    if admin is None:
        admin = Admin(
            user_id=user.id,
            role_id=role.id,
            status="active",
            language_code=language_code,
            starts_at=datetime.now(UTC),
            permission_use_count=0,
        )
        session.add(admin)
    else:
        admin.role_id = role.id
        admin.status = "active"
        admin.ends_at = None
        admin.suspended_at = None
        admin.suspension_reason = None
    await session.flush()
    return admin
