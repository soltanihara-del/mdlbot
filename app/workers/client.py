"""Isolated worker polling/report client; it never receives database credentials."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Awaitable, Callable
from uuid import UUID

from aiohttp import ClientSession, ClientTimeout

from app.core.config import RuntimeSettings
from app.core.errors import DependencyUnavailable
from app.core.secrets import read_secret_file
from app.core.logging import get_logger


@dataclass(frozen=True, slots=True)
class WorkerResult:
    kind: str
    storage_key: str
    filename: str
    size_bytes: int
    sha256: str
    detected_mime: str
    scan_status: str


@dataclass(frozen=True, slots=True)
class TelegramUploadResult:
    kind: str
    telegram_message_id: int
    telegram_file_id: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class MediaWorkerResult:
    kind: str
    size_bytes: int
    direct_play_compatible: bool
    metadata: dict[str, Any]
    variants: list[dict[str, Any]]


class WorkerFailure(Exception):
    def __init__(self, code: str, *, actual_bytes: int = 0) -> None:
        super().__init__(code)
        self.code = code if re.fullmatch(r"[a-z][a-z0-9_.-]{2,95}", code) else "worker_failed"
        self.actual_bytes = max(0, actual_bytes)


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
Processor = Callable[
    [dict[str, Any], ProgressCallback],
    Awaitable[WorkerResult | TelegramUploadResult | MediaWorkerResult],
]


class WorkerClient:
    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        job_type: str,
        worker_id: str,
        processor: Processor,
    ) -> None:
        settings.validate_worker_files(api=False)
        self._settings = settings
        self._job_type = job_type
        self._worker_id = worker_id
        self._processor = processor
        self._token = read_secret_file(settings.worker_token_file, minimum_length=32)  # type: ignore[arg-type]
        self._session: ClientSession | None = None
        self._log = get_logger(f"worker.{job_type}")

    async def start(self) -> None:
        self._session = ClientSession(timeout=ClientTimeout(total=30, connect=3))

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None

    async def run_once(self) -> bool:
        response = await self._post(
            "/internal/workers/claim",
            {"job_type": self._job_type, "worker_id": self._worker_id},
        )
        job = response.get("job")
        if not job:
            return False

        async def progress(payload: dict[str, Any]) -> None:
            report = self._lease_payload(job)
            report["progress"] = payload
            result = await self._post(
                "/internal/workers/heartbeat", report, accept_conflict=True
            )
            if not result.get("ok"):
                code = str(result.get("code", "lease_lost"))
                raise WorkerFailure(code, actual_bytes=int(payload.get("bytes", 0)))

        try:
            result = await self._processor(job, progress)
            payload = self._lease_payload(job)
            payload.update(
                {
                    "stream": job["stream"],
                    "group": job["group"],
                    "message_id": job["message_id"],
                    "result": asdict(result),
                }
            )
            completed = await self._post("/internal/workers/complete", payload)
            if not completed.get("ok"):
                raise WorkerFailure("completion_rejected", actual_bytes=result.size_bytes)
        except Exception as raw_exc:
            exc = raw_exc if isinstance(raw_exc, WorkerFailure) else WorkerFailure("worker_io_error")
            payload = self._lease_payload(job)
            payload.update(
                {
                    "stream": job["stream"],
                    "group": job["group"],
                    "message_id": job["message_id"],
                    "error_code": exc.code,
                    "actual_bytes": exc.actual_bytes,
                }
            )
            await self._post("/internal/workers/fail", payload, accept_conflict=True)
        return True

    async def run(self, stop: asyncio.Event, heartbeat_file: Path) -> None:
        await self.start()
        try:
            while not stop.is_set():
                heartbeat_file.write_text("ready\n", encoding="ascii")
                try:
                    handled = await self.run_once()
                except Exception as exc:
                    self._log.warning("worker_control_cycle_failed", error_type=type(exc).__name__)
                    handled = False
                if not handled:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=1.0)
                    except TimeoutError:
                        continue
        finally:
            await self.close()

    def _lease_payload(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": job["job_id"],
            "generation": job["generation"],
            "lease": job["lease"],
        }

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accept_conflict: bool = False,
    ) -> dict[str, Any]:
        if self._session is None:
            raise DependencyUnavailable("worker HTTP client is not started")
        try:
            async with self._session.post(
                f"{self._settings.worker_control_url}{path}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-Worker-Job-Type": self._job_type,
                },
            ) as response:
                if response.status == 409 and accept_conflict:
                    try:
                        value = await response.json()
                    except Exception:
                        value = {"ok": False}
                    return value if isinstance(value, dict) else {"ok": False}
                if response.status < 200 or response.status >= 300:
                    raise DependencyUnavailable(
                        "worker control request failed",
                        context={"status": response.status, "path": path},
                    )
                value = await response.json()
                if not isinstance(value, dict):
                    raise DependencyUnavailable("worker control returned malformed JSON")
                return value
        except WorkerFailure:
            raise
        except DependencyUnavailable:
            raise
        except Exception as exc:
            raise DependencyUnavailable("worker control is unavailable") from exc
