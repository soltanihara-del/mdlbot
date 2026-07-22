from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.schemas.workers import CompleteRequest
from app.core.config import RuntimeSettings
from app.workers.auth import WorkerAuthenticator


def _settings(tmp_path: Path, *, duplicate: bool = False) -> RuntimeSettings:
    values = {
        "external": "e" * 40,
        "telegram_download": "d" * 40,
        "telegram_upload": ("d" if duplicate else "u") * 40,
        "media": "m" * 40,
    }
    paths = {}
    for name, value in values.items():
        path = tmp_path / name
        path.write_text(value + "\n", encoding="ascii")
        paths[name] = path
    return RuntimeSettings(
        app_env="test",
        external_worker_token_file=paths["external"],
        telegram_download_worker_token_file=paths["telegram_download"],
        telegram_upload_worker_token_file=paths["telegram_upload"],
        media_worker_token_file=paths["media"],
    )


def test_worker_credentials_are_strictly_scoped(tmp_path: Path) -> None:
    auth = WorkerAuthenticator(_settings(tmp_path))
    auth.start()
    assert auth.authenticate("external_download", f"Bearer {'e' * 40}") == "external_download"
    with pytest.raises(PermissionError):
        auth.authenticate("telegram_download", f"Bearer {'e' * 40}")
    assert auth.authenticate("media_process", f"Bearer {'m' * 40}") == "media_process"


def test_duplicate_worker_credentials_are_rejected(tmp_path: Path) -> None:
    auth = WorkerAuthenticator(_settings(tmp_path, duplicate=True))
    with pytest.raises(ValueError, match="must be distinct"):
        auth.start()
    assert auth.started is False


def test_completion_schema_rejects_storage_escape() -> None:
    with pytest.raises(ValidationError):
        CompleteRequest.model_validate(
            {
                "job_id": "019ac0f2-34b3-7ccf-9fa9-9b9aa918bfba",
                "generation": 1,
                "lease": "x" * 32,
                "stream": "mdlbot:stream:jobs:external_download:normal",
                "group": "workers:external_download",
                "message_id": "1-0",
                "result": {
                    "kind": "download",
                    "storage_key": "aa/../etc",
                    "filename": "file.bin",
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                    "detected_mime": "application/octet-stream",
                    "scan_status": "clean",
                },
            }
        )


def test_upload_result_requires_telegram_discriminator_fields() -> None:
    with pytest.raises(ValidationError):
        CompleteRequest.model_validate(
            {
                "job_id": "019ac0f2-34b3-7ccf-9fa9-9b9aa918bfba",
                "generation": 1,
                "lease": "x" * 32,
                "stream": "mdlbot:stream:jobs:telegram_upload:normal",
                "group": "workers:telegram_upload",
                "message_id": "1-0",
                "result": {"kind": "telegram_upload", "size_bytes": 1},
            }
        )


def test_media_result_rejects_segment_path_escape() -> None:
    with pytest.raises(ValidationError):
        CompleteRequest.model_validate(
            {
                "job_id": "019ac0f2-34b3-7ccf-9fa9-9b9aa918bfba",
                "generation": 1,
                "lease": "x" * 32,
                "stream": "mdlbot:stream:jobs:media_process:normal",
                "group": "workers:media_process",
                "message_id": "1-0",
                "result": {
                    "kind": "media",
                    "size_bytes": 1,
                    "direct_play_compatible": False,
                    "metadata": {},
                    "variants": [
                        {
                            "kind": "hls",
                            "quality": "source",
                            "storage_key": "job/index.m3u8",
                            "mime_type": "application/vnd.apple.mpegurl",
                            "size_bytes": 1,
                            "segments": [
                                {
                                    "sequence_number": 0,
                                    "storage_key": "job/../secret",
                                    "size_bytes": 1,
                                    "duration_ms": 1000,
                                }
                            ],
                        }
                    ],
                },
            }
        )
