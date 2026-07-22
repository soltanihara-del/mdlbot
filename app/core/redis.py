"""Redis cache/invalidation lifecycle; never an authorization source of truth."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.core.config import RuntimeSettings
from app.core.errors import ConfigurationError, DependencyUnavailable


class RedisManager:
    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._client: Redis | None = None

    @property
    def started(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> Redis:
        return self._require_client()

    def key(self, *parts: str) -> str:
        normalized = [part.strip(":") for part in parts]
        return ":".join((self._settings.redis_key_prefix, *normalized))

    async def start(self) -> None:
        if self.started:
            return
        if self._settings.redis_url is None:
            raise ConfigurationError("REDIS_URL is required")
        self._client = Redis.from_url(
            self._settings.redis_url.get_secret_value(),
            decode_responses=True,
            encoding="utf-8",
            max_connections=self._settings.redis_max_connections,
            socket_connect_timeout=self._settings.redis_socket_timeout_seconds,
            socket_timeout=self._settings.redis_socket_timeout_seconds,
            protocol=2,
            health_check_interval=30,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    def _require_client(self) -> Redis:
        if self._client is None:
            raise ConfigurationError("Redis has not been started")
        return self._client

    async def healthcheck(self) -> bool:
        try:
            return bool(await self._require_client().ping())
        except Exception as exc:
            raise DependencyUnavailable("Redis healthcheck failed") from exc

    async def get_json(self, key: str) -> Any | None:
        value = await self._require_client().get(self.key("cache", key))
        return None if value is None else json.loads(value)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        await self._require_client().set(self.key("cache", key), payload, ex=ttl_seconds)

    async def delete_cache(self, key: str) -> None:
        await self._require_client().delete(self.key("cache", key))

    async def get_generation(self, namespace: str) -> int:
        value = await self._require_client().get(self.key("generation", namespace))
        return int(value or 0)

    async def invalidate(self, namespace: str, *, item_key: str | None = None) -> int:
        """Advance a recovery generation and publish a best-effort notification."""

        client = self._require_client()
        generation = int(await client.incr(self.key("generation", namespace)))
        payload = json.dumps(
            {"namespace": namespace, "generation": generation, "key": item_key},
            separators=(",", ":"),
            sort_keys=True,
        )
        await client.publish(self.key("invalidation", namespace), payload)
        if item_key is not None:
            await self.delete_cache(f"{namespace}:{item_key}")
        return generation
