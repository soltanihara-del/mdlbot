"""Public Telegram webhook validation and authenticated internal forwarding."""

from __future__ import annotations

import hmac
import re
from typing import Any

from aiohttp import ClientSession, ClientTimeout

from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError, DependencyUnavailable
from app.core.secrets import read_secret_file


class WebhookProxy:
    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._path_secret = ""
        self._telegram_secret = ""
        self._internal_token = ""
        self._session: ClientSession | None = None

    @property
    def started(self) -> bool:
        return self._session is not None

    async def start(self) -> None:
        self._settings.validate_bot_files(token=False, webhook=True)
        self._path_secret = read_secret_file(
            self._settings.telegram_webhook_path_file,  # type: ignore[arg-type]
            minimum_length=48,
        )
        self._telegram_secret = read_secret_file(
            self._settings.telegram_webhook_secret_token_file,  # type: ignore[arg-type]
            minimum_length=32,
        )
        self._internal_token = read_secret_file(
            self._settings.internal_service_token_file,  # type: ignore[arg-type]
            minimum_length=32,
        )
        if re.fullmatch(r"[A-Za-z0-9_-]{48,128}", self._path_secret) is None:
            raise ConfigurationError("webhook path secret has an invalid format")
        if re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self._telegram_secret) is None:
            raise ConfigurationError("Telegram webhook secret has an invalid format")
        self._session = ClientSession(timeout=ClientTimeout(total=12, connect=3))

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None
        self._path_secret = ""
        self._telegram_secret = ""
        self._internal_token = ""

    def validate(self, path_header: str | None, telegram_header: str | None) -> None:
        if not self.started:
            raise ConfigurationError("webhook proxy is not started")
        if path_header is None or not hmac.compare_digest(path_header, self._path_secret):
            raise PermissionError("invalid webhook path")
        if telegram_header is None or not hmac.compare_digest(
            telegram_header,
            self._telegram_secret,
        ):
            raise PermissionError("invalid Telegram webhook secret")

    async def forward(self, payload: dict[str, Any]) -> None:
        if self._session is None:
            raise ConfigurationError("webhook proxy is not started")
        try:
            async with self._session.post(
                f"{self._settings.bot_internal_url}/internal/telegram/webhook",
                json=payload,
                headers={"Authorization": f"Bearer {self._internal_token}"},
            ) as response:
                if response.status < 200 or response.status >= 300:
                    raise DependencyUnavailable(
                        "bot webhook processor rejected the update",
                        context={"status": response.status},
                    )
        except DependencyUnavailable:
            raise
        except Exception as exc:
            raise DependencyUnavailable("bot webhook processor is unavailable") from exc
