from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError
from app.services.downloads import DownloadService, TOKEN_RE, content_disposition


class RedisStub:
    client = None


def write_key(path: Path, value: str) -> Path:
    path.write_text(value, encoding="ascii")
    path.chmod(0o600)
    return path


def test_download_service_requires_exact_hex_key(tmp_path: Path) -> None:
    invalid = RuntimeSettings(
        app_env="test",
        download_signing_key_file=write_key(tmp_path / "bad", "x" * 64),
    )
    with pytest.raises(ConfigurationError, match="hexadecimal"):
        DownloadService(invalid, RedisStub())  # type: ignore[arg-type]

    short = RuntimeSettings(
        app_env="test",
        download_signing_key_file=write_key(tmp_path / "short", "ab" * 33),
    )
    with pytest.raises(ConfigurationError, match="exactly 32 bytes"):
        DownloadService(short, RedisStub())  # type: ignore[arg-type]


def test_content_disposition_prevents_header_injection_and_supports_unicode() -> None:
    value = content_disposition('گزارش\r\nX-Evil: yes".pdf')
    assert "\r" not in value and "\n" not in value
    assert "filename*=UTF-8''" in value
    assert "%DA%AF" in value


def test_download_tokens_have_one_canonical_shape() -> None:
    assert TOKEN_RE.fullmatch("A" * 43)
    assert TOKEN_RE.fullmatch("A" * 42) is None
    assert TOKEN_RE.fullmatch("A" * 42 + ".") is None
