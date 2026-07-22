"""Localized user commands, menus, and Stage 5 FSM entry transitions."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import LanguageCallback
from app.bot.keyboards import cancel_keyboard, language_keyboard, main_menu, menu_labels
from app.bot.repositories import UserRepository
from app.bot.states import DirectUrlStates, LanguageStates, SupportStates, TelegramFileStates
from app.core.i18n import LocalizationService
from app.db.models.identity import User
from app.db.models.product import SupportMessage, SupportTicket
from app.db.models.admin import Setting
from datetime import UTC, datetime
from app.services.admission import AdmissionService
from app.services.url_policy import normalize_external_url


def build_user_router(i18n: LocalizationService, admission: AdmissionService) -> Router:
    router = Router(name="user")
    users = UserRepository()

    async def show_menu(message: Message, user: User) -> None:
        await message.answer(
            i18n.format(user.language_code, "main-menu-prompt"),
            reply_markup=main_menu(i18n, user.language_code),
        )

    @router.message(CommandStart())
    async def start(message: Message, user_record: User, state: FSMContext) -> None:
        await state.clear()
        if user_record.language_selected_at is None:
            await state.set_state(LanguageStates.choosing)
            await message.answer(
                f"{i18n.format('fa', 'language-select')}\n{i18n.format('en', 'language-select')}",
                reply_markup=language_keyboard(i18n),
            )
            return
        await show_menu(message, user_record)

    @router.callback_query(LanguageCallback.filter())
    async def choose_language(
        callback: CallbackQuery,
        callback_data: LanguageCallback,
        user_record: User,
        session: AsyncSession,
        state: FSMContext,
    ) -> None:
        if callback_data.code not in {"fa", "en"}:
            await callback.answer()
            return
        await users.select_language(session, user_record, callback_data.code)
        await state.clear()
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer(
                i18n.format(callback_data.code, "welcome", name=callback.from_user.full_name),
                reply_markup=main_menu(i18n, callback_data.code),
            )

    cancel_labels = menu_labels(i18n, "action-cancel")

    @router.message(Command("cancel"))
    @router.message(F.text.in_(cancel_labels))
    async def cancel(message: Message, user_record: User, state: FSMContext) -> None:
        await state.clear()
        await message.answer(i18n.format(user_record.language_code, "operation-cancelled"))
        await show_menu(message, user_record)

    @router.message(F.text.in_(menu_labels(i18n, "menu-send-telegram-file")))
    async def request_telegram_file(
        message: Message,
        user_record: User,
        state: FSMContext,
    ) -> None:
        await state.set_state(TelegramFileStates.waiting_for_file)
        await message.answer(
            i18n.format(user_record.language_code, "prompt-send-telegram-file"),
            reply_markup=cancel_keyboard(i18n, user_record.language_code),
        )

    @router.message(F.text.in_(menu_labels(i18n, "menu-send-direct-url")))
    async def request_direct_url(
        message: Message,
        user_record: User,
        state: FSMContext,
    ) -> None:
        await state.set_state(DirectUrlStates.waiting_for_url)
        await message.answer(
            i18n.format(user_record.language_code, "prompt-send-direct-url"),
            reply_markup=cancel_keyboard(i18n, user_record.language_code),
        )

    @router.message(
        StateFilter(TelegramFileStates.waiting_for_file),
        F.document | F.video | F.audio | F.animation,
    )
    async def receive_telegram_file(
        message: Message,
        user_record: User,
        state: FSMContext,
        session: AsyncSession,
    ) -> None:
        media = message.document or message.video or message.audio or message.animation
        if media is None:
            return
        unknown_row = await session.scalar(
            select(Setting).where(Setting.key == "queue.unknown_size_reservation")
        )
        fallback_size = int(unknown_row.value) if unknown_row is not None else 64 * 1024**2
        size_known = media.file_size is not None and media.file_size > 0
        estimated_size = media.file_size if size_known else fallback_size
        filename = getattr(media, "file_name", None) or f"telegram-{media.file_unique_id}"
        job, position = await admission.create_job(
            session,
            user=user_record,
            source="telegram",
            job_type="telegram_download",
            payload={
                "telegram_file_id": media.file_id,
                "telegram_file_unique_id": media.file_unique_id,
                "filename": filename,
                "mime_type": getattr(media, "mime_type", None),
                "size_known": size_known,
                "progress_chat_id": message.chat.id,
            },
            estimated_bytes=int(estimated_size),
            idempotency_key=f"telegram:{message.chat.id}:{message.message_id}",
        )
        progress = await message.answer(
            i18n.format(user_record.language_code, "job-queued", position=position)
        )
        job.payload = {**job.payload, "progress_message_id": progress.message_id}
        await session.flush()
        await state.clear()

    @router.message(StateFilter(DirectUrlStates.waiting_for_url), F.text)
    async def receive_direct_url(
        message: Message,
        user_record: User,
        state: FSMContext,
        session: AsyncSession,
    ) -> None:
        normalized = normalize_external_url(message.text or "")
        reserve_row = await session.scalar(
            select(Setting).where(Setting.key == "queue.unknown_size_reservation")
        )
        estimated_size = int(reserve_row.value) if reserve_row is not None else 64 * 1024**2
        job, position = await admission.create_job(
            session,
            user=user_record,
            source="external_url",
            job_type="external_download",
            payload={
                "url": normalized.url,
                "hostname": normalized.hostname,
                "size_known": False,
                "progress_chat_id": message.chat.id,
            },
            estimated_bytes=estimated_size,
            idempotency_key=f"external-url:{message.chat.id}:{message.message_id}",
        )
        progress = await message.answer(
            i18n.format(user_record.language_code, "job-queued", position=position)
        )
        job.payload = {**job.payload, "progress_message_id": progress.message_id}
        await session.flush()
        await state.clear()

    @router.message(F.text.in_(menu_labels(i18n, "menu-my-files")))
    async def my_files(
        message: Message,
        user_record: User,
        session: AsyncSession,
    ) -> None:
        files = await users.recent_files(session, user_record)
        if not files:
            await message.answer(i18n.format(user_record.language_code, "my-files-empty"))
            return
        items = "\n".join(
            i18n.format(
                user_record.language_code,
                "my-files-item",
                filename=item.display_filename,
                expires=item.expires_at.date().isoformat(),
            )
            for item in files
        )
        await message.answer(i18n.format(user_record.language_code, "my-files-list", items=items))

    @router.message(F.text.in_(menu_labels(i18n, "menu-account-status")))
    async def account_status(message: Message, user_record: User) -> None:
        status_label = i18n.format(
            user_record.language_code,
            f"user-status-{user_record.status}",
        )
        language_label = i18n.format(
            user_record.language_code,
            f"language-name-{user_record.language_code}",
        )
        await message.answer(
            i18n.format(
                user_record.language_code,
                "account-summary",
                status=status_label,
                locale=language_label,
            )
        )

    @router.message(F.text.in_(menu_labels(i18n, "menu-settings")))
    async def user_settings(message: Message, user_record: User, state: FSMContext) -> None:
        await state.set_state(LanguageStates.choosing)
        await message.answer(
            i18n.format(user_record.language_code, "settings-language"),
            reply_markup=language_keyboard(i18n),
        )

    @router.message(Command("help"))
    @router.message(F.text.in_(menu_labels(i18n, "menu-help")))
    async def help_message(message: Message, user_record: User) -> None:
        await message.answer(i18n.format(user_record.language_code, "help-message"))

    @router.message(F.text.in_(menu_labels(i18n, "menu-support")))
    async def support_start(message: Message, user_record: User, state: FSMContext) -> None:
        await state.set_state(SupportStates.waiting_for_subject)
        await message.answer(
            i18n.format(user_record.language_code, "support-subject-prompt"),
            reply_markup=cancel_keyboard(i18n, user_record.language_code),
        )

    @router.message(StateFilter(SupportStates.waiting_for_subject), F.text)
    async def support_subject(message: Message, user_record: User, state: FSMContext) -> None:
        subject = (message.text or "").strip()
        if len(subject) < 3 or len(subject) > 512:
            await message.answer(i18n.format(user_record.language_code, "support-subject-invalid"))
            return
        await state.update_data(subject=subject)
        await state.set_state(SupportStates.waiting_for_message)
        await message.answer(i18n.format(user_record.language_code, "support-message-prompt"))

    @router.message(StateFilter(SupportStates.waiting_for_message), F.text)
    async def support_message(
        message: Message,
        user_record: User,
        state: FSMContext,
        session: AsyncSession,
    ) -> None:
        body = (message.text or "").strip()
        if len(body) < 2 or len(body) > 8000:
            await message.answer(i18n.format(user_record.language_code, "support-message-invalid"))
            return
        limit_row = await session.scalar(select(Setting).where(Setting.key == "support.open_ticket_limit"))
        limit = int(limit_row.value) if limit_row is not None else 1
        open_count = int(
            await session.scalar(
                select(func.count()).select_from(SupportTicket).where(
                    SupportTicket.user_id == user_record.id,
                    SupportTicket.status.in_(("open", "answered", "assigned")),
                )
            )
            or 0
        )
        if open_count >= limit:
            await message.answer(i18n.format(user_record.language_code, "support-limit-reached"))
            return
        data = await state.get_data()
        now = datetime.now(UTC)
        ticket = SupportTicket(
            user_id=user_record.id,
            subject=data["subject"],
            user_language=user_record.language_code,
            last_message_at=now,
        )
        session.add(ticket)
        await session.flush()
        session.add(
            SupportMessage(
                ticket_id=ticket.id,
                sender_type="user",
                sender_user_id=user_record.id,
                message_type="text",
                body=body,
            )
        )
        await session.flush()
        await state.clear()
        await message.answer(
            i18n.format(user_record.language_code, "support-ticket-created", ticket=str(ticket.id)),
            reply_markup=main_menu(i18n, user_record.language_code),
        )

    return router
