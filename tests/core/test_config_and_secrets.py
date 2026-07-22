import os

import pytest
from pydantic import ValidationError

from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError, SecretFileError
from app.core.secrets import read_secret_file


def test_runtime_settings_redact_connection_urls() -> None:
    settings = RuntimeSettings(
        service_name="api",
        database_url="postgresql+psycopg://user:password@db/app",
        redis_url="redis://:password@cache/0",
    )
    summary = settings.safe_summary()
    assert "database_url" not in summary
    assert "redis_url" not in summary
    assert "password" not in repr(summary)


def test_runtime_settings_validate_dependency_and_schemes() -> None:
    with pytest.raises(ConfigurationError):
        RuntimeSettings(service_name="api").validate_dependencies()
    with pytest.raises(ValidationError):
        RuntimeSettings(service_name="api", database_url="postgresql://db/app")


def test_secret_reader_rejects_symlink_and_writable_file(tmp_path) -> None:
    target = tmp_path / "secret"
    target.write_text("long-enough-secret", encoding="utf-8")
    target.chmod(0o600)
    assert read_secret_file(target, minimum_length=8) == "long-enough-secret"
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(SecretFileError):
        read_secret_file(link)
    target.chmod(0o620)
    with pytest.raises(SecretFileError):
        read_secret_file(target)


def test_secret_reader_does_not_accept_nul(tmp_path) -> None:
    target = tmp_path / "secret"
    target.write_bytes(b"abc\x00def")
    os.chmod(target, 0o600)
    with pytest.raises(SecretFileError):
        read_secret_file(target)
