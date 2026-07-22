"""Localized keyboard factories with stable callback identifiers."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.callbacks import AdminCallback, FileCallback, LanguageCallback
from app.core.i18n import LocalizationService


USER_MENU_KEYS = (
    "menu-send-telegram-file",
    "menu-send-direct-url",
    "menu-my-files",
    "menu-account-status",
    "menu-support",
    "menu-settings",
    "menu-help",
)

ADMIN_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("settings", "admin-bot-settings", "settings.view"),
    ("admins", "admin-manage-admins", "admins.view"),
    ("users", "admin-manage-users", "users.view"),
    ("broadcast", "admin-broadcast", "broadcast.view"),
    ("public", "admin-public-channel", "public.review"),
    ("security", "admin-security", "security.view"),
    ("backup", "admin-backup", "backup.view"),
    ("restore", "admin-restore", "restore.view"),
)


def language_keyboard(i18n: LocalizationService) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.format("fa", "language-fa"),
                    callback_data=LanguageCallback(code="fa").pack(),
                ),
                InlineKeyboardButton(
                    text=i18n.format("en", "language-en"),
                    callback_data=LanguageCallback(code="en").pack(),
                ),
            ]
        ]
    )


def main_menu(i18n: LocalizationService, locale: str) -> ReplyKeyboardMarkup:
    labels = [i18n.format(locale, key) for key in USER_MENU_KEYS]
    rows = [[KeyboardButton(text=labels[index])] for index in range(len(labels))]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def cancel_keyboard(i18n: LocalizationService, locale: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=i18n.format(locale, "action-cancel"))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def admin_menu(
    i18n: LocalizationService,
    locale: str,
    allowed_permissions: set[str],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for section, label_key, permission in ADMIN_SECTIONS:
        if permission in allowed_permissions:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=i18n.format(locale, label_key),
                        callback_data=AdminCallback(section=section).pack(),
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def forced_join_keyboard(channels: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title[:64], url=url)] for title, url in channels
        ]
    )


def menu_labels(i18n: LocalizationService, key: str) -> set[str]:
    return {i18n.format(locale, key) for locale in ("fa", "en")}


def file_actions_keyboard(
    i18n: LocalizationService,
    locale: str,
    file_id,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.format(locale, "action-download-file"),
                    callback_data=FileCallback(action="download", file_id=file_id).pack(),
                )
            ]
        ]
    )


def download_url_keyboard(
    i18n: LocalizationService,
    locale: str,
    url: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=i18n.format(locale, "action-download-file"), url=url)]
        ]
    )
