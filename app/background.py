"""Long-running dispatcher and isolated worker process orchestration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import signal

from sqlalchemy import select

from app.core.config import RuntimeSettings
from app.core.logging import get_logger
from app.core.permissions import AuthorizationService
from app.core.redis import RedisManager
from app.core.settings import SettingsService
from app.db.models.jobs import Job, JobEvent
from app.db.session import Database
from app.dispatcher.service import DispatcherService, OutboxPublisher
from app.workers.client import WorkerClient
from app.services.quota import QuotaService
from app.usage import UsageCollector
from app.workers.downloads import (
    ExternalDownloadProcessor,
    StorageWriter,
    TelegramDownloadProcessor,
    TelegramUploadProcessor,
)
from app.workers.media import MediaProcessor


def heartbeat_path(service: str) -> Path:
    return Path("/tmp") / f"mdlbot-{service}.ready"


def install_stop_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            continue


async def run_background_service(service: str, settings: RuntimeSettings) -> None:
    stop = asyncio.Event()
    install_stop_handlers(stop)
    if service == "dispatcher":
        await run_dispatcher(settings, stop)
        return
    if service == "usage-collector":
        settings.validate_dependencies()
        database = Database(settings)
        redis = RedisManager(settings)
        await database.start()
        await redis.start()
        try:
            await UsageCollector(settings, database, redis).run(
                stop,
                heartbeat_path(service),
            )
        finally:
            heartbeat_path(service).unlink(missing_ok=True)
            await redis.close()
            await database.close()
        return
    writer = StorageWriter(
        settings.storage_root,
        clamav_host=settings.clamav_host,
        clamav_port=settings.clamav_port,
    )
    if service == "external-download-worker":
        processor = ExternalDownloadProcessor(writer)
        job_type = "external_download"
    elif service == "telegram-download-worker":
        if settings.bot_token_file is None:
            raise ValueError("BOT_TOKEN_FILE is required for Telegram downloads")
        processor = TelegramDownloadProcessor(settings, writer)
        job_type = "telegram_download"
    elif service == "telegram-upload-worker":
        if settings.bot_token_file is None:
            raise ValueError("BOT_TOKEN_FILE is required for Telegram uploads")
        processor = TelegramUploadProcessor(settings)
        job_type = "telegram_upload"
    elif service == "media-worker":
        processor = MediaProcessor(settings)
        job_type = "media_process"
    else:
        raise ValueError(f"unsupported background service: {service}")
    client = WorkerClient(
        settings,
        job_type=job_type,
        worker_id=f"{service}-{settings.instance_id}",
        processor=processor,
    )
    await client.run(stop, heartbeat_path(service))


async def run_dispatcher(settings: RuntimeSettings, stop: asyncio.Event) -> None:
    settings.validate_dependencies()
    database = Database(settings)
    redis = RedisManager(settings)
    await database.start()
    await redis.start()
    dispatcher = DispatcherService()
    publisher = OutboxPublisher(redis)
    quota = QuotaService()
    settings_service = SettingsService(AuthorizationService(), redis)
    log = get_logger("dispatcher")
    try:
        while not stop.is_set():
            heartbeat_path("dispatcher").write_text("ready\n", encoding="ascii")
            dispatched = 0
            try:
                async with database.transaction() as session:
                    snapshot = await settings_service.get_snapshot(session)
                    await recover_expired_jobs(session)
                    await quota.reconcile_expired(session)
                    batch = int(snapshot.values["queue.dispatch_batch"])
                    job_types = ("external_download", "telegram_download", "telegram_upload", "media_process")
                    for batch_index in range(batch):
                        selected = None
                        for offset in range(len(job_types)):
                            job_type = job_types[(batch_index + offset) % len(job_types)]
                            selected = await dispatcher.dispatch_one(
                                session,
                                job_type=job_type,
                                aging_step_seconds=int(snapshot.values["queue.aging_step"]),
                                max_normal_wait_seconds=int(snapshot.values["queue.max_normal_wait"]),
                                max_consecutive_vip=int(snapshot.values["queue.max_consecutive_vip"]),
                            )
                            if selected is not None:
                                dispatched += 1
                                break
                        if selected is None:
                            break
                async with database.transaction() as session:
                    published = await publisher.publish_batch(session)
            except Exception as exc:
                log.warning("dispatcher_cycle_failed", error_type=type(exc).__name__)
                published = 0
            if dispatched == 0 and published == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.5)
                except TimeoutError:
                    continue
    finally:
        heartbeat_path("dispatcher").unlink(missing_ok=True)
        await redis.close()
        await database.close()


async def recover_expired_jobs(session) -> int:
    now = datetime.now(UTC)
    jobs = list(
        (
            await session.scalars(
                select(Job)
                .where(
                    Job.status.in_(
                        (
                            "dispatched", "downloading", "receiving", "scanning", "processing",
                            "remuxing", "transcoding", "uploading", "generating_link",
                        )
                    ),
                    Job.lease_expires_at.is_not(None),
                    Job.lease_expires_at <= now,
                )
                .order_by(Job.lease_expires_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for job in jobs:
        previous = job.status
        job.status = "failed"
        job.last_error_code = "lease_expired"
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="lease_expired",
                from_status=previous,
                to_status="failed",
                actor_type="scheduler",
                actor_id=None,
                details={"generation": job.dispatch_generation},
            )
        )
        await session.flush()
        target = "dead_letter" if job.attempt_count >= job.max_attempts else "queued"
        job.status = target
        job.queued_at = now if target == "queued" else job.queued_at
        job.assigned_instance_id = None
        job.lease_token_hash = None
        job.lease_expires_at = None
        session.add(
            JobEvent(
                job_id=job.id,
                event_type=f"recovery.{target}",
                from_status="failed",
                to_status=target,
                actor_type="scheduler",
                actor_id=None,
                details={},
            )
        )
        await session.flush()
    return len(jobs)
