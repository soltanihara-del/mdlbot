"""Canonical database values shared by models, services, and tests."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import CheckConstraint

LANGUAGES = ("fa", "en")
USER_STATUSES = ("active", "restricted", "banned", "deleted")
SUBSCRIPTION_STATUSES = ("scheduled", "active", "expired", "revoked")
QUOTA_DIMENSIONS = (
    "ingress_bytes",
    "egress_bytes",
    "storage_bytes",
    "file_count",
    "job_count",
    "download_count",
    "stream_count",
)
QUOTA_WINDOWS = ("hourly", "multi_hour", "daily", "weekly", "lifetime")
RESERVATION_STATES = ("active", "committed", "released", "expired")
USAGE_DIRECTIONS = ("debit", "credit")
RESTRICTION_STATES = ("active", "expired", "revoked")
APPEAL_STATES = ("pending", "approved", "reduced", "rejected", "withdrawn")
JOB_STATES = (
    "pending",
    "quota_reserved",
    "queued",
    "dispatched",
    "downloading",
    "receiving",
    "scanning",
    "processing",
    "remuxing",
    "transcoding",
    "uploading",
    "generating_link",
    "completed",
    "failed",
    "cancelled",
    "expired",
    "cancelled_by_migration",
    "dead_letter",
)
JOB_SOURCES = ("telegram", "external_url", "internal")
OUTBOX_STATES = ("pending", "published", "failed")
INSTANCE_STATES = ("starting", "ready", "draining", "stopped", "failed")
FILE_STATES = (
    "incoming",
    "quarantined",
    "available",
    "deleting",
    "deleted",
    "expired",
    "unavailable_after_migration",
)
SCAN_STATES = ("pending", "scanning", "clean", "infected", "suspicious", "failed", "skipped")
LINK_STATES = ("active", "exhausted", "expired", "revoked")
SESSION_STATES = ("active", "completed", "expired", "revoked", "blocked")
MEDIA_VARIANT_STATES = ("pending", "processing", "ready", "failed", "deleting", "deleted")
MEDIA_KINDS = ("direct", "remux", "transcode", "hls", "thumbnail")
PUBLIC_REQUEST_STATES = ("pending", "approved", "rejected", "published", "withdrawn")
REPORT_STATES = ("open", "reviewing", "resolved", "dismissed")
TICKET_STATES = ("open", "answered", "closed", "assigned")
BROADCAST_STATES = ("draft", "queued", "running", "paused", "completed", "cancelled", "failed")
BROADCAST_RESULT_STATES = ("pending", "sent", "failed", "blocked", "deactivated", "skipped")
ADMIN_STATUSES = ("active", "suspended", "expired", "removed")
PERMISSION_EFFECTS = ("allow", "deny")
CONFIRMATION_STATES = ("pending", "consumed", "expired", "cancelled")
APPROVAL_STATES = ("pending", "approved", "rejected", "expired", "executed", "cancelled")
SETTING_VALUE_TYPES = (
    "integer",
    "decimal",
    "boolean",
    "string",
    "enum",
    "duration",
    "bytes",
    "bitrate",
    "percentage",
    "list",
    "controlled_json",
)
RELOAD_TYPES = ("hot_reload", "graceful_reload", "restart_required")
SEVERITIES = ("info", "low", "medium", "high", "critical")
SECURITY_EVENT_STATES = ("open", "investigating", "resolved", "false_positive")
BACKUP_STATES = ("creating", "verifying", "ready", "failed", "deleted")
RESTORE_STATES = ("pending", "running", "completed", "failed", "rolled_back")
TOKEN_PURPOSES = ("download", "stream", "hls_segment")


def enum_check(column: str, values: Sequence[str], *, name: str) -> CheckConstraint:
    """Return a named portable check constraint for a finite string domain."""

    quoted_values = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({quoted_values})", name=name)

