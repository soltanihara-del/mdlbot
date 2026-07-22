"""Small Stage 5 query layer; transaction ownership remains in middleware."""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import User as TelegramUser
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.admin import Admin
from app.db.models.files import FileReference
from app.db.models.identity import User, UserSubscription
from app.db.models.jobs import Job


class UserRepository:
    async def get_or_create(self, session: AsyncSession, telegram: TelegramUser) -> User:
        user = await session.scalar(
            select(User).where(User.telegram_user_id == telegram.id).with_for_update()
        )
        if user is None:
            suggested = telegram.language_code if telegram.language_code in {"fa", "en"} else "fa"
            user = User(
                telegram_user_id=telegram.id,
                username=telegram.username,
                first_name=telegram.first_name,
                last_name=telegram.last_name,
                language_code=suggested,
                status="active",
            )
            session.add(user)
            await session.flush()
        else:
            user.username = telegram.username
            user.first_name = telegram.first_name
            user.last_name = telegram.last_name
        if user.language_selected_at is not None:
            user.last_seen_at = datetime.now(UTC)
        return user

    async def select_language(self, session: AsyncSession, user: User, locale: str) -> None:
        if locale not in {"fa", "en"}:
            raise ValueError("locale must be fa or en")
        user.language_code = locale
        user.language_selected_at = datetime.now(UTC)
        user.last_seen_at = user.language_selected_at
        await session.flush()

    async def recent_files(
        self,
        session: AsyncSession,
        user: User,
        *,
        limit: int = 10,
    ) -> list[FileReference]:
        return list(
            (
                await session.scalars(
                    select(FileReference)
                    .where(FileReference.user_id == user.id, FileReference.deleted_at.is_(None))
                    .order_by(FileReference.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )

    async def active_subscription(
        self,
        session: AsyncSession,
        user: User,
    ) -> UserSubscription | None:
        now = datetime.now(UTC)
        return await session.scalar(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.status == "active",
                UserSubscription.starts_at <= now,
                (UserSubscription.ends_at.is_(None) | (UserSubscription.ends_at > now)),
            )
        )


class AdminRepository:
    async def for_user(self, session: AsyncSession, user: User) -> Admin | None:
        return await session.scalar(select(Admin).where(Admin.user_id == user.id))

    async def dashboard_counts(self, session: AsyncSession) -> dict[str, int]:
        user_count = int(await session.scalar(select(func.count()).select_from(User)) or 0)
        job_count = int(await session.scalar(select(func.count()).select_from(Job)) or 0)
        file_count = int(await session.scalar(select(func.count()).select_from(FileReference)) or 0)
        return {"users": user_count, "jobs": job_count, "files": file_count}
