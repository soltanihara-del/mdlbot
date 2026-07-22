"""Transactional multi-window quota reservation and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceeded
from app.db.models.identity import (
    QuotaBucket,
    QuotaReservation,
    SubscriptionPlan,
    UsageRecord,
    User,
    UserQuotaOverride,
    UserSubscription,
)
from app.db.models.jobs import Job, JobEvent


ACTIVE_JOB_STATES = {
    "pending", "quota_reserved", "queued", "dispatched", "downloading", "receiving",
    "scanning", "processing", "remuxing", "transcoding", "uploading", "generating_link",
}


@dataclass(frozen=True, slots=True)
class EffectivePlan:
    code: str
    max_file_size: int
    hourly_quota: int | None
    daily_quota: int | None
    weekly_quota: int | None
    storage_quota: int | None
    max_files_per_window: int | None
    concurrent_jobs: int
    queue_priority: int
    retention_seconds: int
    external_url_enabled: bool


@dataclass(frozen=True, slots=True)
class Window:
    kind: str
    start: datetime
    end: datetime


def quota_window(kind: str, now: datetime) -> Window:
    now = now.astimezone(UTC)
    if kind == "hourly":
        start = now.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
    elif kind == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif kind == "weekly":
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=7)
    elif kind == "lifetime":
        start = datetime(2000, 1, 1, tzinfo=UTC)
        end = datetime(9999, 1, 1, tzinfo=UTC)
    else:
        raise ValueError(f"unsupported quota window: {kind}")
    return Window(kind, start, end)


class QuotaService:
    async def touch(
        self,
        session: AsyncSession,
        *,
        job: Job,
        now: datetime | None = None,
    ) -> None:
        """Keep reservations alive only while a worker holds a valid durable lease."""

        now = now or datetime.now(UTC)
        reservations = list(
            (
                await session.scalars(
                    select(QuotaReservation)
                    .where(
                        QuotaReservation.job_id == job.id,
                        QuotaReservation.state == "active",
                    )
                    .with_for_update()
                )
            ).all()
        )
        for reservation in reservations:
            reservation.expires_at = now + timedelta(hours=4)

    async def reconcile_expired(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> int:
        """Finalize expired reservations and prevent unreserved stale jobs from running."""

        now = now or datetime.now(UTC)
        job_ids = list(
            (
                await session.scalars(
                    select(QuotaReservation.job_id)
                    .where(
                        QuotaReservation.state == "active",
                        QuotaReservation.expires_at <= now,
                    )
                    .order_by(QuotaReservation.expires_at)
                    .limit(limit)
                )
            ).all()
        )
        reconciled = 0
        for job_id in dict.fromkeys(job_ids):
            job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job is None:
                continue
            if job.status in ACTIVE_JOB_STATES and job.lease_expires_at is not None:
                if job.lease_expires_at > now:
                    await self.touch(session, job=job, now=now)
                    continue
            success = job.status == "completed"
            actual_bytes = int(job.result.get("size_bytes", job.bytes_transferred))
            if job.status == "queued":
                job.status = "expired"
                job.finished_at = now
                session.add(
                    JobEvent(
                        job_id=job.id,
                        event_type="quota_reservation_expired",
                        from_status="queued",
                        to_status="expired",
                        actor_type="scheduler",
                        details={},
                    )
                )
                await session.flush()
            elif job.status in ACTIVE_JOB_STATES:
                previous = job.status
                job.status = "failed"
                job.last_error_code = "quota_reservation_expired"
                job.finished_at = now
                session.add(
                    JobEvent(
                        job_id=job.id,
                        event_type="quota_reservation_expired",
                        from_status=previous,
                        to_status="failed",
                        actor_type="scheduler",
                        details={},
                    )
                )
                await session.flush()
                job.status = "dead_letter"
                await session.flush()
            await self.reconcile(
                session,
                job=job,
                actual_bytes=actual_bytes,
                success=success,
            )
            reconciled += 1
        return reconciled

    async def effective_plan(
        self,
        session: AsyncSession,
        user: User,
        *,
        now: datetime | None = None,
    ) -> EffectivePlan:
        now = now or datetime.now(UTC)
        plan = await session.scalar(
            select(SubscriptionPlan)
            .join(UserSubscription, UserSubscription.plan_id == SubscriptionPlan.id)
            .where(
                UserSubscription.user_id == user.id,
                UserSubscription.status == "active",
                UserSubscription.starts_at <= now,
                or_(UserSubscription.ends_at.is_(None), UserSubscription.ends_at > now),
                SubscriptionPlan.is_active.is_(True),
                SubscriptionPlan.deleted_at.is_(None),
            )
            .order_by(UserSubscription.starts_at.desc())
        )
        if plan is None:
            plan = await session.scalar(
                select(SubscriptionPlan).where(
                    SubscriptionPlan.code == "normal",
                    SubscriptionPlan.is_active.is_(True),
                    SubscriptionPlan.deleted_at.is_(None),
                )
            )
        if plan is None:
            raise QuotaExceeded("no active quota plan is configured")
        effective = EffectivePlan(
            code=plan.code,
            max_file_size=plan.max_file_size,
            hourly_quota=plan.hourly_quota,
            daily_quota=plan.daily_quota,
            weekly_quota=plan.weekly_quota,
            storage_quota=plan.storage_quota,
            max_files_per_window=plan.max_files_per_window,
            concurrent_jobs=plan.concurrent_jobs,
            queue_priority=plan.queue_priority,
            retention_seconds=plan.retention_seconds,
            external_url_enabled=plan.external_url_enabled,
        )
        override = await session.scalar(
            select(UserQuotaOverride)
            .where(
                UserQuotaOverride.user_id == user.id,
                or_(UserQuotaOverride.starts_at.is_(None), UserQuotaOverride.starts_at <= now),
                or_(UserQuotaOverride.ends_at.is_(None), UserQuotaOverride.ends_at > now),
            )
            .order_by(UserQuotaOverride.created_at.desc())
        )
        if override is not None:
            allowed = set(EffectivePlan.__dataclass_fields__) - {"code"}
            updates = {key: value for key, value in override.overrides.items() if key in allowed}
            effective = replace(effective, **updates)
        return effective

    async def reserve(
        self,
        session: AsyncSession,
        *,
        user: User,
        job: Job,
        plan: EffectivePlan,
        estimated_bytes: int,
        now: datetime | None = None,
    ) -> list[QuotaReservation]:
        now = now or datetime.now(UTC)
        if estimated_bytes <= 0 or estimated_bytes > plan.max_file_size:
            raise QuotaExceeded(
                "file size is outside plan bounds",
                context={"maximum": plan.max_file_size},
            )
        active_jobs = int(
            await session.scalar(
                select(func.count()).select_from(Job).where(
                    Job.user_id == user.id,
                    Job.status.in_(ACTIVE_JOB_STATES),
                    Job.id != job.id,
                )
            )
            or 0
        )
        if active_jobs >= plan.concurrent_jobs:
            raise QuotaExceeded(
                "concurrent job limit reached",
                context={"limit": plan.concurrent_jobs},
            )

        specifications: list[tuple[str, Window, int, int]] = []
        for kind, limit in (
            ("hourly", plan.hourly_quota),
            ("daily", plan.daily_quota),
            ("weekly", plan.weekly_quota),
        ):
            if limit is not None:
                specifications.append(("ingress_bytes", quota_window(kind, now), limit, estimated_bytes))
        if plan.storage_quota is not None:
            specifications.append(
                ("storage_bytes", quota_window("lifetime", now), plan.storage_quota, estimated_bytes)
            )
        if plan.max_files_per_window is not None:
            specifications.append(
                ("job_count", quota_window("daily", now), plan.max_files_per_window, 1)
            )
        specifications.sort(key=lambda item: (item[0], item[1].kind))

        reservations: list[QuotaReservation] = []
        for dimension, window, limit, amount in specifications:
            await session.execute(
                insert(QuotaBucket)
                .values(
                    id=uuid4(),
                    user_id=user.id,
                    dimension=dimension,
                    window_kind=window.kind,
                    window_start=window.start,
                    window_end=window.end,
                    quota_limit=limit,
                    committed_amount=0,
                    reserved_amount=0,
                    row_version=1,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        QuotaBucket.user_id,
                        QuotaBucket.dimension,
                        QuotaBucket.window_kind,
                        QuotaBucket.window_start,
                        QuotaBucket.window_end,
                    ]
                )
            )
            bucket = await session.scalar(
                select(QuotaBucket)
                .where(
                    QuotaBucket.user_id == user.id,
                    QuotaBucket.dimension == dimension,
                    QuotaBucket.window_kind == window.kind,
                    QuotaBucket.window_start == window.start,
                    QuotaBucket.window_end == window.end,
                )
                .with_for_update()
            )
            if bucket is None:
                raise QuotaExceeded("quota bucket could not be locked")
            used = bucket.committed_amount + bucket.reserved_amount
            if used + amount > limit:
                raise QuotaExceeded(
                    "quota window exhausted",
                    context={"dimension": dimension, "window": window.kind},
                )
            bucket.quota_limit = limit
            bucket.reserved_amount += amount
            bucket.row_version += 1
            reservation = QuotaReservation(
                user_id=user.id,
                job_id=job.id,
                quota_bucket_id=bucket.id,
                dimension=dimension,
                reserved_amount=amount,
                consumed_amount=0,
                state="active",
                expires_at=now + timedelta(hours=4),
            )
            session.add(reservation)
            reservations.append(reservation)
        await session.flush()
        return reservations

    async def reconcile(
        self,
        session: AsyncSession,
        *,
        job: Job,
        actual_bytes: int,
        success: bool,
    ) -> None:
        reservations = list(
            (
                await session.scalars(
                    select(QuotaReservation)
                    .where(
                        QuotaReservation.job_id == job.id,
                        QuotaReservation.state == "active",
                    )
                    .order_by(QuotaReservation.quota_bucket_id)
                    .with_for_update()
                )
            ).all()
        )
        for reservation in reservations:
            bucket = await session.scalar(
                select(QuotaBucket)
                .where(QuotaBucket.id == reservation.quota_bucket_id)
                .with_for_update()
            )
            if bucket is None:
                raise QuotaExceeded("reservation bucket is missing")
            if reservation.dimension == "job_count":
                consumed = 1 if success else 0
            elif reservation.dimension == "storage_bytes":
                consumed = actual_bytes if success else 0
            else:
                consumed = actual_bytes
            if consumed > reservation.reserved_amount:
                raise QuotaExceeded("actual usage exceeds reservation")
            bucket.reserved_amount -= reservation.reserved_amount
            bucket.committed_amount += consumed
            bucket.row_version += 1
            reservation.consumed_amount = consumed
            reservation.state = "committed" if consumed > 0 else "released"
            reservation.finalized_at = datetime.now(UTC)
            if consumed > 0:
                session.add(
                    UsageRecord(
                        user_id=job.user_id,
                        quota_bucket_id=bucket.id,
                        reservation_id=reservation.id,
                        job_id=job.id,
                        dimension=reservation.dimension,
                        direction="debit",
                        amount=consumed,
                        idempotency_key=f"job:{job.id}:{bucket.id}:commit",
                        metadata_json={"source": job.source},
                    )
                )
        await session.flush()

    async def top_up(
        self,
        session: AsyncSession,
        *,
        job: Job,
        required_bytes: int,
    ) -> None:
        if required_bytes <= 0:
            raise QuotaExceeded("quota top-up must be positive")
        reservations = list(
            (
                await session.scalars(
                    select(QuotaReservation)
                    .where(
                        QuotaReservation.job_id == job.id,
                        QuotaReservation.state == "active",
                        QuotaReservation.dimension.in_(("ingress_bytes", "storage_bytes")),
                    )
                    .order_by(QuotaReservation.quota_bucket_id)
                    .with_for_update()
                )
            ).all()
        )
        for reservation in reservations:
            if required_bytes <= reservation.reserved_amount:
                continue
            delta = required_bytes - reservation.reserved_amount
            bucket = await session.scalar(
                select(QuotaBucket).where(QuotaBucket.id == reservation.quota_bucket_id).with_for_update()
            )
            if bucket is None or (
                bucket.quota_limit is not None
                and bucket.committed_amount + bucket.reserved_amount + delta > bucket.quota_limit
            ):
                raise QuotaExceeded("quota top-up exceeds the active window")
            bucket.reserved_amount += delta
            bucket.row_version += 1
            reservation.reserved_amount = required_bytes
        job.total_bytes = required_bytes
        await session.flush()
