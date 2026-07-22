"""Compact, typed callback payloads kept below Telegram's 64-byte limit."""

from aiogram.filters.callback_data import CallbackData
from uuid import UUID


class LanguageCallback(CallbackData, prefix="lang"):
    code: str


class MenuCallback(CallbackData, prefix="menu"):
    section: str


class AdminCallback(CallbackData, prefix="adm"):
    section: str


class ConfirmationCallback(CallbackData, prefix="cfm"):
    """Opaque server-side confirmation lookup; never carries action values."""

    token: str


class FileCallback(CallbackData, prefix="file"):
    action: str
    file_id: UUID
