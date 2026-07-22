"""Administrator RBAC, confirmations, audit, settings, and translation overrides."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.constants import (
    ADMIN_STATUSES,
    CONFIRMATION_STATES,
    LANGUAGES,
    PERMISSION_EFFECTS,
    RELOAD_TYPES,
    SETTING_VALUE_TYPES,
    enum_check,
)


class AdminRole(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "admin_roles"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name_fa: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str] = mapped_column(String(128))
    description_fa: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (
        CheckConstraint("risk_level IN ('low', 'medium', 'high', 'critical')", name="risk_level"),
        Index("ix_permissions_category_code", "category", "code"),
    )

    code: Mapped[str] = mapped_column(String(128), unique=True)
    category: Mapped[str] = mapped_column(String(64))
    name_fa: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str] = mapped_column(String(255))
    description_fa: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(16))
    super_admin_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class RolePermission(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),)

    role_id: Mapped[UUID] = mapped_column(ForeignKey("admin_roles.id", ondelete="CASCADE"))
    permission_id: Mapped[UUID] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"))


class Admin(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admins"
    __table_args__ = (
        enum_check("status", ADMIN_STATUSES, name="status"),
        enum_check("language_code", LANGUAGES, name="language_code"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="valid_period"),
        CheckConstraint("max_permission_uses IS NULL OR max_permission_uses > 0", name="positive_max_uses"),
        CheckConstraint("permission_use_count >= 0", name="nonnegative_use_count"),
        Index("ix_admins_status_expiry", "status", "ends_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("admin_roles.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    language_code: Mapped[str] = mapped_column(String(2), default="fa", server_default="fa")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    preferred_date_format: Mapped[str] = mapped_column(String(32), default="locale", server_default="locale")
    preferred_digits: Mapped[str] = mapped_column(String(16), default="locale", server_default="locale")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_permission_uses: Mapped[int | None] = mapped_column(BigInteger)
    permission_use_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    added_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(Text)


class AdminPermissionOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_permission_overrides"
    __table_args__ = (
        enum_check("effect", PERMISSION_EFFECTS, name="effect"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="valid_period"),
        UniqueConstraint("admin_id", "permission_id", name="uq_admin_permission_overrides_pair"),
        Index("ix_admin_permission_overrides_active", "admin_id", "ends_at"),
    )

    admin_id: Mapped[UUID] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    permission_id: Mapped[UUID] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"))
    effect: Mapped[str] = mapped_column(String(8))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    granted_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class AdminScope(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_scopes"
    __table_args__ = (
        UniqueConstraint("admin_id", "scope_type", name="uq_admin_scopes_type"),
        CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="valid_period"),
    )

    admin_id: Mapped[UUID] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    scope_type: Mapped[str] = mapped_column(String(64))
    constraints_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_sessions"
    __table_args__ = (
        CheckConstraint("octet_length(session_token_hash) >= 32", name="token_hash_minimum"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        UniqueConstraint("session_token_hash", name="uq_admin_sessions_token_hash"),
        Index("ix_admin_sessions_admin_expiry", "admin_id", "expires_at", "revoked_at"),
    )

    admin_id: Mapped[UUID] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    session_token_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    source_ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    user_agent_hash: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(128))


class AdminConfirmation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_confirmations"
    __table_args__ = (
        enum_check("status", CONFIRMATION_STATES, name="status"),
        CheckConstraint("octet_length(token_hash) >= 32", name="token_hash_minimum"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        CheckConstraint("required_approvals > 0", name="positive_required_approvals"),
        UniqueConstraint("token_hash", name="uq_admin_confirmations_token_hash"),
        UniqueConstraint("action_key", name="uq_admin_confirmations_action_key"),
        Index("ix_admin_confirmations_admin_status", "admin_id", "status", "expires_at"),
    )

    admin_id: Mapped[UUID] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    action_key: Mapped[str] = mapped_column(String(192))
    action: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    reason: Mapped[str] = mapped_column(Text)
    required_approvals: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminApproval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_approvals"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="decision"),
        UniqueConstraint("confirmation_id", "approver_admin_id", name="uq_admin_approvals_approver"),
        Index("ix_admin_approvals_confirmation", "confirmation_id", "created_at"),
    )

    confirmation_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_confirmations.id", ondelete="CASCADE")
    )
    approver_admin_id: Mapped[UUID] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)


class AdminAuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("ix_admin_audit_logs_admin_created", "admin_id", "created_at"),
        Index("ix_admin_audit_logs_target_created", "target_type", "target_id", "created_at"),
        Index("ix_admin_audit_logs_action_created", "action", "created_at"),
    )

    admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    permission: Mapped[str | None] = mapped_column(String(128))
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(96))
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger)
    request_id: Mapped[str | None] = mapped_column(String(128))
    previous_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    record_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))


class Setting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settings"
    __table_args__ = (
        enum_check("value_type", SETTING_VALUE_TYPES, name="value_type"),
        enum_check("reload_type", RELOAD_TYPES, name="reload_type"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_.-]{1,127}$'", name="key_format"),
        CheckConstraint("minimum IS NULL OR maximum IS NULL OR minimum <= maximum", name="valid_numeric_range"),
        CheckConstraint("version > 0", name="positive_version"),
        Index("ix_settings_category_key", "category", "key"),
    )

    key: Mapped[str] = mapped_column(String(128), unique=True)
    display_name_fa: Mapped[str] = mapped_column(String(255))
    display_name_en: Mapped[str] = mapped_column(String(255))
    description_fa: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64))
    value_type: Mapped[str] = mapped_column(String(24))
    unit: Mapped[str | None] = mapped_column(String(32))
    value: Mapped[Any] = mapped_column(JSONB)
    default_value: Mapped[Any] = mapped_column(JSONB)
    minimum: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    maximum: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    allowed_values: Mapped[list[Any] | None] = mapped_column(JSONB)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    runtime_editable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    reload_type: Mapped[str] = mapped_column(String(24), default="hot_reload", server_default="hot_reload")
    required_permission: Mapped[str] = mapped_column(String(128))
    dependencies: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class SettingsHistory(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "settings_history"
    __table_args__ = (
        CheckConstraint("version > 0", name="positive_version"),
        UniqueConstraint("setting_id", "version", name="uq_settings_history_version"),
        Index("ix_settings_history_setting_created", "setting_id", "created_at"),
    )

    setting_id: Mapped[UUID] = mapped_column(ForeignKey("settings.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    old_value: Mapped[Any] = mapped_column(JSONB)
    new_value: Mapped[Any] = mapped_column(JSONB)
    changed_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text)
    rollback_of_history_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("settings_history.id", ondelete="SET NULL")
    )


class SettingsProfile(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "settings_profiles"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name_fa: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str] = mapped_column(String(128))
    description_fa: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str] = mapped_column(Text)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class TranslationOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "translation_overrides"
    __table_args__ = (
        enum_check("locale", LANGUAGES, name="locale"),
        CheckConstraint("message_key ~ '^[a-z][a-z0-9_.-]{1,191}$'", name="message_key_format"),
        UniqueConstraint("locale", "message_key", name="uq_translation_overrides_key"),
        Index("ix_translation_overrides_locale_enabled", "locale", "is_enabled"),
    )

    locale: Mapped[str] = mapped_column(String(2))
    message_key: Mapped[str] = mapped_column(String(192))
    value: Mapped[str] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    changed_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
