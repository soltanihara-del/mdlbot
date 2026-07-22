"""Separate stream tokens, player authorization, and Range-capable media grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import re
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError, StreamDenied
from app.core.redis import RedisManager
from app.core.secrets import read_secret_file
from app.db.models.files import (
    File,
    FileReference,
    MediaVariant,
    MediaSegment,
    StreamSession,
    StreamToken,
)
from app.db.models.identity import User
from app.services.quota import QuotaService


STREAM_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True, slots=True)
class PlayerGrant:
    url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StreamGrant:
    session_id: UUID
    token_id: UUID
    file_id: UUID
    user_id: UUID
    internal_path: str
    mime_type: str
    etag: str
    rate_bytes_per_second: int | None


@dataclass(frozen=True, slots=True)
class PlayerView:
    filename: str
    language: str
    media_kind: str
    hls_available: bool


@dataclass(frozen=True, slots=True)
class HlsManifest:
    body: str


class StreamService:
    def __init__(self, settings: RuntimeSettings, redis: RedisManager) -> None:
        self._settings = settings
        self._redis = redis
        self._quota = QuotaService()
        if settings.stream_signing_key_file is None:
            raise ConfigurationError("STREAM_SIGNING_KEY_FILE is required")
        raw = read_secret_file(settings.stream_signing_key_file, minimum_length=64)
        try:
            self._key = bytes.fromhex(raw)
        except ValueError as exc:
            raise ConfigurationError("stream signing key must be hexadecimal") from exc
        if len(self._key) != 32:
            raise ConfigurationError("stream signing key must contain exactly 32 bytes")
        if settings.download_signing_key_file is not None:
            download_raw = read_secret_file(
                settings.download_signing_key_file,
                minimum_length=64,
            )
            try:
                download_key = bytes.fromhex(download_raw)
            except ValueError as exc:
                raise ConfigurationError("download signing key must be hexadecimal") from exc
            if hmac.compare_digest(self._key, download_key):
                raise ConfigurationError("download and stream signing keys must be distinct")

    def _digest(self, namespace: bytes, value: str) -> bytes:
        return hmac.new(self._key, namespace + b":" + value.encode(), hashlib.sha256).digest()

    async def create_token(
        self,
        session: AsyncSession,
        *,
        user: User,
        file_id: UUID,
        media_kind: str,
    ) -> PlayerGrant:
        if media_kind not in {"video", "audio"}:
            raise StreamDenied("unsupported player kind")
        if not self._settings.public_domain:
            raise ConfigurationError("PUBLIC_DOMAIN is required to create player links")
        now = datetime.now(UTC)
        reference = await session.scalar(
            select(FileReference).where(
                FileReference.user_id == user.id,
                FileReference.file_id == file_id,
                FileReference.deleted_at.is_(None),
                FileReference.expires_at > now,
            )
        )
        file = await session.scalar(
            select(File).where(
                File.id == file_id,
                File.status == "available",
                File.deleted_at.is_(None),
                File.expires_at > now,
            )
        )
        if reference is None or file is None:
            raise StreamDenied("file is unavailable")
        if media_kind == "video" and not file.detected_mime.startswith("video/"):
            raise StreamDenied("file is not a video")
        if media_kind == "audio" and not (
            file.detected_mime.startswith("audio/") or file.detected_mime.startswith("video/")
        ):
            raise StreamDenied("file has no playable audio")
        plan = await self._quota.effective_plan(session, user, now=now)
        if not plan.streaming_enabled:
            raise StreamDenied("streaming is disabled for this plan")
        active = int(
            await session.scalar(
                select(func.count()).select_from(StreamSession).where(
                    StreamSession.user_id == user.id,
                    StreamSession.status == "active",
                    StreamSession.expires_at > now,
                )
            )
            or 0
        )
        if active >= plan.concurrent_streams:
            raise StreamDenied("concurrent stream limit reached")
        raw_token = secrets.token_urlsafe(32)
        expires_at = min(file.expires_at, now + timedelta(hours=2))
        token = StreamToken(
            file_id=file.id,
            user_id=user.id,
            token_hash=self._digest(b"stream", raw_token),
            nonce_hash=self._digest(b"nonce", raw_token),
            key_version=1,
            purpose="stream",
            allowed_quality=plan.max_stream_quality,
            maximum_connections=plan.stream_connection_limit,
            maximum_ips=plan.allowed_ips_per_session,
            expires_at=expires_at,
        )
        session.add(token)
        await session.flush()
        route = "watch" if media_kind == "video" else "listen"
        return PlayerGrant(
            url=f"https://{self._settings.public_domain}/{route}/{raw_token}",
            expires_at=expires_at,
        )

    async def player_view(
        self,
        session: AsyncSession,
        *,
        raw_token: str,
        media_kind: str,
    ) -> PlayerView:
        token, file, user = await self._load(session, raw_token)
        if media_kind == "video" and not file.detected_mime.startswith("video/"):
            raise StreamDenied("player type does not match media")
        if media_kind == "audio" and not (
            file.detected_mime.startswith("audio/") or file.detected_mime.startswith("video/")
        ):
            raise StreamDenied("player type does not match media")
        return PlayerView(
            filename=file.safe_display_filename,
            language=user.language_code,
            media_kind=media_kind,
            hls_available=bool(
                await session.scalar(
                    select(MediaVariant.id).where(
                        MediaVariant.file_id == file.id,
                        MediaVariant.kind == "hls",
                        MediaVariant.status == "ready",
                        MediaVariant.deleted_at.is_(None),
                    )
                )
            ),
        )

    async def authorize(
        self,
        session: AsyncSession,
        *,
        raw_token: str,
        source_ip: str,
        user_agent: str,
    ) -> StreamGrant:
        token, file, user = await self._load(session, raw_token, lock=True)
        now = datetime.now(UTC)
        stream_session = await self._ensure_session(
            session,
            token=token,
            file=file,
            user=user,
            source_ip=source_ip,
            user_agent=user_agent,
        )

        variant = await session.scalar(
            select(MediaVariant)
            .where(
                MediaVariant.file_id == file.id,
                MediaVariant.status == "ready",
                MediaVariant.kind.in_(("remux", "transcode")),
                MediaVariant.deleted_at.is_(None),
            )
            .order_by(MediaVariant.kind.asc())
        )
        if file.direct_play_compatible:
            internal_path = f"/__protected/files/{file.storage_key}"
            mime_type = file.detected_mime
            etag_value = file.sha256.hex() if file.sha256 else str(file.id)
        elif variant is not None:
            internal_path = f"/__protected/media/{variant.storage_key}"
            mime_type = variant.mime_type
            etag_value = f"{variant.id}-{variant.updated_at.timestamp()}"
        else:
            raise StreamDenied("no compatible media variant is ready", context={"language": user.language_code})

        await self._acquire_connection(token, stream_session, user.language_code)
        stream_session.active_connections += 1
        stream_session.last_activity_at = now
        await session.flush()
        rate = None
        if user is not None:
            plan = await self._quota.effective_plan(session, user, now=now)
            rate = None if plan.stream_rate is None else max(1, plan.stream_rate // 8)
        return StreamGrant(
            session_id=stream_session.id,
            token_id=token.id,
            file_id=file.id,
            user_id=user.id,
            internal_path=internal_path,
            mime_type=mime_type,
            etag=f'"{etag_value}"',
            rate_bytes_per_second=rate,
        )

    async def hls_manifest(
        self,
        session: AsyncSession,
        *,
        raw_token: str,
        source_ip: str,
        user_agent: str,
    ) -> HlsManifest:
        token, file, user = await self._load(session, raw_token, lock=True)
        await self._ensure_session(
            session,
            token=token,
            file=file,
            user=user,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        variant = await session.scalar(
            select(MediaVariant).where(
                MediaVariant.file_id == file.id,
                MediaVariant.kind == "hls",
                MediaVariant.status == "ready",
                MediaVariant.deleted_at.is_(None),
            )
        )
        if variant is None:
            raise StreamDenied("HLS variant is unavailable", context={"language": user.language_code})
        segments = list(
            (
                await session.scalars(
                    select(MediaSegment)
                    .where(MediaSegment.variant_id == variant.id)
                    .order_by(MediaSegment.sequence_number)
                )
            ).all()
        )
        if not segments:
            raise StreamDenied("HLS segments are unavailable", context={"language": user.language_code})
        target = max(1, max((segment.duration_ms + 999) // 1000 for segment in segments))
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{target}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
        ]
        for segment in segments:
            lines.extend(
                [
                    f"#EXTINF:{segment.duration_ms / 1000:.3f},",
                    f"/hls/{raw_token}/{segment.sequence_number}.ts",
                ]
            )
        lines.append("#EXT-X-ENDLIST")
        return HlsManifest(body="\n".join(lines) + "\n")

    async def authorize_hls_segment(
        self,
        session: AsyncSession,
        *,
        raw_token: str,
        sequence_number: int,
        source_ip: str,
        user_agent: str,
    ) -> StreamGrant:
        token, file, user = await self._load(session, raw_token, lock=True)
        stream_session = await self._ensure_session(
            session,
            token=token,
            file=file,
            user=user,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        variant = await session.scalar(
            select(MediaVariant).where(
                MediaVariant.file_id == file.id,
                MediaVariant.kind == "hls",
                MediaVariant.status == "ready",
                MediaVariant.deleted_at.is_(None),
            )
        )
        segment = None
        if variant is not None:
            segment = await session.scalar(
                select(MediaSegment).where(
                    MediaSegment.variant_id == variant.id,
                    MediaSegment.sequence_number == sequence_number,
                )
            )
        if segment is None:
            raise StreamDenied("HLS segment is unavailable", context={"language": user.language_code})
        await self._acquire_connection(token, stream_session, user.language_code)
        stream_session.active_connections += 1
        stream_session.last_activity_at = datetime.now(UTC)
        await session.flush()
        plan = await self._quota.effective_plan(session, user)
        return StreamGrant(
            session_id=stream_session.id,
            token_id=token.id,
            file_id=file.id,
            user_id=user.id,
            internal_path=f"/__protected/hls/{segment.storage_key}",
            mime_type="video/mp2t",
            etag=f'"{variant.id}-{segment.sequence_number}-{segment.size_bytes}"',
            rate_bytes_per_second=None if plan.stream_rate is None else max(1, plan.stream_rate // 8),
        )

    async def _ensure_session(
        self,
        session: AsyncSession,
        *,
        token: StreamToken,
        file: File,
        user: User,
        source_ip: str,
        user_agent: str,
    ) -> StreamSession:
        now = datetime.now(UTC)
        ip_hash = self._digest(b"ip", source_ip)
        agent_hash = self._digest(b"ua", user_agent[:2048])
        stream_session = None
        if token.stream_session_id is not None:
            stream_session = await session.scalar(
                select(StreamSession)
                .where(StreamSession.id == token.stream_session_id)
                .with_for_update()
            )
        if stream_session is None:
            raw_session = secrets.token_urlsafe(32)
            stream_session = StreamSession(
                file_id=file.id,
                user_id=user.id,
                session_id_hash=self._digest(b"session", raw_session),
                source_ip_hash=ip_hash,
                user_agent_hash=agent_hash,
                status="active",
                allowed_quality=token.allowed_quality,
                expires_at=token.expires_at,
                last_activity_at=now,
            )
            session.add(stream_session)
            await session.flush()
            token.stream_session_id = stream_session.id
        if (
            stream_session.status != "active"
            or stream_session.expires_at <= now
            or token.revoked_at is not None
            or not hmac.compare_digest(stream_session.source_ip_hash, ip_hash)
            or not hmac.compare_digest(stream_session.user_agent_hash, agent_hash)
        ):
            raise StreamDenied("stream session is invalid", context={"language": user.language_code})
        return stream_session

    async def _acquire_connection(
        self,
        token: StreamToken,
        stream_session: StreamSession,
        language: str,
    ) -> None:
        now = datetime.now(UTC)
        key = self._redis.key("stream", "connections", str(stream_session.id))
        ttl = max(60, int((stream_session.expires_at - now).total_seconds()))
        acquired = int(
            await self._redis.client.eval(
                """
                local current = tonumber(redis.call('GET', KEYS[1]) or '0')
                if current >= tonumber(ARGV[1]) then return -1 end
                current = redis.call('INCR', KEYS[1])
                redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
                return current
                """,
                1,
                key,
                token.maximum_connections,
                ttl,
            )
        )
        if acquired < 0:
            raise StreamDenied("stream connection limit reached", context={"language": language})

    async def _load(
        self,
        session: AsyncSession,
        raw_token: str,
        *,
        lock: bool = False,
    ) -> tuple[StreamToken, File, User]:
        if STREAM_TOKEN_RE.fullmatch(raw_token) is None:
            raise StreamDenied("invalid stream token")
        query = select(StreamToken).where(
            StreamToken.token_hash == self._digest(b"stream", raw_token),
            StreamToken.purpose == "stream",
            StreamToken.key_version == 1,
        )
        token = await session.scalar(query.with_for_update() if lock else query)
        now = datetime.now(UTC)
        if token is None or token.revoked_at is not None or token.expires_at <= now:
            raise StreamDenied("stream token is invalid")
        file = await session.scalar(select(File).where(File.id == token.file_id))
        user = await session.scalar(select(User).where(User.id == token.user_id))
        if (
            file is None
            or user is None
            or file.status != "available"
            or file.deleted_at is not None
            or file.expires_at <= now
        ):
            raise StreamDenied("stream file is unavailable")
        return token, file, user
