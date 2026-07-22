"""Structured logging with recursive credential redaction."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import logging
import re
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars


REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_hash",
    "signing_key",
    "encryption_key",
    "database_url",
    "redis_url",
)
TELEGRAM_TOKEN_RE = re.compile(r"\b[0-9]{6,}:[A-Za-z0-9_-]{20,}\b")
URL_CREDENTIAL_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_value(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        value = TELEGRAM_TOKEN_RE.sub(REDACTED, value)
        return URL_CREDENTIAL_RE.sub(lambda match: f"{match.group('scheme')}{REDACTED}@", value)
    return value


def redact_event(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    return {key: redact_value(value, key=key) for key, value in event_dict.items()}


def configure_logging(*, level: str = "INFO", output_format: str = "json") -> None:
    """Configure structlog and the standard-library root logger once per process."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(stream=sys.stdout, level=numeric_level, format="%(message)s", force=True)
    renderer: structlog.types.Processor
    if output_format == "console":
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer(sort_keys=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_event,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def bind_log_context(**values: str | int | None) -> None:
    bind_contextvars(**{key: value for key, value in values.items() if value is not None})


def clear_log_context() -> None:
    clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
