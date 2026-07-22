"""Stored files, scans, links, sessions, media variants, and traffic accounting."""

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

from app.db.base import Base, CreatedAtMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.constants import (
    FILE_STATES,
    LINK_STATES,
    MEDIA_KINDS,
    MEDIA_VARIANT_STATES,
    SCAN_STATES,
    SESSION_STATES,
    TOKEN_PURPOSES,
    enum_check,
)


class File(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "files"
    __table_args__ = (
        enum_check("status", FILE_STATES, name="status"),
        enum_check("scan_status", SCAN_STATES, name="scan_status"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("retention_seconds > 0", name="positive_retention"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        CheckConstraint("sha256 IS NULL OR octet_length(sha256) = 32", name="sha256_length"),
        Index("ix_files_owner_status", "owner_user_id", "status"),
        Index("ix_files_expiry", "status", "expires_at"),
        Index("ix_files_sha256_size", "sha256", "size_bytes"),
        Index("ix_files_created_by_job", "created_by_job_id"),
    )

    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_by_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), unique=True
    )
    source_type: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(32), default="incoming", server_default="incoming")
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str] = mapped_column(String(1024))
    safe_display_filename: Mapped[str] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    detected_mime: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    reported_mime: Mapped[str | None] = mapped_column(String(255))
    scan_status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    media_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    direct_play_compatible: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    retention_seconds: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deletion_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unavailable_reason: Mapped[str | None] = mapped_column(String(96))


