"""Verify that the frozen initial revision matches the ORM schema contract."""

from __future__ import annotations

from importlib import import_module
import re

from app.db.base import Base
import app.db.models  # noqa: F401

migration = import_module("app.db.migrations.versions.0001_initial_schema")


def _created_names(pattern: str) -> set[str]:
    expression = re.compile(pattern, re.IGNORECASE)
    return {
        match.group(1)
        for statement in migration.UPGRADE_STATEMENTS
        if (match := expression.match(statement.strip()))
    }


def test_migration_creates_exact_metadata_table_set() -> None:
    assert _created_names(r"CREATE TABLE ([a-z0-9_]+)") == set(Base.metadata.tables)


def test_migration_contains_every_metadata_index() -> None:
    expected = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.name
    }
    actual = _created_names(r"CREATE (?:UNIQUE )?INDEX ([a-z0-9_]+)")
    assert expected == actual


def test_migration_contains_every_named_constraint() -> None:
    ddl = "\n".join(migration.UPGRADE_STATEMENTS)
    expected = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name
    }
    missing = {name for name in expected if f"CONSTRAINT {name} " not in ddl}
    assert not missing


def test_downgrade_drops_every_table() -> None:
    dropped = {
        match.group(1)
        for statement in migration.DOWNGRADE_STATEMENTS
        if (match := re.match(r"DROP TABLE IF EXISTS ([a-z0-9_]+) CASCADE", statement))
    }
    assert dropped == set(Base.metadata.tables)


def test_integrity_functions_and_triggers_are_present() -> None:
    ddl = "\n".join(migration.UPGRADE_STATEMENTS)
    required = {
        "validate_job_state_transition",
        "prevent_immutable_mutation",
        "protect_last_super_admin",
        "protect_system_admin_role",
        "enforce_approval_separation",
        "trg_jobs_validate_state_transition",
        "trg_admins_protect_last_super_admin",
    }
    assert all(name in ddl for name in required)


def test_revision_does_not_delegate_to_metadata_create_or_drop_all() -> None:
    source = open(migration.__file__, encoding="utf-8").read()
    assert "metadata.create_all" not in source
    assert "metadata.drop_all" not in source

