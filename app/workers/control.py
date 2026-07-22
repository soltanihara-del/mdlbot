"""Redis Stream gateway with durable PostgreSQL generation and lease checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from redis.exceptions import ResponseError
from sqlalchemy import select

from app import __version__
from app.core.redis import RedisManager
from app.db.models.files import File, FileReference, MediaSegment, MediaVariant
from app.db.models.jobs import ApplicationInstance, Job, JobAttempt, JobEvent, OutboxEvent
from app.db.session import Database
from app.services.quota import QuotaService


RUNNING_STATE = {
    "external_download": "downloading",
    "telegram_download": "receiving",
    "telegram_upload": "uploading",
    "media_process": "processing",
}


class WorkerControlService:
    def __init__(
        self,
        database: Database,
        redis: RedisManager,
        quota: QuotaService,
    ) -> None:
        self._database = database
        self._redis = redis
        self._quota = quota
        self._consecutive_vip: dict[str, int] = {}

    async def claim(
        self,
        *,
        job_type: str,
        worker_id: str,
        max_consecutive_vip: int = 4,
    ) -> dict[str, Any] | None:
        if job_type not in RUNNING_STATE:
            return None
        group = f"workers:{job_type}"
        prefer_vip = self._consecutive_vip.get(job_type, 0) < max_consecutive_vip
        lanes = ("vip", "normal") if prefer_vip else ("normal", "vip")
        for lane in lanes:
            stream = self._redis.key("stream", f"jobs:{job_type}:{lane}")
            await self._ensure_group(stream, group)
            messages = await self._redis.client.xreadgroup(
                group,
                worker_id,
                {stream: ">"},
                count=1,
                block=250,
            )
            if not messages:
                continue
            _stream_name, entries = messages[0]
            message_id, fields = entries[0]
            try:
                payload = json.loads(fields["payload"])
                job_id = UUID(payload["job_id"])
                generation = int(payload["generation"])
                lease = str(payload["lease"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                await self._redis.client.xack(stream, group, message_id)
                continue
            claimed = await self._claim_durable(
                job_id=job_id,
                generation=generation,
                lease=lease,
                worker_id=worker_id,
                job_type=job_type,
            )
            if claimed is None:
                await self._redis.client.xack(stream, group, message_id)
                continue
            self._consecutive_vip[job_type] = (
                self._consecutive_vip.get(job_type, 0) + 1 if lane == "vip" else 0
            )
            return {
                **claimed,
                "stream": stream,
                "group": group,
                "message_id": str(message_id),
                "lease": lease,
            }
        return None

    async def _ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.client.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _claim_durable(
        self,
        *,
        job_id: UUID,
        generation: int,
        lease: str,
        worker_id: str,
        job_type: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            digest = hashlib.sha256(lease.encode("ascii")).digest()
            if (
                job is None
                or job.status != "dispatched"
                or job.job_type != job_type
                or job.dispatch_generation != generation
                or job.lease_token_hash is None
                or not hmac.compare_digest(job.lease_token_hash, digest)
                or job.lease_expires_at is None
                or job.lease_expires_at <= now
            ):
                return None
            if job.attempt_count >= job.max_attempts:
                job.status = "dead_letter"
                job.lease_token_hash = None
                job.lease_expires_at = None
                session.add(
                    JobEvent(
                        job_id=job.id,
                        event_type="attempts_exhausted",
                        from_status="dispatched",
                        to_status="dead_letter",
                        actor_type="worker",
                        details={"generation": generation},
                    )
                )
                await self._quota.reconcile(
                    session,
                    job=job,
                    actual_bytes=job.bytes_transferred,
                    success=False,
                )
                await session.flush()
                return None
            instance = await session.scalar(
                select(ApplicationInstance).where(
                    ApplicationInstance.installation_id == "default",
                    ApplicationInstance.instance_name == worker_id,
                )
            )
            if instance is None:
                instance = ApplicationInstance(
                    installation_id="default",
                    instance_name=worker_id,
                    service_type=job_type,
                    version=__version__,
                    status="ready",
                    started_at=now,
                    last_heartbeat_at=now,
                    metadata_json={},
                )
                session.add(instance)
                await session.flush()
            else:
                instance.status = "ready"
                instance.last_heartbeat_at = now
            running = RUNNING_STATE[job_type]
            job.status = running
            job.started_at = job.started_at or now
            job.attempt_count += 1
            job.assigned_instance_id = instance.id
            job.lease_expires_at = now + timedelta(seconds=120)
            attempt = JobAttempt(
                job_id=job.id,
                attempt_number=job.attempt_count,
                dispatch_generation=generation,
                instance_id=instance.id,
                status="running",
                started_at=now,
                heartbeat_at=now,
                checkpoint={},
            )
            session.add(attempt)
            session.add(
                JobEvent(
                    job_id=job.id,
                    attempt_id=attempt.id,
                    event_type="claimed",
                    from_status="dispatched",
                    to_status=running,
                    actor_type="worker",
                    actor_id=instance.id,
                    details={"generation": generation},
                )
            )
            await session.flush()
            return {
                "job_id": str(job.id),
                "generation": generation,
                "job_type": job.job_type,
                "payload": job.payload,
                "policy": job.policy_snapshot,
                "attempt": job.attempt_count,
            }

    async def heartbeat(
        self,
        *,
        job_id: UUID,
        generation: int,
        lease: str,
        progress: dict[str, Any] | None = None,
        expected_job_type: str | None = None,
    ) -> bool:
        async with self._database.transaction() as session:
            job = await self._validated_job(
                session, job_id, generation, lease, expected_job_type=expected_job_type
            )
            if job is None:
                return False
            now = datetime.now(UTC)
            job.lease_expires_at = now + timedelta(seconds=120)
            await self._quota.touch(session, job=job, now=now)
            attempt = await session.scalar(
                select(JobAttempt)
                .where(
                    JobAttempt.job_id == job.id,
                    JobAttempt.attempt_number == job.attempt_count,
                )
                .with_for_update()
            )
            if attempt is not None:
                attempt.heartbeat_at = now
                if progress:
                    attempt.checkpoint = dict(progress)
            if progress:
                requested_bytes = int(progress.get("bytes", job.bytes_transferred))
                if requested_bytes > (job.total_bytes or 0):
                    await self._quota.top_up(session, job=job, required_bytes=requested_bytes)
                percent = max(0, min(100, int(progress.get("percent", job.progress_percent))))
                job.progress_percent = percent
                job.progress_stage = str(progress.get("stage", job.progress_stage or "processing"))[:32]
                job.bytes_transferred = max(
                    job.bytes_transferred,
                    int(progress.get("bytes", job.bytes_transferred)),
                )
                await self._redis.set_json(
                    f"progress:{job.id}",
                    {
                        "stage": job.progress_stage,
                        "percent": job.progress_percent,
                        "bytes": job.bytes_transferred,
                        "generation": generation,
                    },
                    ttl_seconds=3600,
                )
                await self._publish_progress(
                    job.id,
                    stage=job.progress_stage,
                    percent=job.progress_percent,
                    bytes_transferred=job.bytes_transferred,
                )
            await session.flush()
            return True

    async def complete(
        self,
        *,
        job_id: UUID,
        generation: int,
        lease: str,
        result: dict[str, Any],
        stream: str,
        group: str,
        message_id: str,
        expected_job_type: str | None = None,
    ) -> bool:
        async with self._database.transaction() as session:
            job = await self._validated_job(
                session, job_id, generation, lease, expected_job_type=expected_job_type
            )
            if job is None:
                return False
            if not await self._transport_matches(
                session, job, generation, stream, group, message_id
            ):
                return False
            if job.job_type == "telegram_upload":
                if result.get("kind") != "telegram_upload":
                    return False
                await self._complete_upload_locked(session, job, result)
                scan_failed = False
                upload_completed = True
            elif job.job_type == "media_process":
                if result.get("kind") != "media":
                    return False
                await self._complete_media_locked(session, job, result)
                scan_failed = False
                upload_completed = False
            else:
                if result.get("kind") != "download":
                    return False
                scan_failed = await self._complete_download_locked(session, job, result)
                upload_completed = False
        await self._redis.client.xack(stream, group, message_id)
        if scan_failed:
            return True
        progress = {
            "stage": "completed" if not upload_completed else "uploaded",
            "percent": 100,
            "bytes": int(result["size_bytes"]),
        }
        await self._redis.set_json(f"progress:{job_id}", progress, ttl_seconds=3600)
        await self._publish_progress(
            job_id,
            stage=str(progress["stage"]),
            percent=100,
            bytes_transferred=int(progress["bytes"]),
        )
        return True

    async def _complete_download_locked(
        self,
        session: Any,
        job: Job,
        result: dict[str, Any],
    ) -> bool:
        now = datetime.now(UTC)
        actual_bytes = int(result["size_bytes"])
        scan_status = str(result.get("scan_status", "clean"))
        invalid_scan = scan_status not in {"clean", "skipped"} or (
            job.policy_snapshot.get("scan_required") and scan_status != "clean"
        )
        if invalid_scan:
            await self._fail_locked(session, job, "scan_not_clean", actual_bytes)
            return True
        for target in ("scanning", "processing", "generating_link", "completed"):
            previous = job.status
            job.status = target
            session.add(
                JobEvent(
                    job_id=job.id,
                    event_type=f"state.{target}",
                    from_status=previous,
                    to_status=target,
                    actor_type="worker",
                    actor_id=job.assigned_instance_id,
                    details={},
                )
            )
            await session.flush()
        expires = now + timedelta(seconds=int(job.policy_snapshot["retention_seconds"]))
        file = File(
            owner_user_id=job.user_id,
            created_by_job_id=job.id,
            source_type=job.source,
            status="available",
            storage_key=str(result["storage_key"]),
            original_filename=str(result["filename"]),
            safe_display_filename=str(result["filename"]),
            size_bytes=actual_bytes,
            sha256=bytes.fromhex(str(result["sha256"])),
            detected_mime=str(result.get("detected_mime", "application/octet-stream")),
            reported_mime=job.payload.get("mime_type"),
            scan_status=scan_status,
            media_metadata={},
            direct_play_compatible=False,
            retention_seconds=int(job.policy_snapshot["retention_seconds"]),
            expires_at=expires,
        )
        session.add(file)
        await session.flush()
        session.add(
            FileReference(
                user_id=job.user_id,
                file_id=file.id,
                source_job_id=job.id,
                display_filename=file.safe_display_filename,
                expires_at=expires,
                is_owner=True,
            )
        )
        job.result = {"file_id": str(file.id), "size_bytes": actual_bytes}
        job.progress_percent = 100
        job.progress_stage = "completed"
        job.finished_at = now
        attempt = await session.scalar(
            select(JobAttempt).where(
                JobAttempt.job_id == job.id,
                JobAttempt.attempt_number == job.attempt_count,
            )
        )
        if attempt is not None:
            attempt.status = "completed"
            attempt.finished_at = now
        await self._quota.reconcile(session, job=job, actual_bytes=actual_bytes, success=True)
        await self._schedule_telegram_upload(session, job, file)
        await self._schedule_media_processing(session, job, file)
        await session.flush()
        return False

    @staticmethod
    async def _schedule_media_processing(session: Any, parent: Job, file: File) -> None:
        if not file.detected_mime.startswith(("audio/", "video/")):
            return
        idempotency_key = f"media-process:{file.id}"
        existing = await session.scalar(select(Job.id).where(Job.idempotency_key == idempotency_key))
        if existing is not None:
            return
        media_job = Job(
            user_id=parent.user_id,
            source="internal",
            job_type="media_process",
            status="queued",
            queue_class=parent.queue_class,
            base_priority=parent.base_priority,
            effective_priority=parent.effective_priority,
            priority_snapshot={**parent.priority_snapshot, "parent_job_id": str(parent.id)},
            policy_snapshot=dict(parent.policy_snapshot),
            payload={
                "parent_job_id": str(parent.id),
                "file_id": str(file.id),
                "storage_key": file.storage_key,
                "filename": file.safe_display_filename,
                "size_bytes": file.size_bytes,
                "detected_mime": file.detected_mime,
            },
            result={},
            idempotency_key=idempotency_key,
            queued_at=datetime.now(UTC),
            total_bytes=file.size_bytes,
        )
        session.add(media_job)
        await session.flush()
        session.add(
            JobEvent(
                job_id=media_job.id,
                event_type="media_processing_scheduled",
                from_status=None,
                to_status="queued",
                actor_type="system",
                actor_id=None,
                details={"parent_job_id": str(parent.id), "file_id": str(file.id)},
            )
        )

    @staticmethod
    async def _complete_media_locked(
        session: Any,
        job: Job,
        result: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        file_id = UUID(str(job.payload["file_id"]))
        file = await session.scalar(select(File).where(File.id == file_id).with_for_update())
        if file is None or file.status != "available":
            raise ValueError("media source file is unavailable")
        if int(result["size_bytes"]) != file.size_bytes:
            raise ValueError("media result source size does not match")
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("media result metadata is invalid")
        file.media_metadata = metadata
        file.direct_play_compatible = bool(result["direct_play_compatible"])
        for value in result.get("variants", []):
            variant = MediaVariant(
                file_id=file.id,
                job_id=job.id,
                kind=str(value["kind"]),
                quality=str(value["quality"]),
                status="ready",
                storage_key=str(value["storage_key"]),
                mime_type=str(value["mime_type"]),
                size_bytes=int(value["size_bytes"]),
                metadata_json=dict(value.get("metadata", {})),
                expires_at=file.expires_at,
            )
            session.add(variant)
            await session.flush()
            for segment in value.get("segments", []):
                session.add(
                    MediaSegment(
                        variant_id=variant.id,
                        sequence_number=int(segment["sequence_number"]),
                        storage_key=str(segment["storage_key"]),
                        size_bytes=int(segment["size_bytes"]),
                        duration_ms=int(segment["duration_ms"]),
                        expires_at=file.expires_at,
                    )
                )
        previous = job.status
        job.status = "generating_link"
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="media_variants_persisted",
                from_status=previous,
                to_status="generating_link",
                actor_type="worker",
                actor_id=job.assigned_instance_id,
                details={"variant_count": len(result.get("variants", []))},
            )
        )
        await session.flush()
        job.status = "completed"
        job.result = {
            "file_id": str(file.id),
            "variant_count": len(result.get("variants", [])),
            "direct_play_compatible": file.direct_play_compatible,
        }
        job.progress_stage = "media_ready"
        job.progress_percent = 100
        job.bytes_transferred = file.size_bytes
        job.finished_at = now
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="media_processing_completed",
                from_status="generating_link",
                to_status="completed",
                actor_type="worker",
                actor_id=job.assigned_instance_id,
                details={},
            )
        )
        attempt = await session.scalar(
            select(JobAttempt).where(
                JobAttempt.job_id == job.id,
                JobAttempt.attempt_number == job.attempt_count,
            )
        )
        if attempt is not None:
            attempt.status = "completed"
            attempt.finished_at = now
        await session.flush()

    @staticmethod
    async def _schedule_telegram_upload(session: Any, parent: Job, file: File) -> None:
        chat_id = parent.payload.get("progress_chat_id")
        upload_limit = int(parent.policy_snapshot.get("telegram_upload_limit", 0))
        if parent.source != "external_url" or not isinstance(chat_id, int):
            return
        if upload_limit <= 0 or file.size_bytes > upload_limit:
            return
        idempotency_key = f"telegram-upload:{parent.id}"
        existing = await session.scalar(select(Job.id).where(Job.idempotency_key == idempotency_key))
        if existing is not None:
            return
        upload = Job(
            user_id=parent.user_id,
            source="internal",
            job_type="telegram_upload",
            status="queued",
            queue_class=parent.queue_class,
            base_priority=parent.base_priority,
            effective_priority=parent.effective_priority,
            priority_snapshot={**parent.priority_snapshot, "parent_job_id": str(parent.id)},
            policy_snapshot=dict(parent.policy_snapshot),
            payload={
                "parent_job_id": str(parent.id),
                "file_id": str(file.id),
                "storage_key": file.storage_key,
                "filename": file.safe_display_filename,
                "size_bytes": file.size_bytes,
                "chat_id": chat_id,
                "progress_message_id": parent.payload.get("progress_message_id"),
            },
            result={},
            idempotency_key=idempotency_key,
            queued_at=datetime.now(UTC),
            total_bytes=file.size_bytes,
        )
        session.add(upload)
        await session.flush()
        session.add(
            JobEvent(
                job_id=upload.id,
                event_type="telegram_upload_scheduled",
                from_status=None,
                to_status="queued",
                actor_type="system",
                actor_id=None,
                details={"parent_job_id": str(parent.id), "file_id": str(file.id)},
            )
        )

    @staticmethod
    async def _complete_upload_locked(
        session: Any,
        job: Job,
        result: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        previous = job.status
        job.status = "completed"
        job.result = {
            "telegram_message_id": int(result["telegram_message_id"]),
            "telegram_file_id": str(result["telegram_file_id"]),
            "size_bytes": int(result["size_bytes"]),
        }
        job.progress_stage = "uploaded"
        job.progress_percent = 100
        job.bytes_transferred = int(result["size_bytes"])
        job.finished_at = now
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="telegram_upload_completed",
                from_status=previous,
                to_status="completed",
                actor_type="worker",
                actor_id=job.assigned_instance_id,
                details={"telegram_message_id": int(result["telegram_message_id"])},
            )
        )
        attempt = await session.scalar(
            select(JobAttempt).where(
                JobAttempt.job_id == job.id,
                JobAttempt.attempt_number == job.attempt_count,
            )
        )
        if attempt is not None:
            attempt.status = "completed"
            attempt.finished_at = now
        await session.flush()

    async def fail(
        self,
        *,
        job_id: UUID,
        generation: int,
        lease: str,
        error_code: str,
        actual_bytes: int,
        stream: str,
        group: str,
        message_id: str,
        expected_job_type: str | None = None,
    ) -> bool:
        async with self._database.transaction() as session:
            job = await self._validated_job(
                session, job_id, generation, lease, expected_job_type=expected_job_type
            )
            if job is None:
                return False
            if not await self._transport_matches(
                session, job, generation, stream, group, message_id
            ):
                return False
            await self._fail_locked(session, job, error_code[:96], actual_bytes)
        await self._redis.client.xack(stream, group, message_id)
        await self._publish_progress(
            job_id,
            stage="failed",
            percent=0,
            bytes_transferred=actual_bytes,
            error_code=error_code,
        )
        return True

    async def _publish_progress(
        self,
        job_id: UUID,
        *,
        stage: str,
        percent: int,
        bytes_transferred: int,
        error_code: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "job_id": str(job_id),
            "stage": stage,
            "percent": max(0, min(100, percent)),
            "bytes": max(0, bytes_transferred),
        }
        if error_code:
            payload["error_code"] = error_code
        await self._redis.client.xadd(
            self._redis.key("stream", "job-progress"),
            {"payload": json.dumps(payload, separators=(",", ":"), sort_keys=True)},
            maxlen=100_000,
            approximate=True,
        )

    async def _fail_locked(
        self,
        session: Any,
        job: Job,
        error_code: str,
        actual_bytes: int,
    ) -> None:
        previous = job.status
        job.status = "failed"
        job.last_error_code = error_code
        job.bytes_transferred = max(job.bytes_transferred, actual_bytes)
        job.finished_at = datetime.now(UTC)
        attempt = await session.scalar(
            select(JobAttempt).where(
                JobAttempt.job_id == job.id,
                JobAttempt.attempt_number == job.attempt_count,
            )
        )
        if attempt is not None:
            attempt.status = "failed"
            attempt.error_code = error_code
            attempt.finished_at = job.finished_at
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="failed",
                from_status=previous,
                to_status="failed",
                actor_type="worker",
                actor_id=job.assigned_instance_id,
                details={"error_code": error_code},
            )
        )
        await self._quota.reconcile(session, job=job, actual_bytes=actual_bytes, success=False)
        await session.flush()

    @staticmethod
    async def _validated_job(
        session: Any,
        job_id: UUID,
        generation: int,
        lease: str,
        expected_job_type: str | None = None,
    ) -> Job | None:
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        digest = hashlib.sha256(lease.encode("ascii")).digest()
        if (
            job is None
            or job.dispatch_generation != generation
            or job.lease_token_hash is None
            or not hmac.compare_digest(job.lease_token_hash, digest)
            or job.status not in set(RUNNING_STATE.values())
            or job.lease_expires_at is None
            or job.lease_expires_at <= datetime.now(UTC)
            or (expected_job_type is not None and job.job_type != expected_job_type)
        ):
            return None
        return job

    async def _transport_matches(
        self,
        session: Any,
        job: Job,
        generation: int,
        stream: str,
        group: str,
        message_id: str,
    ) -> bool:
        expected_name = f"jobs:{job.job_type}:{job.queue_class}"
        if not (
            hmac.compare_digest(group, f"workers:{job.job_type}")
            and hmac.compare_digest(stream, self._redis.key("stream", expected_name))
        ):
            return False
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_type == "job",
                OutboxEvent.aggregate_id == job.id,
                OutboxEvent.event_type == "job.dispatched",
                OutboxEvent.stream_name == expected_name,
                OutboxEvent.redis_message_id == message_id,
                OutboxEvent.state == "published",
            )
        )
        return bool(event is not None and int(event.payload.get("generation", -1)) == generation)
