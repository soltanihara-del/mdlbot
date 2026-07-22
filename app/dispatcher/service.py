"""PostgreSQL queue ordering and Redis Streams transport publication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import RedisManager
from app.db.models.jobs import Job, JobEvent, OutboxEvent


def choose_lane(
    *,
    oldest_normal: datetime | None,
    now: datetime,
    consecutive_vip: int,
    max_normal_wait_seconds: int,
    max_consecutive_vip: int,
) -> str:
    """Choose the first lane while guaranteeing bounded normal-queue starvation."""

    normal_wait_exceeded = bool(
        oldest_normal is not None
        and now - oldest_normal >= timedelta(seconds=max_normal_wait_seconds)
    )
    return (
        "normal"
        if normal_wait_exceeded or consecutive_vip >= max_consecutive_vip
        else "vip"
    )


class DispatcherService:
    def __init__(self) -> None:
        self._consecutive_vip: dict[str, int] = {}

    async def dispatch_one(
        self,
        session: AsyncSession,
        *,
        job_type: str,
        aging_step_seconds: int,
        max_normal_wait_seconds: int,
        max_consecutive_vip: int,
        lease_seconds: int = 120,
    ) -> Job | None:
        now = datetime.now(UTC)
        oldest_normal = await session.scalar(
            select(func.min(Job.queued_at)).where(
                Job.status == "queued",
                Job.attempt_count < Job.max_attempts,
                Job.job_type == job_type,
                Job.queue_class == "normal",
            )
        )
        preferred = choose_lane(
            oldest_normal=oldest_normal,
            now=now,
            consecutive_vip=self._consecutive_vip.get(job_type, 0),
            max_normal_wait_seconds=max_normal_wait_seconds,
            max_consecutive_vip=max_consecutive_vip,
        )
        job = await self._select_lane(
            session,
            job_type=job_type,
            queue_class=preferred,
            now=now,
            aging_step_seconds=aging_step_seconds,
        )
        if job is None:
            alternate = "vip" if preferred == "normal" else "normal"
            job = await self._select_lane(
                session,
                job_type=job_type,
                queue_class=alternate,
                now=now,
                aging_step_seconds=aging_step_seconds,
            )
        if job is None:
            return None
        waited_seconds = max(0, int((now - (job.queued_at or now)).total_seconds()))
        aging_bonus = waited_seconds // max(1, aging_step_seconds)
        job.effective_priority = job.base_priority + aging_bonus
        job.status = "dispatched"
        job.dispatch_generation += 1
        job.dispatched_at = now
        raw_lease = secrets.token_urlsafe(32)
        job.lease_token_hash = hashlib.sha256(raw_lease.encode("ascii")).digest()
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        if job.queue_class == "vip":
            self._consecutive_vip[job_type] = self._consecutive_vip.get(job_type, 0) + 1
        else:
            self._consecutive_vip[job_type] = 0
        stream = f"jobs:{job.job_type}:{job.queue_class}"
        session.add(
            JobEvent(
                job_id=job.id,
                event_type="dispatched",
                from_status="queued",
                to_status="dispatched",
                actor_type="dispatcher",
                details={
                    "generation": job.dispatch_generation,
                    "waited_seconds": waited_seconds,
                    "aging_bonus": aging_bonus,
                    "queue_class": job.queue_class,
                },
            )
        )
        session.add(
            OutboxEvent(
                aggregate_type="job",
                aggregate_id=job.id,
                event_type="job.dispatched",
                stream_name=stream,
                payload={
                    "job_id": str(job.id),
                    "generation": job.dispatch_generation,
                    "lease": raw_lease,
                    "job_type": job.job_type,
                    "queue_class": job.queue_class,
                },
                deduplication_key=f"job:{job.id}:dispatch:{job.dispatch_generation}",
                available_at=now,
            )
        )
        await session.flush()
        return job

    @staticmethod
    async def _select_lane(
        session: AsyncSession,
        *,
        job_type: str,
        queue_class: str,
        now: datetime,
        aging_step_seconds: int,
    ) -> Job | None:
        waited = func.extract("epoch", now - Job.queued_at)
        score = Job.base_priority + func.floor(waited / max(1, aging_step_seconds))
        return await session.scalar(
            select(Job)
            .where(
                Job.status == "queued",
                Job.job_type == job_type,
                Job.queue_class == queue_class,
            )
            .order_by(score.desc(), Job.queued_at.asc(), Job.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )


class OutboxPublisher:
    def __init__(self, redis: RedisManager) -> None:
        self._redis = redis

    async def publish_batch(self, session: AsyncSession, *, limit: int = 100) -> int:
        now = datetime.now(UTC)
        events = list(
            (
                await session.scalars(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.state.in_(("pending", "failed")),
                        OutboxEvent.available_at <= now,
                        OutboxEvent.attempt_count < 20,
                    )
                    .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        published = 0
        for event in events:
            try:
                message_id = await self._redis.client.xadd(
                    self._redis.key("stream", event.stream_name),
                    {
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "payload": json.dumps(event.payload, separators=(",", ":"), sort_keys=True),
                    },
                    maxlen=100_000,
                    approximate=True,
                )
                event.state = "published"
                event.published_at = now
                event.redis_message_id = str(message_id)
                event.last_error = None
                if event.event_type == "job.dispatched":
                    event.payload = {
                        "job_id": event.payload["job_id"],
                        "generation": event.payload["generation"],
                        "published": True,
                    }
                published += 1
            except Exception as exc:
                event.state = "failed"
                event.attempt_count += 1
                event.last_error = type(exc).__name__
                event.available_at = now + timedelta(seconds=min(300, 2 ** min(event.attempt_count, 8)))
        await session.flush()
        return published
