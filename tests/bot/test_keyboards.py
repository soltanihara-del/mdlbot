from app.bot.callbacks import (
    AdminCallback,
    ConfirmationCallback,
    LanguageCallback,
    MenuCallback,
    FileCallback,
)
from app.bot.keyboards import ADMIN_SECTIONS, admin_menu, language_keyboard, main_menu
from app.core.i18n import LocalizationService
from uuid import UUID


def service() -> LocalizationService:
    i18n = LocalizationService("locales")
    i18n.load()
    return i18n


def test_callback_payloads_fit_telegram_limit() -> None:
    payloads = [
        LanguageCallback(code="fa").pack(),
        MenuCallback(section="account").pack(),
        AdminCallback(section="settings").pack(),
        ConfirmationCallback(token="A" * 43).pack(),
        FileCallback(
            action="download",
            file_id=UUID("019ac0f2-34b3-7ccf-9fa9-9b9aa918bfba"),
        ).pack(),
    ]
    assert all(len(payload.encode("utf-8")) <= 64 for payload in payloads)


def test_language_and_user_keyboards_are_localized() -> None:
    i18n = service()
    language = language_keyboard(i18n)
    assert language.inline_keyboard[0][0].callback_data == "lang:fa"
    assert language.inline_keyboard[0][1].callback_data == "lang:en"
    persian = main_menu(i18n, "fa")
    english = main_menu(i18n, "en")
    assert persian.keyboard[0][0].text == "ارسال فایل تلگرام"
    assert english.keyboard[0][0].text == "Send Telegram File"


def test_admin_keyboard_hides_unauthorized_sections() -> None:
    i18n = service()
    keyboard = admin_menu(i18n, "en", {"settings.view", "users.view"})
    callbacks = {row[0].callback_data for row in keyboard.inline_keyboard}
    assert callbacks == {"adm:settings", "adm:users"}
    assert len(callbacks) < len(ADMIN_SECTIONS)
