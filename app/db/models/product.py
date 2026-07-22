"""Forced membership, advertisements, public publishing, support, and broadcasts."""

from __future__ import annotations

from datetime import datetime
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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.constants import (
    BROADCAST_RESULT_STATES,
    BROADCAST_STATES,
    LANGUAGES,
    PUBLIC_REQUEST_STATES,
    REPORT_STATES,
    TICKET_STATES,
    enum_check,
)


class ForcedJoinChannel(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "forced_join_channels"
    __table_args__ = (
        CheckConstraint("telegram_chat_id <> 0", name="nonzero_chat_id"),
        Index("ix_forced_join_channels_enabled_order", "is_enabled", "display_order"),
    )

    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    join_url: Mapped[str] = mapped_column(String(2048))
    title_fa: Mapped[str] = mapped_column(String(255))
    title_en: Mapped[str] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    membership_cache_seconds: Mapped[int] = mapped_column(Integer, default=300, server_default="300")


class Advertisement(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "advertisements"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="valid_period"),
        CheckConstraint("click_count >= 0", name="nonnegative_click_count"),
        Index("ix_advertisements_active_period", "is_enabled", "starts_at", "ends_at"),
    )

    name: Mapped[str] = mapped_column(String(128), unique=True)
    text_fa: Mapped[str] = mapped_column(Text)
    text_en: Mapped[str] = mapped_column(Text)
    target_url: Mapped[str] = mapped_column(String(2048))
    plan_codes: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    click_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    click_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class PublicCategory(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "public_categories"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    title_fa: Mapped[str] = mapped_column(String(255))
    title_en: Mapped[str] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class PublicShareRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_share_requests"
    __table_args__ = (
        enum_check("status", PUBLIC_REQUEST_STATES, name="status"),
        CheckConstraint("language_mode IN ('fa', 'en', 'bilingual')", name="language_mode"),
        Index("ix_public_share_requests_review", "status", "created_at"),
        Index("ix_public_share_requests_user", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    file_reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("file_references.id", ondelete="RESTRICT")
    )
    category_id: Mapped[UUID] = mapped_column(ForeignKey("public_categories.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    language_mode: Mapped[str] = mapped_column(String(16), default="fa", server_default="fa")
    title_fa: Mapped[str | None] = mapped_column(String(512))
    title_en: Mapped[str | None] = mapped_column(String(512))
    description_fa: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    rights_confirmed: Mapped[bool] = mapped_column(Boolean)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    reviewed_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)


class PublicChannelPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_channel_posts"
    __table_args__ = (
        UniqueConstraint("channel_id", "telegram_message_id", name="uq_public_channel_posts_message"),
        Index(
            "uq_public_channel_posts_active_request_channel",
            "share_request_id", "channel_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_public_channel_posts_expiry", "expires_at", "removed_at"),
    )

    share_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("public_share_requests.id", ondelete="CASCADE")
    )
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    language_mode: Mapped[str] = mapped_column(String(16))
    published_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "file_reports"
    __table_args__ = (
        enum_check("status", REPORT_STATES, name="status"),
        UniqueConstraint("public_post_id", "reporter_user_id", name="uq_file_reports_reporter_post"),
        Index("ix_file_reports_review", "status", "created_at"),
    )

    public_post_id: Mapped[UUID] = mapped_column(
        ForeignKey("public_channel_posts.id", ondelete="CASCADE")
    )
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    reporter_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason_code: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    reviewed_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text)


class SupportTicket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        enum_check("status", TICKET_STATES, name="status"),
        enum_check("user_language", LANGUAGES, name="user_language"),
        Index("ix_support_tickets_assignment", "status", "assigned_admin_id", "created_at"),
        Index("ix_support_tickets_user", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    subject: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    user_language: Mapped[str] = mapped_column(String(2))
    assigned_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SupportMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        CheckConstraint(
            "(sender_type = 'user' AND sender_user_id IS NOT NULL AND sender_admin_id IS NULL) OR "
            "(sender_type = 'admin' AND sender_admin_id IS NOT NULL AND sender_user_id IS NULL) OR "
            "(sender_type = 'system' AND sender_user_id IS NULL AND sender_admin_id IS NULL)",
            name="valid_sender",
        ),
        Index("ix_support_messages_ticket_created", "ticket_id", "created_at"),
    )

    ticket_id: Mapped[UUID] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"))
    sender_type: Mapped[str] = mapped_column(String(16))
    sender_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sender_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    message_type: Mapped[str] = mapped_column(String(24))
    body: Mapped[str | None] = mapped_column(Text)
    telegram_file_id: Mapped[str | None] = mapped_column(String(1024))
    reply_to_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_messages.id", ondelete="SET NULL")
    )


class Broadcast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "broadcasts"
    __table_args__ = (
        enum_check("status", BROADCAST_STATES, name="status"),
        CheckConstraint("target_language IN ('fa', 'en', 'all')", name="target_language"),
        CheckConstraint("success_count >= 0", name="nonnegative_success_count"),
        CheckConstraint("failure_count >= 0", name="nonnegative_failure_count"),
        CheckConstraint("blocked_count >= 0", name="nonnegative_blocked_count"),
        CheckConstraint("deactivated_count >= 0", name="nonnegative_deactivated_count"),
        Index("ix_broadcasts_worker", "status", "scheduled_at", "created_at"),
    )

    created_by_admin_id: Mapped[UUID] = mapped_column(ForeignKey("admins.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    target_language: Mapped[str] = mapped_column(String(8), default="all", server_default="all")
    target_filter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    payload_fa: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload_en: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    target_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    success_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    failure_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    blocked_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    deactivated_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BroadcastResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "broadcast_results"
    __table_args__ = (
        enum_check("status", BROADCAST_RESULT_STATES, name="status"),
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_results_recipient"),
        Index("ix_broadcast_results_resume", "broadcast_id", "status"),
    )

    broadcast_id: Mapped[UUID] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    language_code: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(96))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