class FileReference(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "file_references"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        UniqueConstraint("user_id", "file_id", "source_job_id", name="uq_file_references_owner_source"),
        Index("ix_file_references_user_expiry", "user_id", "expires_at"),
        Index("ix_file_references_file_active", "file_id", "deleted_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    source_job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    display_filename: Mapped[str] = mapped_column(String(1024))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class FileScanResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "file_scan_results"
    __table_args__ = (
        enum_check("status", SCAN_STATES, name="status"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="valid_scan_period"),
        UniqueConstraint("file_id", "scanner", "scanner_version", name="uq_file_scan_results_run"),
        Index("ix_file_scan_results_status", "status", "created_at"),
    )

    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    scanner: Mapped[str] = mapped_column(String(64))
    scanner_version: Mapped[str] = mapped_column(String(64))
    signature_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    finding_code: Mapped[str | None] = mapped_column(String(128))
    finding_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DownloadLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "download_links"
    __table_args__ = (
        enum_check("status", LINK_STATES, name="status"),
        CheckConstraint("octet_length(token_hash) >= 32", name="token_hash_minimum"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        CheckConstraint("max_downloads IS NULL OR max_downloads > 0", name="positive_max_downloads"),
        CheckConstraint("download_count >= 0", name="nonnegative_download_count"),
        UniqueConstraint("token_hash", "key_version", name="uq_download_links_token_key"),
        Index("ix_download_links_file_status", "file_id", "status"),
        Index("ix_download_links_expiry", "status", "expires_at"),
        Index("ix_download_links_owner_status", "owner_user_id", "status"),
    )

    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    file_reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("file_references.id", ondelete="CASCADE")
    )
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    key_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    purpose: Mapped[str] = mapped_column(String(24), default="private", server_default="private")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_downloads: Mapped[int | None] = mapped_column(Integer)
    download_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    one_time: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    password_hash: Mapped[bytes | None] = mapped_column(LargeBinary(128))
    bound_ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(128))


class DownloadSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "download_sessions"
    __table_args__ = (
        enum_check("status", SESSION_STATES, name="status"),
        CheckConstraint("octet_length(session_id_hash) >= 32", name="session_hash_minimum"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        CheckConstraint("bytes_served >= 0", name="nonnegative_bytes_served"),
        CheckConstraint("range_requests >= 0", name="nonnegative_range_requests"),
        CheckConstraint("resume_count >= 0", name="nonnegative_resume_count"),
        CheckConstraint("active_connections >= 0", name="nonnegative_active_connections"),
        CheckConstraint("unique_ip_count >= 0", name="nonnegative_unique_ip_count"),
        UniqueConstraint("session_id_hash", name="uq_download_sessions_hash"),
        Index("ix_download_sessions_link_status", "download_link_id", "status"),
        Index("ix_download_sessions_owner_status", "owner_user_id", "status"),
        Index("ix_download_sessions_expiry", "status", "expires_at"),
    )

    download_link_id: Mapped[UUID] = mapped_column(ForeignKey("download_links.id", ondelete="CASCADE"))
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    source_ip_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    user_agent_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bytes_served: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    range_requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    resume_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active_connections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unique_ip_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    risk_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(128))


class StreamToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stream_tokens"
    __table_args__ = (
        enum_check("purpose", TOKEN_PURPOSES, name="purpose"),
        CheckConstraint("purpose IN ('stream', 'hls_segment')", name="stream_purpose_only"),
        CheckConstraint("octet_length(token_hash) >= 32", name="token_hash_minimum"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        CheckConstraint("maximum_connections > 0", name="positive_maximum_connections"),
        CheckConstraint("maximum_ips > 0", name="positive_maximum_ips"),
        UniqueConstraint("token_hash", "key_version", name="uq_stream_tokens_token_key"),
        Index("ix_stream_tokens_file_expiry", "file_id", "expires_at"),
        Index("ix_stream_tokens_session", "stream_session_id"),
    )

    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    stream_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stream_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    nonce_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    key_version: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(16), default="stream", server_default="stream")
    allowed_quality: Mapped[str] = mapped_column(String(32))
    maximum_connections: Mapped[int] = mapped_column(Integer)
    maximum_ips: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StreamSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stream_sessions"
    __table_args__ = (
        enum_check("status", SESSION_STATES, name="status"),
        CheckConstraint("octet_length(session_id_hash) >= 32", name="session_hash_minimum"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        CheckConstraint("bytes_served >= 0", name="nonnegative_bytes_served"),
        CheckConstraint("active_connections >= 0", name="nonnegative_active_connections"),
        CheckConstraint("unique_ip_count >= 0", name="nonnegative_unique_ip_count"),
        UniqueConstraint("session_id_hash", name="uq_stream_sessions_hash"),
        Index("ix_stream_sessions_file_status", "file_id", "status"),
        Index("ix_stream_sessions_user_status", "user_id", "status"),
        Index("ix_stream_sessions_expiry", "status", "expires_at"),
    )

    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    source_ip_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    user_agent_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    allowed_quality: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bytes_served: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    active_connections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unique_ip_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    risk_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(128))


class MediaVariant(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "media_variants"
    __table_args__ = (
        enum_check("kind", MEDIA_KINDS, name="kind"),
        enum_check("status", MEDIA_VARIANT_STATES, name="status"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("expires_at > created_at", name="future_expiry"),
        UniqueConstraint("file_id", "kind", "quality", name="uq_media_variants_file_kind_quality"),
        Index("ix_media_variants_expiry", "status", "expires_at"),
    )

    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    quality: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(96))


class MediaSegment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "media_segments"
    __table_args__ = (
        CheckConstraint("sequence_number >= 0", name="nonnegative_sequence"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("duration_ms > 0", name="positive_duration"),
        UniqueConstraint("variant_id", "sequence_number", name="uq_media_segments_sequence"),
        Index("ix_media_segments_expiry", "expires_at"),
    )

    variant_id: Mapped[UUID] = mapped_column(ForeignKey("media_variants.id", ondelete="CASCADE"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_ms: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BandwidthUsage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "bandwidth_usage"
    __table_args__ = (
        CheckConstraint("bytes_sent >= 0", name="nonnegative_bytes_sent"),
        UniqueConstraint("log_source", "log_event_id", name="uq_bandwidth_usage_log_event"),
        Index("ix_bandwidth_usage_user_created", "user_id", "created_at"),
        Index("ix_bandwidth_usage_file_created", "file_id", "created_at"),
        Index("ix_bandwidth_usage_session_created", "session_type", "session_id", "created_at"),
        Index("ix_bandwidth_usage_ip_created", "source_ip_hash", "created_at"),
    )

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    token_id: Mapped[UUID | None]
    session_type: Mapped[str] = mapped_column(String(16))
    session_id: Mapped[UUID | None]
    purpose: Mapped[str] = mapped_column(String(24))
    source_ip_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    bytes_sent: Mapped[int] = mapped_column(BigInteger)
    http_status: Mapped[int] = mapped_column(Integer)
    range_start: Mapped[int | None] = mapped_column(BigInteger)
    range_end: Mapped[int | None] = mapped_column(BigInteger)
    log_source: Mapped[str] = mapped_column(String(64))
    log_event_id: Mapped[str] = mapped_column(String(160))


class StorageStatistic(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "storage_statistics"
    __table_args__ = (
        CheckConstraint("total_bytes >= 0", name="nonnegative_total"),
        CheckConstraint("used_bytes >= 0", name="nonnegative_used"),
        CheckConstraint("free_bytes >= 0", name="nonnegative_free"),
        CheckConstraint("used_bytes + free_bytes <= total_bytes", name="valid_capacity"),
        Index("ix_storage_statistics_scope_created", "scope", "created_at"),
    )

    scope: Mapped[str] = mapped_column(String(64))
    total_bytes: Mapped[int] = mapped_column(BigInteger)
    used_bytes: Mapped[int] = mapped_column(BigInteger)
    free_bytes: Mapped[int] = mapped_column(BigInteger)
    incoming_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    media_cache_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    file_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    pressure_state: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")

