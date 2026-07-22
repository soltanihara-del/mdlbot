"""Durable jobs, attempts, outbox delivery, worker leases, and infrastructure state."""

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

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.constants import (
    INSTANCE_STATES,
    JOB_SOURCES,
    JOB_STATES,
    OUTBOX_STATES,
    enum_check,
)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("source", JOB_SOURCES, name="source"),
        enum_check("status", JOB_STATES, name="status"),
        CheckConstraint("base_priority >= 0", name="nonnegative_base_priority"),
        CheckConstraint("effective_priority >= 0", name="nonnegative_effective_priority"),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        CheckConstraint("max_attempts > 0", name="positive_max_attempts"),
        CheckConstraint("attempt_count <= max_attempts", name="attempt_within_limit"),
        CheckConstraint("dispatch_generation >= 0", name="nonnegative_dispatch_generation"),
        CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="valid_progress"),
        CheckConstraint("bytes_transferred >= 0", name="nonnegative_bytes_transferred"),
        CheckConstraint("total_bytes IS NULL OR total_bytes >= 0", name="nonnegative_total_bytes"),
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        Index(
            "ix_jobs_dispatch_eligible",
            "job_type", "queue_class", "effective_priority", "queued_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_retry", "status", "next_retry_at"),
        Index("ix_jobs_stale_dispatch", "status", "lease_expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(16))
    job_type: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    queue_class: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    base_priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    effective_priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    priority_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    dispatch_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    assigned_instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("application_instances.id", ondelete="SET NULL")
    )
    lease_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_stage: Mapped[str | None] = mapped_column(String(32))
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bytes_transferred: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(String(96))
    last_error_detail: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class JobAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_number"),
        Index("ix_job_attempts_instance", "instance_id", "started_at"),
    )

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    dispatch_generation: Mapped[int] = mapped_column(Integer)
    instance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("application_instances.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    error_code: Mapped[str | None] = mapped_column(String(96))
    error_detail: Mapped[str | None] = mapped_column(Text)


class JobEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_created", "job_id", "created_at"),)

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    attempt_id: Mapped[UUID | None] = mapped_column(ForeignKey("job_attempts.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[UUID | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


class OutboxEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        enum_check("state", OUTBOX_STATES, name="state"),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        UniqueConstraint("deduplication_key", name="uq_outbox_events_deduplication_key"),
        Index(
            "ix_outbox_events_publish",
            "available_at", "created_at",
            postgresql_where=text("state IN ('pending', 'failed')"),
        ),
    )

    aggregate_type: Mapped[str] = mapped_column(String(48))
    aggregate_id: Mapped[UUID]
    event_type: Mapped[str] = mapped_column(String(96))
    stream_name: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    deduplication_key: Mapped[str] = mapped_column(String(192))
    state: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redis_message_id: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)


class ApplicationInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "application_instances"
    __table_args__ = (
        enum_check("status", INSTANCE_STATES, name="status"),
        UniqueConstraint("installation_id", "instance_name", name="uq_application_instances_identity"),
        Index("ix_application_instances_heartbeat", "status", "last_heartbeat_at"),
    )

    installation_id: Mapped[str] = mapped_column(String(64))
    instance_name: Mapped[str] = mapped_column(String(128))
    service_type: Mapped[str] = mapped_column(String(48))
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="starting", server_default="starting")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class WorkerLease(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "worker_leases"
    __table_args__ = (
        CheckConstraint("lease_expires_at > acquired_at", name="valid_lease_period"),
        UniqueConstraint("resource_type", "resource_id", name="uq_worker_leases_resource"),
        Index("ix_worker_leases_expiry", "lease_expires_at"),
    )

    resource_type: Mapped[str] = mapped_column(String(48))
    resource_id: Mapped[UUID]
    instance_id: Mapped[UUID] = mapped_column(
        ForeignKey("application_instances.id", ondelete="CASCADE")
    )
    lease_token_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    generation: Mapped[int] = mapped_column(Integer)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TelegramApiCapability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telegram_api_capabilities"
    __table_args__ = (
        CheckConstraint("upload_limit_bytes > 0", name="positive_upload_limit"),
        UniqueConstraint("installation_id", "endpoint_fingerprint", name="uq_telegram_capabilities_endpoint"),
        Index("ix_telegram_capabilities_active", "is_active", "verified_at"),
    )

    installation_id: Mapped[str] = mapped_column(String(64))
    api_mode: Mapped[str] = mapped_column(String(16))
    endpoint_fingerprint: Mapped[bytes] = mapped_column(LargeBinary(64))
    server_version: Mapped[str | None] = mapped_column(String(64))
    image_digest: Mapped[str | None] = mapped_column(String(128))
    upload_limit_bytes: Mapped[int] = mapped_column(BigInteger)
    unlimited_download: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    absolute_file_paths: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    verification_status: Mapped[str] = mapped_column(String(24))
    verification_source: Mapped[str] = mapped_column(String(255))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class WebhookUpdate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_updates"
    __table_args__ = (
        CheckConstraint("telegram_update_id >= 0", name="nonnegative_update_id"),
        Index("ix_webhook_updates_status_received", "status", "received_at"),
    )

    telegram_update_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    update_type: Mapped[str] = mapped_column(String(48))
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary(64))
    status: Mapped[str] = mapped_column(String(24), default="received", server_default="received")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(96))

