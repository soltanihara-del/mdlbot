"""Static integrity checks for SQLAlchemy metadata."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKeyConstraint, Index

from app.db.base import Base
import app.db.models  # noqa: F401

EXPECTED_TABLES = {
    "abuse_actions",
    "admin_approvals",
    "admin_audit_logs",
    "admin_confirmations",
    "admin_permission_overrides",
    "admin_roles",
    "admin_scopes",
    "admin_sessions",
    "admins",
    "advertisements",
    "application_instances",
    "backup_destinations",
    "backups",
    "bandwidth_usage",
    "bans",
    "broadcast_results",
    "broadcasts",
    "domain_blocklist",
    "download_links",
    "download_sessions",
    "file_hash_blocklist",
    "file_references",
    "file_reports",
    "file_scan_results",
    "files",
    "forced_join_channels",
    "job_attempts",
    "job_events",
    "jobs",
    "media_segments",
    "media_variants",
    "outbox_events",
    "permissions",
    "privacy_versions",
    "public_categories",
    "public_channel_posts",
    "public_share_requests",
    "quota_buckets",
    "quota_reservations",
    "restore_history",
    "role_permissions",
    "security_events",
    "settings",
    "settings_history",
    "settings_profiles",
    "storage_statistics",
    "stream_sessions",
    "stream_tokens",
    "subscription_plans",
    "support_messages",
    "support_tickets",
    "telegram_api_capabilities",
    "terms_versions",
    "translation_overrides",
    "usage_records",
    "user_appeals",
    "user_consents",
    "user_quota_overrides",
    "user_restrictions",
    "user_strikes",
    "user_subscriptions",
    "users",
    "webhook_updates",
    "worker_leases",
}


def test_exact_stage_2_table_inventory() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_table_has_named_primary_key() -> None:
    for table in Base.metadata.tables.values():
        assert table.primary_key.columns, table.name
        assert table.primary_key.name == f"pk_{table.name}"


def test_every_foreign_key_resolves_to_known_table() -> None:
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                for element in constraint.elements:
                    assert element.column.table.name in EXPECTED_TABLES


def test_index_and_constraint_names_are_globally_unique() -> None:
    names: list[str] = []
    for table in Base.metadata.tables.values():
        names.extend(index.name for index in table.indexes if index.name)
        names.extend(constraint.name for constraint in table.constraints if constraint.name)
    duplicates = {name for name in names if names.count(name) > 1}
    assert not duplicates


def test_no_raw_secret_or_capability_token_columns() -> None:
    forbidden = {"token", "raw_token", "session_token", "download_token", "stream_token"}
    for table in Base.metadata.tables.values():
        assert forbidden.isdisjoint(table.columns.keys()), table.name


def test_byte_counters_use_bigint() -> None:
    exempt_binary = {
        "sha256",
        "checksum_sha256",
        "bytes_hash",
    }
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if "bytes" in column.name and column.name not in exempt_binary:
                assert isinstance(column.type, BigInteger), f"{table.name}.{column.name}"


def test_critical_partial_unique_indexes_exist() -> None:
    expected = {
        "uq_user_subscriptions_one_active",
        "uq_quota_reservations_active_job_bucket",
        "uq_user_appeals_one_pending_per_restriction",
        "uq_public_channel_posts_active_request_channel",
    }
    actual = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if isinstance(index, Index) and index.unique and index.dialect_options["postgresql"].get("where") is not None
    }
    assert expected <= actual

