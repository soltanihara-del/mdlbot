"""Localized Telegram progress-message consumer backed by a Redis Stream."""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any
from uuid import UUID

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from redis.exceptions import ResponseError
from sqlalchemy import select

from app.core.i18n import LocalizationService
from app.core.logging import get_logger
from app.core.redis import RedisManager
from app.db.models.identity import User
from app.db.models.jobs import Job
from app.db.session import Database


KNOWN_STAGES = {
    "downloading",
    "downloaded",
    "receiving",
    "scanning",
    "processing",
    "generating_link",
    "uploading",
    "uploaded",
    "completed",
    "failed",
}


def human_bytes(value: int) -> str:
    amount = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"


class ProgressNotifier:
    def __init__(
        self,
        database: Database,
        redis: RedisManager,
        bot: Bot,
        i18n: LocalizationService,
    ) -> None:
        self._database = database
        self._redis = redis
        self._bot = bot
        self._i18n = i18n
        self._stream = redis.key("stream", "job-progress")
        self._group = "bot-progress"
        self._consumer = f"bot-{socket.gethostname()}"
        self._log = get_logger("bot.progress")

    async def run(self, stop: asyncio.Event) -> None:
        await self._ensure_group()
        while not stop.is_set():
            try:
                messages = await self._redis.client.xreadgroup(
                    self._group,
                    self._consumer,
                    {self._stream: ">"},
                    count=20,
                    block=1000,
                )
                for _stream, entries in messages:
                    for message_id, fields in entries:
                        await self._handle(message_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log.warning("progress_consumer_cycle_failed", error_type=type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    continue

    async def _ensure_group(self) -> None:
        try:
            await self._redis.client.xgroup_create(
                self._stream,
                self._group,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _handle(self, message_id: str, fields: dict[str, Any]) -> None:
        try:
            payload = json.loads(fields["payload"])
            job_id = UUID(payload["job_id"])
            stage = str(payload["stage"])
            percent = max(0, min(100, int(payload["percent"])))
            transferred = max(0, int(payload["bytes"]))
            if stage not in KNOWN_STAGES:
                stage = "processing"
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await self._redis.client.xack(self._stream, self._group, message_id)
            return
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(Job, User.language_code)
                    .join(User, User.id == Job.user_id)
                    .where(Job.id == job_id)
                )
            ).one_or_none()
        if row is None:
            await self._redis.client.xack(self._stream, self._group, message_id)
            return
        job, language = row
        chat_id = job.payload.get("progress_chat_id") or job.payload.get("chat_id")
        message = job.payload.get("progress_message_id")
        if not isinstance(chat_id, int) or not isinstance(message, int):
            await self._redis.client.xack(self._stream, self._group, message_id)
            return
        stage_label = self._i18n.format(language, f"progress-stage-{stage}")
        key = "job-failed" if stage == "failed" else "job-progress"
        text = self._i18n.format(
            language,
            key,
            stage=stage_label,
            percent=percent,
            bytes=human_bytes(transferred),
        )
        try:
            await self._bot.edit_message_text(text, chat_id=chat_id, message_id=message)
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            self._log.info(
                "progress_message_not_editable",
                job_id=str(job_id),
                error_type=type(exc).__name__,
            )
        finally:
            await self._redis.client.xack(self._stream, self._group, message_id)
