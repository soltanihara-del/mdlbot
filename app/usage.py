"""Idempotent ingestion of structured Nginx delivery logs into PostgreSQL."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import RuntimeSettings
from app.core.logging import get_logger
from app.core.redis import RedisManager
from app.core.secrets import read_secret_file
from app.db.models.files import BandwidthUsage, DownloadSession, File, StreamSession
from app.db.models.identity import UsageRecord
from app.db.session import Database


REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


@dataclass(frozen=True, slots=True)
class UsageEvent:
    request_id: str
    remote_addr: str
    response_bytes: int
    status: int
    session_id: UUID
    link_id: UUID
    file_id: UUID
    user_id: UUID
    range_start: int | None
    range_end: int | None
    purpose: str


def parse_usage_event(value: str) -> UsageEvent | None:
    if len(value) > 64 * 1024:
        return None
    try:
        item = json.loads(value)
        request_id = str(item["request_id"])
        if REQUEST_ID_RE.fullmatch(request_id) is None:
            return None
        response_bytes = int(item["response_bytes"])
        status = int(item["status"])
        if response_bytes < 0 or status < 100 or status > 599:
            return None
        session_id = UUID(str(item["session_id"]))
        link_id = UUID(str(item["link_id"]))
        file_id = UUID(str(item["file_id"]))
        user_id = UUID(str(item["user_id"]))
        remote_addr = str(item["remote_addr"])
        purpose = str(item["purpose"])
        if purpose not in {"download", "stream"}:
            return None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    start = end = None
    range_value = str(item.get("range", ""))
    match = RANGE_RE.fullmatch(range_value)
    if match is not None:
        start = int(match.group(1)) if match.group(1) else None
        end = int(match.group(2)) if match.group(2) else None
    return UsageEvent(
        request_id=request_id,
        remote_addr=remote_addr,
        response_bytes=response_bytes,
        status=status,
        session_id=session_id,
        link_id=link_id,
        file_id=file_id,
        user_id=user_id,
        range_start=start,
        range_end=end,
        purpose=purpose,
    )


def read_complete_lines(path: Path, offset: int, *, limit: int = 1000) -> tuple[list[str], int]:
    lines: list[str] = []
    with path.open("rb") as handle:
        handle.seek(offset)
        while len(lines) < limit:
            start = handle.tell()
            raw = handle.readline(64 * 1024 + 1)
            if not raw:
                break
            if len(raw) > 64 * 1024 or not raw.endswith(b"\n"):
                handle.seek(start)
                break
            try:
                lines.append(raw.decode("utf-8"))
            except UnicodeDecodeError:
                lines.append("")
        return lines, handle.tell()


class UsageCollector:
    def __init__(
        self,
        settings: RuntimeSettings,
        database: Database,
        redis: RedisManager,
    ) -> None:
        if settings.download_signing_key_file is None:
            raise ValueError("DOWNLOAD_SIGNING_KEY_FILE is required")
        raw_key = read_secret_file(settings.download_signing_key_file, minimum_length=64)
        try:
            self._key = bytes.fromhex(raw_key)
        except ValueError as exc:
            raise ValueError("download signing key must be hexadecimal") from exc
        if len(self._key) != 32:
            raise ValueError("download signing key must contain exactly 32 bytes")
        if settings.stream_signing_key_file is None:
            raise ValueError("STREAM_SIGNING_KEY_FILE is required")
        stream_raw = read_secret_file(settings.stream_signing_key_file, minimum_length=64)
        try:
            self._stream_key = bytes.fromhex(stream_raw)
        except ValueError as exc:
            raise ValueError("stream signing key must be hexadecimal") from exc
        if len(self._stream_key) != 32:
            raise ValueError("stream signing key must contain exactly 32 bytes")
        if hmac.compare_digest(self._key, self._stream_key):
            raise ValueError("download and stream signing keys must be distinct")
        self._settings = settings
        self._database = database
        self._redis = redis
        self._log = get_logger("usage.collector")

    async def run(self, stop: asyncio.Event, heartbeat: Path) -> None:
        while not stop.is_set():
            heartbeat.write_text("ready\n", encoding="ascii")
            processed = 0
            for path in sorted(self._settings.usage_logs_path.glob("access-*.json")):
                try:
                    processed += await self._consume_file(path)
                except Exception as exc:
                    self._log.warning(
                        "usage_log_cycle_failed",
                        source=path.name,
                        error_type=type(exc).__name__,
                    )
            if processed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    continue

    async def _consume_file(self, path: Path) -> int:
        stat = path.stat()
        cursor_key = self._redis.key("usage", "cursor", path.name, str(stat.st_ino))
        raw_offset = await self._redis.client.get(cursor_key)
        offset = int(raw_offset or 0)
        if offset > stat.st_size:
            offset = 0
        lines, new_offset = await asyncio.to_thread(read_complete_lines, path, offset)
        events = [event for line in lines if (event := parse_usage_event(line)) is not None]
        released: list[tuple[str, UUID]] = []
        if events:
            async with self._database.transaction() as session:
                for event in events:
                    inserted = await session.scalar(
                        insert(BandwidthUsage)
                        .values(
                            user_id=event.user_id,
                            file_id=event.file_id,
                            token_id=event.link_id,
                            session_type=event.purpose,
                            session_id=event.session_id,
                            purpose=event.purpose,
                            source_ip_hash=hmac.new(
                                self._key if event.purpose == "download" else self._stream_key,
                                b"ip:" + event.remote_addr.encode("utf-8"),
                                hashlib.sha256,
                            ).digest(),
                            bytes_sent=event.response_bytes,
                            http_status=event.status,
                            range_start=event.range_start,
                            range_end=event.range_end,
                            log_source=path.name,
                            log_event_id=event.request_id,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[BandwidthUsage.log_source, BandwidthUsage.log_event_id]
                        )
                        .returning(BandwidthUsage.id)
                    )
                    if inserted is None:
                        continue
                    session_model = DownloadSession if event.purpose == "download" else StreamSession
                    tracked_session = await session.scalar(
                        select(session_model)
                        .where(session_model.id == event.session_id)
                        .with_for_update()
                    )
                    if tracked_session is not None:
                        tracked_session.bytes_served += event.response_bytes
                        tracked_session.active_connections = max(
                            0,
                            tracked_session.active_connections - 1,
                        )
                        if (
                            event.purpose == "download"
                            and event.range_start is None
                            and event.range_end is None
                        ):
                            file_size = await session.scalar(
                                select(File.size_bytes).where(File.id == event.file_id)
                            )
                            if (
                                file_size is not None
                                and event.status == 200
                                and event.response_bytes >= file_size
                            ):
                                tracked_session.status = "completed"
                    if event.response_bytes > 0:
                        session.add(
                            UsageRecord(
                                user_id=event.user_id,
                                file_id=event.file_id,
                                session_id=event.session_id,
                                dimension="egress_bytes",
                                direction="debit",
                                amount=event.response_bytes,
                                idempotency_key=f"nginx:{path.name}:{event.request_id}",
                                metadata_json={"http_status": event.status},
                            )
                        )
                    released.append((event.purpose, event.session_id))
                await session.flush()
        for purpose, session_id in released:
            key = self._redis.key(purpose, "connections", str(session_id))
            await self._redis.client.eval(
                """
                local current = tonumber(redis.call('GET', KEYS[1]) or '0')
                if current <= 1 then redis.call('DEL', KEYS[1]); return 0 end
                return redis.call('DECR', KEYS[1])
                """,
                1,
                key,
            )
        await self._redis.client.set(cursor_key, new_offset, ex=8 * 86400)
        return len(lines)
