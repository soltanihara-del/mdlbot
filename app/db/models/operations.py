"""Security events, abuse actions, blocklists, backups, and restore history."""

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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.constants import (
    BACKUP_STATES,
    RESTORE_STATES,
    SECURITY_EVENT_STATES,
    SEVERITIES,
    enum_check,
)


class SecurityEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "security_events"
    __table_args__ = (
        enum_check("severity", SEVERITIES, name="severity"),
        enum_check("status", SECURITY_EVENT_STATES, name="status"),
        Index("ix_security_events_triage", "status", "severity", "created_at"),
        Index("ix_security_events_user_created", "user_id", "created_at"),
        Index("ix_security_events_job_created", "job_id", "created_at"),
        Index("ix_security_events_fingerprint", "fingerprint", "created_at"),
    )

    event_type: Mapped[str] = mapped_column(String(96))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="open", server_default="open")
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    session_type: Mapped[str | None] = mapped_column(String(16))
    session_id: Mapped[UUID | None]
    source_ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    fingerprint: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    automatic_action: Mapped[str | None] = mapped_column(String(96))
    resolved_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class AbuseAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "abuse_actions"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="valid_period"),
        Index("ix_abuse_actions_user_active", "user_id", "revoked_at", "ends_at"),
        Index("ix_abuse_actions_ip_active", "source_ip_hash", "revoked_at", "ends_at"),
    )

    security_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("security_events.id", ondelete="SET NULL")
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    token_id: Mapped[UUID | None]
    action_type: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(24))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class DomainBlocklist(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "domain_blocklist"
    __table_args__ = (
        CheckConstraint("domain = lower(domain)", name="normalized_lowercase_domain"),
        UniqueConstraint("domain", name="uq_domain_blocklist_domain"),
        Index("ix_domain_blocklist_enabled", "is_enabled", "domain"),
    )

    domain: Mapped[str] = mapped_column(String(253))
    include_subdomains: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    reason_code: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class FileHashBlocklist(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "file_hash_blocklist"
    __table_args__ = (
        CheckConstraint("octet_length(sha256) = 32", name="sha256_length"),
        UniqueConstraint("sha256", name="uq_file_hash_blocklist_sha256"),
        Index("ix_file_hash_blocklist_enabled", "is_enabled"),
    )

    sha256: Mapped[bytes] = mapped_column(LargeBinary(32))
    reason_code: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class Backup(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "backups"
    __table_args__ = (
        enum_check("status", BACKUP_STATES, name="status"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("checksum_sha256 IS NULL OR octet_length(checksum_sha256) = 32", name="checksum_length"),
        Index("ix_backups_status_created", "status", "created_at"),
    )

    backup_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="creating", server_default="creating")
    format_version: Mapped[str] = mapped_column(String(32))
    application_version: Mapped[str] = mapped_column(String(64))
    schema_revision: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(512), unique=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    encrypted: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    encryption_key_version: Mapped[int | None] = mapped_column(Integer)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_result: Mapped[str | None] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class BackupDestination(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "backup_destinations"

    name: Mapped[str] = mapped_column(String(128), unique=True)
    destination_type: Mapped[str] = mapped_column(String(24))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    secret_reference: Mapped[str] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    retention_count: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    created_by_admin_id: Mapped[UUID | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))


class RestoreHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "restore_history"
    __table_args__ = (
        enum_check("status", RESTORE_STATES, name="status"),
        Index("ix_restore_history_status_created", "status", "created_at"),
    )

    backup_id: Mapped[UUID] = mapped_column(ForeignKey("backups.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    requested_by_admin_id: Mapped[UUID] = mapped_column(ForeignKey("admins.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
    source_schema_revision: Mapped[str] = mapped_column(String(64))
    target_schema_revision: Mapped[str] = mapped_column(String(64))
    safety_backup_id: Mapped[UUID | None] = mapped_column(ForeignKey("backups.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    rollback_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

