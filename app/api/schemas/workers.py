"""Strict worker control-plane request schemas."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


JobType = Literal["external_download", "telegram_download", "telegram_upload", "media_process"]


class ClaimRequest(BaseModel):
    job_type: JobType
    worker_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,127}$")


class LeaseRequest(BaseModel):
    job_id: UUID
    generation: int = Field(ge=1)
    lease: str = Field(min_length=32, max_length=128)


class HeartbeatRequest(LeaseRequest):
    progress: dict[str, Any] | None = None

    @field_validator("progress")
    @classmethod
    def validate_progress(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if len(value) > 8:
            raise ValueError("progress payload contains too many fields")
        if int(value.get("bytes", 0)) < 0:
            raise ValueError("progress bytes cannot be negative")
        if not 0 <= int(value.get("percent", 0)) <= 100:
            raise ValueError("progress percent is outside range")
        return value


class DownloadCompletionResult(BaseModel):
    kind: Literal["download"]
    storage_key: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{1,510}$")
    filename: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0, le=100 * 1024**3)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detected_mime: str = Field(min_length=1, max_length=255)
    scan_status: Literal["clean", "skipped", "infected", "suspicious", "failed"]

    @field_validator("storage_key")
    @classmethod
    def prevent_path_escape(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("storage key escapes its managed root")
        return value

    @field_validator("filename", "detected_mime")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("value contains control characters")
        return value


class TelegramUploadCompletionResult(BaseModel):
    kind: Literal["telegram_upload"]
    telegram_message_id: int = Field(ge=1)
    telegram_file_id: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=0, le=100 * 1024**3)

    @field_validator("telegram_file_id")
    @classmethod
    def validate_file_id(cls, value: str) -> str:
        if any(ord(character) < 33 or ord(character) == 127 for character in value):
            raise ValueError("Telegram file identifier contains invalid characters")
        return value


class MediaSegmentResult(BaseModel):
    sequence_number: int = Field(ge=0, le=100_000)
    storage_key: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9/_.-]{1,510}$")
    size_bytes: int = Field(ge=0, le=10 * 1024**3)
    duration_ms: int = Field(gt=0, le=120_000)

    @field_validator("storage_key")
    @classmethod
    def prevent_segment_escape(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("segment key escapes its managed root")
        return value


class MediaVariantResult(BaseModel):
    kind: Literal["remux", "transcode", "hls"]
    quality: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,31}$")
    storage_key: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9/_.-]{1,510}$")
    mime_type: str = Field(min_length=3, max_length=255)
    size_bytes: int = Field(ge=0, le=100 * 1024**3)
    metadata: dict[str, Any] = Field(default_factory=dict)
    segments: list[MediaSegmentResult] = Field(default_factory=list, max_length=100_000)

    @field_validator("storage_key")
    @classmethod
    def prevent_variant_escape(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("variant key escapes its managed root")
        return value


class MediaCompletionResult(BaseModel):
    kind: Literal["media"]
    size_bytes: int = Field(ge=0, le=100 * 1024**3)
    direct_play_compatible: bool
    metadata: dict[str, Any]
    variants: list[MediaVariantResult] = Field(default_factory=list, max_length=8)


CompletionResult = Annotated[
    DownloadCompletionResult | TelegramUploadCompletionResult | MediaCompletionResult,
    Field(discriminator="kind"),
]


class CompleteRequest(LeaseRequest):
    stream: str = Field(min_length=8, max_length=192)
    group: str = Field(min_length=8, max_length=128)
    message_id: str = Field(pattern=r"^[0-9]+-[0-9]+$")
    result: CompletionResult


class FailRequest(LeaseRequest):
    stream: str = Field(min_length=8, max_length=192)
    group: str = Field(min_length=8, max_length=128)
    message_id: str = Field(pattern=r"^[0-9]+-[0-9]+$")
    error_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    actual_bytes: int = Field(default=0, ge=0, le=100 * 1024**3)
