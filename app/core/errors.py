"""Stable internal errors whose codes may be mapped to localized messages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ApplicationError(Exception):
    """Base error with a non-sensitive code and structured context."""

    code = "application_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        self.context = dict(context or {})


class ConfigurationError(ApplicationError):
    code = "configuration_error"


class SecretFileError(ConfigurationError):
    code = "secret_file_error"


class DependencyUnavailable(ApplicationError):
    code = "dependency_unavailable"


class SettingsValidationError(ApplicationError):
    code = "settings_validation_error"


class SettingsConflict(ApplicationError):
    code = "settings_version_conflict"


class PermissionDenied(ApplicationError):
    code = "permission_denied"


class QuotaExceeded(ApplicationError):
    code = "quota_exceeded"


class AdmissionDenied(ApplicationError):
    code = "admission_denied"


class UnsafeUrl(ApplicationError):
    code = "unsafe_url"


class LocalizationError(ApplicationError):
    code = "localization_error"


class StageBoundaryError(ApplicationError):
    code = "service_not_available_in_current_stage"
