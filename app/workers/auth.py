"""Per-pool worker credentials; a token can authorize exactly one job type."""

from __future__ import annotations

import hmac

from app.core.config import RuntimeSettings
from app.core.secrets import read_secret_file


class WorkerAuthenticator:
    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._tokens: dict[str, str] = {}

    @property
    def started(self) -> bool:
        return bool(self._tokens)

    def start(self) -> None:
        self._settings.validate_worker_files(api=True)
        paths = {
            "external_download": self._settings.external_worker_token_file,
            "telegram_download": self._settings.telegram_download_worker_token_file,
            "telegram_upload": self._settings.telegram_upload_worker_token_file,
        }
        self._tokens = {
            job_type: read_secret_file(path, minimum_length=32)  # type: ignore[arg-type]
            for job_type, path in paths.items()
        }
        if len(set(self._tokens.values())) != len(self._tokens):
            self.close()
            raise ValueError("worker pool credentials must be distinct")

    def close(self) -> None:
        self._tokens.clear()

    def authenticate(self, job_type: str | None, authorization: str | None) -> str:
        token = self._tokens.get(job_type or "")
        if token is None or authorization is None or not hmac.compare_digest(
            authorization,
            f"Bearer {token}",
        ):
            raise PermissionError("invalid worker pool credential")
        return str(job_type)
