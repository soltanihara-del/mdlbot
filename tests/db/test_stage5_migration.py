from importlib import import_module


migration = import_module("app.db.migrations.versions.0002_user_language_selection")


def test_language_selection_migration_extends_initial_revision() -> None:
    assert migration.revision == "0002_user_language_selection"
    assert migration.down_revision == "0001_initial_schema"
