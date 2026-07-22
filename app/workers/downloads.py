"""Bounded external and Telegram downloads into job-owned no-exec storage."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import socket
import stat
import struct
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from uuid import uuid4

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiohttp.abc import AbstractResolver
from aiohttp.payload import Payload
from aiohttp import MultipartWriter

from app.core.config import RuntimeSettings
from app.core.secrets import read_secret_file
from app.services.url_policy import is_forbidden_ip, normalize_external_url
from app.workers.client import (
    ProgressCallback,
    TelegramUploadResult,
    WorkerFailure,
    WorkerResult,
)


CHUNK_SIZE = 256 * 1024


class PinnedResolver(AbstractResolver):
    def __init__(self, hostname: str, addresses: list[str]) -> None:
        self._hostname = hostname
        self._addresses = addresses

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_UNSPEC):
        if host.lower().rstrip(".") != self._hostname:
            raise OSError("resolver hostname mismatch")
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
            for address in self._addresses
        ]

    async def close(self) -> None:
        return None


async def resolve_public(hostname: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    addresses = sorted({record[4][0] for record in records})
    if not addresses or any(is_forbidden_ip(address) for address in addresses):
        raise WorkerFailure("destination_forbidden")
    return addresses


def safe_filename(value: str) -> str:
    cleaned = "".join(character for character in value if character >= " " and character != "\x7f")
    cleaned = cleaned.replace("/", "_").replace("\\", "_").strip(" .")
    return (cleaned or "download.bin")[:255]


def sniff_mime(path: Path, filename: str) -> str:
    with path.open("rb") as handle:
        prefix = handle.read(16)
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF8", "image/gif"),
        (b"%PDF-", "application/pdf"),
        (b"PK\x03\x04", "application/zip"),
    )
    for signature, mime in signatures:
        if prefix.startswith(signature):
            return mime
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        return "video/mp4"
    return "application/octet-stream"


def write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write to managed storage")
        view = view[written:]


class LocalContent:
    def __init__(self, handle: Any) -> None:
        self._handle = handle

    async def iter_chunked(self, size: int):
        while chunk := await asyncio.to_thread(self._handle.read, size):
            yield chunk


class LocalResponse:
    def __init__(self, handle: Any, size: int) -> None:
        self.content = LocalContent(handle)
        self.content_length = size


class StorageWriter:
    def __init__(self, root: Path, clamav_host: str, clamav_port: int) -> None:
        self._root = root
        self._clamav_host = clamav_host
        self._clamav_port = clamav_port

    async def store_response(
        self,
        response: Any,
        *,
        job_id: str,
        filename: str,
        maximum_bytes: int,
        scan_required: bool,
        progress: ProgressCallback,
    ) -> WorkerResult:
        incoming = self._root / ".incoming" / job_id
        incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
        part = incoming / f"{uuid4()}.part"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(part, flags, 0o600)
        transferred = 0
        digest = hashlib.sha256()
        declared = response.content_length
        if declared is not None and declared > maximum_bytes:
            os.close(descriptor)
            part.unlink(missing_ok=True)
            raise WorkerFailure("file_too_large")
        try:
            async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                transferred += len(chunk)
                if transferred > maximum_bytes:
                    raise WorkerFailure("file_too_large", actual_bytes=transferred - len(chunk))
                write_all(descriptor, chunk)
                digest.update(chunk)
                if transferred % (8 * 1024**2) < CHUNK_SIZE:
                    percent = int(transferred * 100 / declared) if declared else 0
                    await progress(
                        {"stage": "downloading", "percent": min(percent, 99), "bytes": transferred}
                    )
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            part.unlink(missing_ok=True)
            raise
        os.close(descriptor)
        if transferred == 0:
            part.unlink(missing_ok=True)
            raise WorkerFailure("empty_response")
        await progress({"stage": "downloaded", "percent": 99, "bytes": transferred})
        scan_status = await self._scan(part) if scan_required else "skipped"
        if scan_status != "clean" and scan_required:
            part.unlink(missing_ok=True)
            raise WorkerFailure(f"scan_{scan_status}", actual_bytes=transferred)
        object_id = str(uuid4())
        relative = Path(digest.hexdigest()[:2]) / object_id
        final = self._root / relative
        final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(part, final)
        with suppress(OSError):
            incoming.rmdir()
        return WorkerResult(
            kind="download",
            storage_key=relative.as_posix(),
            filename=safe_filename(filename),
            size_bytes=transferred,
            sha256=digest.hexdigest(),
            detected_mime=sniff_mime(final, filename),
            scan_status=scan_status,
        )

    async def _scan(self, path: Path) -> str:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._clamav_host, self._clamav_port),
                timeout=3,
            )
            writer.write(b"zINSTREAM\0")
            with path.open("rb") as handle:
                while chunk := handle.read(CHUNK_SIZE):
                    writer.write(struct.pack("!I", len(chunk)))
                    writer.write(chunk)
                    await writer.drain()
            writer.write(struct.pack("!I", 0))
            await writer.drain()
            response = await asyncio.wait_for(reader.readuntil(b"\0"), timeout=60)
            writer.close()
            await writer.wait_closed()
        except Exception:
            return "failed"
        if b"FOUND" in response:
            return "infected"
        return "clean" if b"OK" in response else "failed"


class ExternalDownloadProcessor:
    def __init__(self, writer: StorageWriter) -> None:
        self._writer = writer

    async def __call__(self, job: dict[str, Any], progress: ProgressCallback) -> WorkerResult:
        payload = job["payload"]
        policy = job["policy"]
        current = normalize_external_url(str(payload["url"]))
        for redirect_count in range(4):
            addresses = await resolve_public(current.hostname, current.port)
            connector = TCPConnector(
                resolver=PinnedResolver(current.hostname, addresses),
                use_dns_cache=False,
                ttl_dns_cache=0,
                limit=4,
                ssl=True,
            )
            timeout = ClientTimeout(total=3600, connect=10, sock_connect=10, sock_read=30)
            async with ClientSession(
                connector=connector,
                timeout=timeout,
                auto_decompress=False,
                max_line_size=8192,
                max_field_size=8192,
            ) as session:
                async with session.get(current.url, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        if redirect_count >= 3 or "Location" not in response.headers:
                            raise WorkerFailure("redirect_limit")
                        current = normalize_external_url(urljoin(current.url, response.headers["Location"]))
                        continue
                    if response.status < 200 or response.status >= 300:
                        raise WorkerFailure("origin_http_error")
                    filename = safe_filename(unquote(PurePosixPath(urlsplit(current.url).path).name))
                    return await self._writer.store_response(
                        response,
                        job_id=job["job_id"],
                        filename=filename,
                        maximum_bytes=int(policy["max_file_size"]),
                        scan_required=bool(policy["scan_required"]),
                        progress=progress,
                    )
        raise WorkerFailure("redirect_limit")


class TelegramDownloadProcessor:
    def __init__(self, settings: RuntimeSettings, writer: StorageWriter) -> None:
        self._settings = settings
        self._writer = writer
        self._token = read_secret_file(settings.bot_token_file, minimum_length=30)  # type: ignore[arg-type]

    async def __call__(self, job: dict[str, Any], progress: ProgressCallback) -> WorkerResult:
        payload = job["payload"]
        base = self._settings.telegram_api_base_url
        timeout = ClientTimeout(total=3600, connect=10, sock_read=30)
        async with ClientSession(timeout=timeout, auto_decompress=False) as session:
            async with session.post(
                f"{base}/bot{self._token}/getFile",
                json={"file_id": payload["telegram_file_id"]},
            ) as metadata_response:
                metadata = await metadata_response.json()
                if metadata_response.status != 200 or not metadata.get("ok"):
                    raise WorkerFailure("telegram_get_file_failed")
                file_path = str(metadata["result"]["file_path"])
            if os.path.isabs(file_path):
                root = Path("/var/lib/telegram-bot-api").resolve()
                source = Path(file_path)
                try:
                    resolved = source.resolve(strict=True)
                    resolved.relative_to(root)
                    source_stat = source.lstat()
                except (OSError, ValueError) as exc:
                    raise WorkerFailure("telegram_local_path_invalid") from exc
                if source.is_symlink() or not stat.S_ISREG(source_stat.st_mode):
                    raise WorkerFailure("telegram_local_path_invalid")
                descriptor = os.open(
                    source,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                )
                with os.fdopen(descriptor, "rb", closefd=True) as handle:
                    return await self._writer.store_response(
                        LocalResponse(handle, source_stat.st_size),
                        job_id=job["job_id"],
                        filename=str(payload["filename"]),
                        maximum_bytes=int(job["policy"]["max_file_size"]),
                        scan_required=bool(job["policy"]["scan_required"]),
                        progress=progress,
                    )
            async with session.get(f"{base}/file/bot{self._token}/{file_path.lstrip('/')}") as response:
                if response.status != 200:
                    raise WorkerFailure("telegram_download_failed")
                return await self._writer.store_response(
                    response,
                    job_id=job["job_id"],
                    filename=str(payload["filename"]),
                    maximum_bytes=int(job["policy"]["max_file_size"]),
                    scan_required=bool(job["policy"]["scan_required"]),
                    progress=progress,
                )


class ProgressFilePayload(Payload):
    """Known-length multipart payload that reports bytes actually written to the socket."""

    def __init__(
        self,
        path: Path,
        *,
        size: int,
        progress: ProgressCallback,
    ) -> None:
        super().__init__(path, content_type="application/octet-stream")
        self._path = path
        self._size = size
        self._progress = progress

    async def write(self, writer: Any) -> None:
        transferred = 0
        with self._path.open("rb") as handle:
            while chunk := await asyncio.to_thread(handle.read, CHUNK_SIZE):
                await writer.write(chunk)
                transferred += len(chunk)
                percent = min(99, int(transferred * 100 / max(1, self._size)))
                await self._progress(
                    {"stage": "uploading", "percent": percent, "bytes": transferred}
                )


class TelegramUploadProcessor:
    """Upload a previously stored file after rechecking path, size, and capability."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._root = settings.storage_root.resolve()
        self._token = read_secret_file(settings.bot_token_file, minimum_length=30)  # type: ignore[arg-type]

    async def __call__(
        self,
        job: dict[str, Any],
        progress: ProgressCallback,
    ) -> TelegramUploadResult:
        payload = job["payload"]
        relative = PurePosixPath(str(payload["storage_key"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkerFailure("storage_path_invalid")
        source = self._root.joinpath(*relative.parts)
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(self._root)
            source_stat = source.lstat()
        except (OSError, ValueError) as exc:
            raise WorkerFailure("storage_path_invalid") from exc
        if source.is_symlink() or not stat.S_ISREG(source_stat.st_mode):
            raise WorkerFailure("storage_path_invalid")
        expected_size = int(payload["size_bytes"])
        if job["policy"].get("telegram_api_mode") != self._settings.telegram_api_mode:
            raise WorkerFailure("telegram_capability_changed")
        capability_limit = int(job["policy"]["telegram_upload_limit"])
        if self._settings.telegram_api_mode == "official":
            capability_limit = min(capability_limit, 50 * 1024**2)
        if source_stat.st_size != expected_size:
            raise WorkerFailure("stored_file_size_mismatch")
        if expected_size > capability_limit:
            raise WorkerFailure("telegram_upload_limit_exceeded")

        multipart = MultipartWriter("form-data")
        chat = multipart.append(str(int(payload["chat_id"])))
        chat.set_content_disposition("form-data", name="chat_id")
        document = multipart.append_payload(
            ProgressFilePayload(source, size=expected_size, progress=progress)
        )
        document.set_content_disposition(
            "form-data",
            name="document",
            filename=safe_filename(str(payload["filename"])),
        )
        timeout = ClientTimeout(total=7200, connect=10, sock_connect=10, sock_read=120)
        async with ClientSession(timeout=timeout, auto_decompress=False) as session:
            async with session.post(
                f"{self._settings.telegram_api_base_url}/bot{self._token}/sendDocument",
                data=multipart,
            ) as response:
                raw = await response.content.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise WorkerFailure("telegram_response_too_large", actual_bytes=expected_size)
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise WorkerFailure(
                        "telegram_response_invalid", actual_bytes=expected_size
                    ) from exc
                if response.status != 200 or not body.get("ok"):
                    raise WorkerFailure("telegram_upload_failed", actual_bytes=expected_size)
        result = body.get("result", {})
        telegram_document = result.get("document", {})
        file_id = telegram_document.get("file_id")
        message_id = result.get("message_id")
        if not isinstance(file_id, str) or not file_id or not isinstance(message_id, int):
            raise WorkerFailure("telegram_response_invalid", actual_bytes=expected_size)
        await progress({"stage": "uploaded", "percent": 100, "bytes": expected_size})
        return TelegramUploadResult(
            kind="telegram_upload",
            telegram_message_id=message_id,
            telegram_file_id=file_id,
            size_bytes=expected_size,
        )
