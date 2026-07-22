"""Validated non-secret runtime configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import socket
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigurationError


Environment = Literal["development", "test", "production"]


class RuntimeSettings(BaseSettings):
    """Process settings loaded from environment after entrypoint validation."""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    app_env: Environment = "production"
    service_name: str = "api"
    instance_id: str = Field(default_factory=socket.gethostname)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    database_url: SecretStr | None = None
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    database_statement_timeout_ms: int = Field(default=30_000, ge=1_000, le=300_000)

    redis_url: SecretStr | None = None
    redis_max_connections: int = Field(default=50, ge=2, le=500)
    redis_socket_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    redis_key_prefix: str = "mdlbot"

    bot_token_file: Path | None = None
    telegram_webhook_path_file: Path | None = None
    telegram_webhook_secret_token_file: Path | None = None
    internal_service_token_file: Path | None = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_api_mode: Literal["local", "official"] = "local"
    bot_internal_url: str = "http://bot:8001"
    bot_internal_host: str = "0.0.0.0"
    bot_internal_port: int = Field(default=8001, ge=1024, le=65535)

    locales_path: Path = Path("locales")
    default_locale: Literal["fa", "en"] = "fa"
    public_domain: str | None = None
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1024, le=65535)
    settings_cache_ttl_seconds: int = Field(default=60, ge=5, le=3600)
    settings_generation_poll_seconds: int = Field(default=30, ge=5, le=300)
    graceful_shutdown_seconds: int = Field(default=30, ge=5, le=300)

    @field_validator("service_name", "redis_key_prefix")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", value):
            raise ValueError("must be a lowercase service identifier")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(
            "postgresql+psycopg://"
        ):
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must use redis or rediss")
        return value

    @field_validator("telegram_api_base_url", "bot_internal_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("URL must use http or https")
        return normalized

    @field_validator("public_domain")
    @classmethod
    def validate_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.rstrip(".").lower()
        if len(normalized) > 253 or ".." in normalized or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", normalized
        ):
            raise ValueError("PUBLIC_DOMAIN must be a DNS hostname without a scheme")
        return normalized

    def validate_dependencies(self, *, database: bool = True, redis: bool = True) -> None:
        missing: list[str] = []
        if database and self.database_url is None:
            missing.append("DATABASE_URL")
        if redis and self.redis_url is None:
            missing.append("REDIS_URL")
        if missing:
            raise ConfigurationError(
                "required dependency configuration is missing",
                context={"missing": missing, "service": self.service_name},
            )

    def validate_bot_files(self, *, token: bool = True, webhook: bool = True) -> None:
        required = {"INTERNAL_SERVICE_TOKEN_FILE": self.internal_service_token_file}
        if token:
            required["BOT_TOKEN_FILE"] = self.bot_token_file
        if webhook:
            required.update(
                {
                    "TELEGRAM_WEBHOOK_PATH_FILE": self.telegram_webhook_path_file,
                    "TELEGRAM_WEBHOOK_SECRET_TOKEN_FILE": self.telegram_webhook_secret_token_file,
                }
            )
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ConfigurationError("bot secret-file paths are missing", context={"missing": missing})

    def safe_summary(self) -> dict[str, str | int | float | None]:
        return {
            "app_env": self.app_env,
            "service_name": self.service_name,
            "instance_id": self.instance_id,
            "log_level": self.log_level,
            "database_pool_size": self.database_pool_size,
            "redis_max_connections": self.redis_max_connections,
            "public_domain": self.public_domain,
            "api_port": self.api_port,
            "telegram_api_mode": self.telegram_api_mode,
            "bot_internal_port": self.bot_internal_port,
        }


@lru_cache(maxsize=32)
def load_settings(service_name: str = "api") -> RuntimeSettings:
    return RuntimeSettings(service_name=service_name)
