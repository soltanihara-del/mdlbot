"""Explicit async PostgreSQL lifecycle and transaction boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError, DependencyUnavailable


class Database:
    """Own one process-local engine; callers own every commit boundary."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._sessions: async_sessionmaker[AsyncSession] | None = None

    @property
    def started(self) -> bool:
        return self._engine is not None

    async def start(self) -> None:
        if self.started:
            return
        if self._settings.database_url is None:
            raise ConfigurationError("DATABASE_URL is required")
        url = self._settings.database_url.get_secret_value()
        statement_timeout = self._settings.database_statement_timeout_ms
        self._engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=self._settings.database_pool_size,
            max_overflow=self._settings.database_max_overflow,
            pool_timeout=self._settings.database_pool_timeout_seconds,
            connect_args={"options": f"-c statement_timeout={statement_timeout}"},
        )
        self._sessions = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._sessions = None

    async def healthcheck(self) -> bool:
        if self._engine is None:
            return False
        try:
            async with self._engine.connect() as connection:
                return (await connection.scalar(text("SELECT 1"))) == 1
        except Exception as exc:
            raise DependencyUnavailable("PostgreSQL healthcheck failed") from exc

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session without silently committing application work."""

        if self._sessions is None:
            raise ConfigurationError("database has not been started")
        async with self._sessions() as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Yield an atomic transaction and commit only at this declared boundary."""

        async with self.session() as session:
            async with session.begin():
                yield session
