"""Users, consent, plans, quota accounting, restrictions, strikes, and appeals."""

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
    APPEAL_STATES,
    LANGUAGES,
    QUOTA_DIMENSIONS,
    QUOTA_WINDOWS,
    RESERVATION_STATES,
    RESTRICTION_STATES,
    SUBSCRIPTION_STATUSES,
    USAGE_DIRECTIONS,
    USER_STATUSES,
    enum_check,
)


class TermsVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "terms_versions"

    version: Mapped[str] = mapped_column(String(64), unique=True)
    body_fa: Mapped[str] = mapped_column(Text)
    body_en: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class PrivacyVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "privacy_versions"

    version: Mapped[str] = mapped_column(String(64), unique=True)
    body_fa: Mapped[str] = mapped_column(Text)
    body_en: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        enum_check("language_code", LANGUAGES, name="language_code"),
        enum_check("status", USER_STATUSES, name="status"),
        CheckConstraint("telegram_user_id > 0", name="positive_telegram_user_id"),
        Index("ix_users_status_created_at", "status", "created_at"),
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    language_code: Mapped[str] = mapped_column(String(2), default="fa", server_default="fa")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    preferred_date_format: Mapped[str] = mapped_column(String(32), default="locale", server_default="locale")
    preferred_digits: Mapped[str] = mapped_column(String(16), default="locale", server_default="locale")
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active")
    terms_version_accepted: Mapped[UUID | None] = mapped_column(
        ForeignKey("terms_versions.id", ondelete="RESTRICT")
    )
    privacy_version_accepted: Mapped[UUID | None] = mapped_column(
        ForeignKey("privacy_versions.id", ondelete="RESTRICT")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserConsent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "terms_version_id", "privacy_version_id", name="uq_user_consents_versions"
        ),
        Index("ix_user_consents_user_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    terms_version_id: Mapped[UUID] = mapped_column(ForeignKey("terms_versions.id", ondelete="RESTRICT"))
    privacy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("privacy_versions.id", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(String(32), default="telegram", server_default="telegram")
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger)


class SubscriptionPlan(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint("max_file_size > 0", name="positive_max_file_size"),
        CheckConstraint("concurrent_jobs > 0", name="positive_concurrent_jobs"),
        CheckConstraint("concurrent_downloads > 0", name="positive_concurrent_downloads"),
        CheckConstraint("concurrent_streams > 0", name="positive_concurrent_streams"),
        CheckConstraint("retention_seconds > 0", name="positive_retention_seconds"),
        CheckConstraint("queue_priority >= 0", name="nonnegative_queue_priority"),
    )

    code: Mapped[str] = mapped_column(String(64), unique=True)
    name_fa: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    max_file_size: Mapped[int] = mapped_column(BigInteger)
    quota_bytes: Mapped[int | None] = mapped_column(BigInteger)
    quota_window_seconds: Mapped[int | None] = mapped_column(Integer)
    hourly_quota: Mapped[int | None] = mapped_column(BigInteger)
    daily_quota: Mapped[int | None] = mapped_column(BigInteger)
    weekly_quota: Mapped[int | None] = mapped_column(BigInteger)
    max_files_per_window: Mapped[int | None] = mapped_column(Integer)
    concurrent_jobs: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    concurrent_downloads: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    concurrent_streams: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    storage_quota: Mapped[int | None] = mapped_column(BigInteger)
    active_link_limit: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    download_connection_limit: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    stream_connection_limit: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    allowed_ips_per_session: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    resume_limit: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    range_request_limit: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
    download_rate: Mapped[int | None] = mapped_column(BigInteger)
    stream_rate: Mapped[int | None] = mapped_column(BigInteger)
    retention_seconds: Mapped[int] = mapped_column(Integer)
    public_retention_seconds: Mapped[int | None] = mapped_column(Integer)
    queue_priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    media_priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_stream_quality: Mapped[str] = mapped_column(String(32), default="original", server_default="original")
    public_share_limit: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    support_ticket_limit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    external_url_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    streaming_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    public_share_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    permanent_link_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    one_time_link_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    password_link_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class UserSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        enum_check("status", SUBSCRIPTION_STATUSES, name="status"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="valid_period"),
        Index(
            "uq_user_subscriptions_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_user_subscriptions_expiry", "status", "ends_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("subscription_plans.id", ondelete="RESTRICT"))
    fallback_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    grant_reason: Mapped[str | None] = mapped_column(Text)


class UserQuotaOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_quota_overrides"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="valid_period"),
        Index("ix_user_quota_overrides_active", "user_id", "ends_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    overrides: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text)


class QuotaBucket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quota_buckets"
    __table_args__ = (
        enum_check("dimension", QUOTA_DIMENSIONS, name="dimension"),
        enum_check("window_kind", QUOTA_WINDOWS, name="window_kind"),
        CheckConstraint("window_end > window_start", name="valid_window"),
        CheckConstraint("quota_limit IS NULL OR quota_limit >= 0", name="nonnegative_limit"),
        CheckConstraint("committed_amount >= 0", name="nonnegative_committed"),
        CheckConstraint("reserved_amount >= 0", name="nonnegative_reserved"),
        CheckConstraint(
            "quota_limit IS NULL OR committed_amount + reserved_amount <= quota_limit",
            name="within_quota_limit",
        ),
        CheckConstraint("row_version > 0", name="positive_row_version"),
        UniqueConstraint(
            "user_id", "dimension", "window_kind", "window_start", "window_end",
            name="uq_quota_buckets_identity",
        ),
        Index("ix_quota_buckets_expiry", "window_end"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    dimension: Mapped[str] = mapped_column(String(32))
    window_kind: Mapped[str] = mapped_column(String(16))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quota_limit: Mapped[int | None] = mapped_column(BigInteger)
    committed_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    reserved_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class QuotaReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quota_reservations"
    __table_args__ = (
        enum_check("dimension", QUOTA_DIMENSIONS, name="dimension"),
        enum_check("state", RESERVATION_STATES, name="state"),
        CheckConstraint("reserved_amount > 0", name="positive_reserved_amount"),
        CheckConstraint("consumed_amount >= 0 AND consumed_amount <= reserved_amount", name="valid_consumed_amount"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        Index(
            "uq_quota_reservations_active_job_bucket",
            "job_id", "quota_bucket_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
        Index("ix_quota_reservations_reconcile", "state", "expires_at"),
        Index("ix_quota_reservations_user_state", "user_id", "state"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    quota_bucket_id: Mapped[UUID] = mapped_column(ForeignKey("quota_buckets.id", ondelete="CASCADE"))
    dimension: Mapped[str] = mapped_column(String(32))
    reserved_amount: Mapped[int] = mapped_column(BigInteger)
    consumed_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    state: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        enum_check("dimension", QUOTA_DIMENSIONS, name="dimension"),
        enum_check("direction", USAGE_DIRECTIONS, name="direction"),
        CheckConstraint("amount > 0", name="positive_amount"),
        UniqueConstraint("idempotency_key", name="uq_usage_records_idempotency_key"),
        Index("ix_usage_records_user_created", "user_id", "created_at"),
        Index("ix_usage_records_job", "job_id"),
        Index("ix_usage_records_session", "session_id"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    quota_bucket_id: Mapped[UUID | None] = mapped_column(ForeignKey("quota_buckets.id", ondelete="SET NULL"))
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("quota_reservations.id", ondelete="SET NULL")
    )
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    session_id: Mapped[UUID | None]
    dimension: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8), default="debit", server_default="debit")
    amount: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class Ban(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bans"
    __table_args__ = (
        CheckConstraint("expires_at IS NULL OR expires_at > starts_at", name="valid_period"),
        Index("ix_bans_active_user", "user_id", "revoked_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(64))
    public_reason_fa: Mapped[str] = mapped_column(Text)
    public_reason_en: Mapped[str] = mapped_column(Text)
    internal_note: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class UserRestriction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_restrictions"
    __table_args__ = (
        enum_check("state", RESTRICTION_STATES, name="state"),
        CheckConstraint("expires_at IS NULL OR expires_at > starts_at", name="valid_period"),
        Index("ix_user_restrictions_effective", "user_id", "state", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    restriction_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    reason_code: Mapped[str] = mapped_column(String(64))
    internal_note: Mapped[str | None] = mapped_column(Text)
    public_explanation_fa: Mapped[str] = mapped_column(Text)
    public_explanation_en: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    related_file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    related_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    appeal_allowed: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class UserStrike(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_strikes"
    __table_args__ = (
        CheckConstraint("score > 0", name="positive_score"),
        Index("ix_user_strikes_active", "user_id", "revoked_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    related_file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    related_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    related_security_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("security_events.id", ondelete="SET NULL")
    )
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class UserAppeal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_appeals"
    __table_args__ = (
        enum_check("status", APPEAL_STATES, name="status"),
        Index(
            "uq_user_appeals_one_pending_per_restriction",
            "restriction_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_user_appeals_status_created", "status", "created_at"),
    )

    restriction_id: Mapped[UUID] = mapped_column(ForeignKey("user_restrictions.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    reviewed_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
