"""Destructive integration test for an explicitly disposable PostgreSQL database."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.db.test_metadata import EXPECTED_TABLES


def _disposable_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if os.environ.get("MDLBOT_ALLOW_DESTRUCTIVE_SCHEMA_TESTS") != "1":
        pytest.skip("MDLBOT_ALLOW_DESTRUCTIVE_SCHEMA_TESTS=1 is required")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        pytest.fail("Stage 2 integration tests require PostgreSQL")
    if not parsed.database or not parsed.database.startswith("mdlbot_test"):
        pytest.fail("refusing destructive migration test: database name must start with mdlbot_test")
    return url


@pytest.mark.postgres
def test_upgrade_constraints_and_downgrade_on_disposable_database() -> None:
    url = _disposable_database_url()
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    engine = create_engine(url)

    with engine.connect() as connection:
        preexisting = set(inspect(connection).get_table_names())
    if preexisting:
        pytest.fail(f"refusing to touch non-empty test database: {sorted(preexisting)}")

    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
            assert tables == EXPECTED_TABLES

            user_id = uuid4()
            job_id = uuid4()
            connection.execute(
                text("INSERT INTO users (id, telegram_user_id) VALUES (:id, :telegram_id)"),
                {"id": user_id, "telegram_id": 9000000001},
            )
            connection.execute(
                text(
                    "INSERT INTO jobs (id, user_id, source, job_type, idempotency_key) "
                    "VALUES (:id, :user_id, 'external_url', 'external_download', :key)"
                ),
                {"id": job_id, "user_id": user_id, "key": f"test:{job_id}"},
            )
            connection.commit()

            with pytest.raises((IntegrityError, DBAPIError)):
                with connection.begin():
                    connection.execute(
                        text("UPDATE jobs SET status = 'completed' WHERE id = :id"), {"id": job_id}
                    )

            with pytest.raises((IntegrityError, DBAPIError)):
                with connection.begin():
                    connection.execute(
                        text(
                            "INSERT INTO quota_buckets "
                            "(id, user_id, dimension, window_kind, window_start, window_end, "
                            "quota_limit, committed_amount, reserved_amount) VALUES "
                            "(:id, :user_id, 'ingress_bytes', 'daily', now(), now() + interval '1 day', 100, 80, 30)"
                        ),
                        {"id": uuid4(), "user_id": user_id},
                    )

            audit_id = uuid4()
            with connection.begin():
                connection.execute(
                    text(
                        "INSERT INTO admin_audit_logs (id, action, target_type, success) "
                        "VALUES (:id, 'schema_test', 'test', true)"
                    ),
                    {"id": audit_id},
                )
            with pytest.raises(DBAPIError):
                with connection.begin():
                    connection.execute(
                        text("UPDATE admin_audit_logs SET action = 'tampered' WHERE id = :id"),
                        {"id": audit_id},
                    )
    finally:
        command.downgrade(config, "base")
        engine.dispose()

