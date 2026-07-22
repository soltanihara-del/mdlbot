"""Opaque download links and IP-bound sessions for X-Accel-Redirect delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import re
import secrets
from typing import Any
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError, DownloadDenied
from app.core.secrets import read_secret_file
from app.core.redis import RedisManager
from app.db.models.files import DownloadLink, DownloadSession, File, FileReference
from app.db.models.identity import User
from app.services.quota import QuotaService
from app.core.permissions import AuthorizationService
from app.core.settings import SettingsService


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


@dataclass(frozen=True, slots=True)
class LinkGrant:
    url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: UUID
    raw_session: str | None
    redirect_url: str | None
    internal_path: str | None
    filename: str
    mime_type: str
    etag: str
    rate_bytes_per_second: int | None
    language: str
    link_id: UUID
    file_id: UUID
    user_id: UUID


class DownloadService:
    def __init__(
        self,
        settings: RuntimeSettings,
        redis: RedisManager,
        quota: QuotaService | None = None,
        settings_service: SettingsService | None = None,
    ) -> None:
        self._settings = settings
        self._quota = quota or QuotaService()
        self._redis = redis
        self._policy_settings = settings_service or SettingsService(AuthorizationService(), redis)
        if settings.download_signing_key_file is None:
            raise ConfigurationError("DOWNLOAD_SIGNING_KEY_FILE is required")
        raw = read_secret_file(settings.download_signing_key_file, minimum_length=64)
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise ConfigurationError("download signing key must be hexadecimal") from exc
        if len(key) != 32:
            raise ConfigurationError("download signing key must contain exactly 32 bytes")
        self._key = key

    def _digest(self, namespace: bytes, value: str) -> bytes:
        return hmac.new(self._key, namespace + b":" + value.encode("utf-8"), hashlib.sha256).digest()

    async def create_link(
        self,
        session: AsyncSession,
        *,
        user: User,
        file_id: UUID,
        one_time: bool = False,
    ) -> LinkGrant:
        if not self._settings.public_domain:
            raise ConfigurationError("PUBLIC_DOMAIN is required to create download links")
        now = datetime.now(UTC)
        reference = await session.scalar(
            select(FileReference)
            .where(
                FileReference.user_id == user.id,
                FileReference.file_id == file_id,
                FileReference.deleted_at.is_(None),
                FileReference.expires_at > now,
            )
            .with_for_update()
        )
        file = await session.scalar(
            select(File).where(
                File.id == file_id,
                File.owner_user_id == user.id,
                File.status == "available",
                File.deleted_at.is_(None),
                File.expires_at > now,
            )
        )
        if reference is None or file is None:
            raise DownloadDenied("file is not available")
        plan = await self._quota.effective_plan(session, user, now=now)
        settings = (await self._policy_settings.get_snapshot(session)).values
        if one_time and not plan.one_time_link_enabled:
            raise DownloadDenied("one-time links are disabled for this plan")
        active = int(
            await session.scalar(
                select(func.count()).select_from(DownloadLink).where(
                    DownloadLink.owner_user_id == user.id,
                    DownloadLink.status == "active",
                    DownloadLink.expires_at > now,
                )
            )
            or 0
        )
        if active >= plan.active_link_limit:
            raise DownloadDenied("active link limit reached")
        raw_token = secrets.token_urlsafe(32)
        expires_at = min(file.expires_at, reference.expires_at)
        link = DownloadLink(
            file_id=file.id,
            file_reference_id=reference.id,
            owner_user_id=user.id,
            token_hash=self._digest(b"link", raw_token),
            key_version=1,
            status="active",
            purpose="private",
            expires_at=expires_at,
            max_downloads=1 if one_time else None,
            one_time=one_time,
            policy={
                "concurrent_downloads": plan.concurrent_downloads,
                "connection_limit": min(
                    plan.download_connection_limit,
                    int(settings["downloads.max_connections"]),
                ),
                "allowed_ips": plan.allowed_ips_per_session,
                "resume_limit": plan.resume_limit,
                "range_limit": min(
                    plan.range_request_limit,
                    int(settings["downloads.max_range_requests"]),
                ),
                "rate": plan.download_rate or int(settings["downloads.rate"]),
                "session_ttl": int(settings["downloads.session_ttl"]),
            },
        )
        session.add(link)
        await session.flush()
        return LinkGrant(
            url=f"https://{self._settings.public_domain}/d/{raw_token}",
            expires_at=expires_at,
        )

    async def authorize(
        self,
        session: AsyncSession,
        *,
        raw_token: str,
        raw_session: str | None,
        source_ip: str,
        user_agent: str,
        range_header: str | None,
    ) -> SessionGrant:
        if TOKEN_RE.fullmatch(raw_token) is None:
            raise DownloadDenied("invalid download token")
        now = datetime.now(UTC)
        token_hash = self._digest(b"link", raw_token)
        link = await session.scalar(
            select(DownloadLink).where(DownloadLink.token_hash == token_hash).with_for_update()
        )
        if link is None:
            raise DownloadDenied("download link was not found")
        file = await session.scalar(select(File).where(File.id == link.file_id).with_for_update())
        user = await session.scalar(select(User).where(User.id == link.owner_user_id))
        language = user.language_code if user is not None else "en"
        if file is None or file.status != "available" or file.expires_at <= now:
            raise DownloadDenied("file is no longer available", context={"language": language})
        ip_hash = self._digest(b"ip", source_ip)
        agent_hash = self._digest(b"ua", user_agent[:2048])
        if raw_session is None:
            if link.status != "active" or link.expires_at <= now:
                raise DownloadDenied("download link has expired", context={"language": language})
            active_sessions = int(
                await session.scalar(
                    select(func.count()).select_from(DownloadSession).where(
                        DownloadSession.owner_user_id == link.owner_user_id,
                        DownloadSession.status == "active",
                        DownloadSession.expires_at > now,
                    )
                )
                or 0
            )
            concurrent = int(link.policy.get("concurrent_downloads", 1))
            if active_sessions >= concurrent:
                raise DownloadDenied("concurrent download limit reached", context={"language": language})
            raw_session = secrets.token_urlsafe(32)
            session_ttl = int(link.policy.get("session_ttl", 3600))
            download_session = DownloadSession(
                download_link_id=link.id,
                file_id=file.id,
                owner_user_id=link.owner_user_id,
                session_id_hash=self._digest(b"session", raw_session),
                source_ip_hash=ip_hash,
                user_agent_hash=agent_hash,
                status="active",
                expires_at=min(link.expires_at, now + timedelta(seconds=session_ttl)),
                last_activity_at=now,
            )
            session.add(download_session)
            link.download_count += 1
            if link.one_time or (
                link.max_downloads is not None and link.download_count >= link.max_downloads
            ):
                link.status = "exhausted"
            await session.flush()
            return self._grant(
                link,
                file,
                download_session,
                language=language,
                raw_session=raw_session,
                redirect_url=f"/d/{raw_token}?s={raw_session}",
            )
        if TOKEN_RE.fullmatch(raw_session) is None:
            raise DownloadDenied("invalid download session", context={"language": language})
        download_session = await session.scalar(
            select(DownloadSession)
            .where(
                DownloadSession.download_link_id == link.id,
                DownloadSession.session_id_hash == self._digest(b"session", raw_session),
            )
            .with_for_update()
        )
        if (
            download_session is None
            or download_session.status != "active"
            or download_session.expires_at <= now
            or link.status in {"revoked", "expired"}
        ):
            raise DownloadDenied("download session has expired", context={"language": language})
        if not hmac.compare_digest(download_session.source_ip_hash, ip_hash):
            raise DownloadDenied("download session address changed", context={"language": language})
        if not hmac.compare_digest(download_session.user_agent_hash, agent_hash):
            raise DownloadDenied("download client changed", context={"language": language})
        if range_header:
            match = RANGE_RE.fullmatch(range_header.strip())
            if match is None or (not match.group(1) and not match.group(2)):
                raise DownloadDenied("invalid byte range", context={"language": language})
            download_session.range_requests += 1
            if match.group(1) and int(match.group(1)) > 0:
                download_session.resume_count += 1
            if download_session.range_requests > int(link.policy.get("range_limit", 1000)):
                raise DownloadDenied("range request limit reached", context={"language": language})
            if download_session.resume_count > int(link.policy.get("resume_limit", 20)):
                raise DownloadDenied("resume limit reached", context={"language": language})
        download_session.last_activity_at = now
        connection_limit = int(link.policy.get("connection_limit", 1))
        ttl = max(60, int((download_session.expires_at - now).total_seconds()))
        acquired = int(
            await self._redis.client.eval(
                """
                local current = tonumber(redis.call('GET', KEYS[1]) or '0')
                local maximum = tonumber(ARGV[1])
                if current >= maximum then return -1 end
                current = redis.call('INCR', KEYS[1])
                redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
                return current
                """,
                1,
                self._redis.key("download", "connections", str(download_session.id)),
                connection_limit,
                ttl,
            )
        )
        if acquired < 0:
            raise DownloadDenied("download connection limit reached", context={"language": language})
        download_session.active_connections += 1
        await session.flush()
        return self._grant(link, file, download_session, language=language)

    @staticmethod
    def _grant(
        link: DownloadLink,
        file: File,
        download_session: DownloadSession,
        *,
        language: str,
        raw_session: str | None = None,
        redirect_url: str | None = None,
    ) -> SessionGrant:
        digest = file.sha256.hex() if file.sha256 is not None else str(file.id)
        rate = link.policy.get("rate")
        return SessionGrant(
            session_id=download_session.id,
            raw_session=raw_session,
            redirect_url=redirect_url,
            internal_path=None if redirect_url else f"/__protected/files/{file.storage_key}",
            filename=file.safe_display_filename,
            mime_type=file.detected_mime,
            etag=f'"{digest}"',
            rate_bytes_per_second=None if rate is None else max(1, int(rate) // 8),
            language=language,
            link_id=link.id,
            file_id=file.id,
            user_id=link.owner_user_id,
        )


def content_disposition(filename: str) -> str:
    fallback = "".join(
        character if 32 <= ord(character) < 127 and character not in {'"', "\\"} else "_"
        for character in filename
    ).strip(" .") or "download.bin"
    return f"attachment; filename=\"{fallback[:180]}\"; filename*=UTF-8''{quote(filename, safe='')}"
