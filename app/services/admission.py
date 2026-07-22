"""Atomic user admission: policy snapshot, job, quota reservations, outbox."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AdmissionDenied
from app.core.settings import SettingsService
from app.db.models.identity import User
from app.db.models.jobs import Job, JobEvent, OutboxEvent, TelegramApiCapability
from app.services.quota import EffectivePlan, QuotaService


class AdmissionService:
    def __init__(self, settings: SettingsService, quota: QuotaService) -> None:
        self._settings = settings
        self._quota = quota

    async def create_job(
        self,
        session: AsyncSession,
        *,
        user: User,
        source: str,
        job_type: str,
        payload: dict[str, Any],
        estimated_bytes: int,
        idempotency_key: str,
    ) -> tuple[Job, int]:
        existing = await session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing is not None:
            position = await self.queue_position(session, existing)
            return existing, position
        snapshot = await self._settings.get_snapshot(session)
        if snapshot.values.get("system.maintenance") or not snapshot.values.get(
            "admission.enabled",
            True,
        ):
            raise AdmissionDenied("new job admission is disabled")
        hard_max = int(snapshot.values["files.max_size"])
        if estimated_bytes <= 0 or estimated_bytes > hard_max:
            raise AdmissionDenied("file exceeds the system hard limit", context={"limit": hard_max})
        plan = await self._quota.effective_plan(session, user)
        if estimated_bytes > plan.max_file_size:
            raise AdmissionDenied(
                "file exceeds the active plan limit",
                context={"limit": plan.max_file_size},
            )
        if source == "external_url" and not plan.external_url_enabled:
            raise AdmissionDenied("external URL intake is disabled for this plan")
        now = datetime.now(UTC)
        queue_class = "vip" if plan.queue_priority >= 100 else "normal"
        policy_snapshot = await self._policy_snapshot(session, plan, snapshot.values)
        job = Job(
            user_id=user.id,
            source=source,
            job_type=job_type,
            status="queued",
            queue_class=queue_class,
            base_priority=plan.queue_priority,
            effective_priority=plan.queue_priority,
            priority_snapshot={"plan": plan.code, "base": plan.queue_priority},
            policy_snapshot=policy_snapshot,
            payload=payload,
            result={},
            idempotency_key=idempotency_key,
            queued_at=now,
            total_bytes=estimated_bytes if payload.get("size_known", True) else None,
        )
        session.add(job)
        await session.flush()
        await self._quota.reserve(
            session,
            user=user,
            job=job,
            plan=plan,
            estimated_bytes=estimated_bytes,
            now=now,
        )
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="admitted",
                from_status=None,
                to_status="queued",
                actor_type="user",
                actor_id=user.id,
                details={"source": source, "queue_class": queue_class},
            )
        )
        session.add(
            OutboxEvent(
                aggregate_type="job",
                aggregate_id=job.id,
                event_type="job.admitted",
                stream_name="job-admission-events",
                payload={"job_id": str(job.id), "job_type": job_type},
                deduplication_key=f"job:{job.id}:admitted",
                available_at=now,
            )
        )
        await session.flush()
        return job, await self.queue_position(session, job)

    @staticmethod
    async def _policy_snapshot(
        session: AsyncSession,
        plan: EffectivePlan,
        settings: Any,
    ) -> dict[str, Any]:
        telegram_mode = settings["telegram.api_mode"]
        upload_limit_key = (
            "telegram.local_upload_limit"
            if telegram_mode == "local"
            else "telegram.cloud_upload_limit"
        )
        configured_limit = int(settings[upload_limit_key])
        capability = await session.scalar(
            select(TelegramApiCapability)
            .where(
                TelegramApiCapability.api_mode == telegram_mode,
                TelegramApiCapability.is_active.is_(True),
            )
            .order_by(TelegramApiCapability.verified_at.desc())
        )
        upload_limit = (
            min(configured_limit, capability.upload_limit_bytes)
            if capability is not None
            else configured_limit
        )
        return {
            "plan": plan.code,
            "max_file_size": min(plan.max_file_size, int(settings["files.max_size"])),
            "retention_seconds": plan.retention_seconds,
            "scan_required": bool(settings["security.scan_required"]),
            "telegram_api_mode": telegram_mode,
            "telegram_upload_limit": upload_limit,
            "telegram_capability_source": (
                capability.verification_source if capability is not None else "configured_default"
            ),
            "captured_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    async def queue_position(session: AsyncSession, job: Job) -> int:
        if job.status != "queued" or job.queued_at is None:
            return 0
        ahead = int(
            await session.scalar(
                select(func.count()).select_from(Job).where(
                    Job.status == "queued",
                    Job.job_type == job.job_type,
                    (Job.effective_priority > job.effective_priority)
                    | (
                        (Job.effective_priority == job.effective_priority)
                        & (Job.queued_at < job.queued_at)
                    ),
                )
            )
            or 0
        )
        return ahead + 1
