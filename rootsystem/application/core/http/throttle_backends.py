"""
Pluggable backends for rate limiting.

    from core.http.throttle_backends import get_backend, reset_backend

Default is MemoryBackend. Set settings.THROTTLE_BACKEND = 'redis' for Redis.
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from core.conf import config


class ThrottleBackend(ABC):
    """Interface for rate limiting storage."""

    @abstractmethod
    async def get_timestamps(self, key: str, window: int) -> list[float]:
        """Return timestamps within the window for the given key."""

    @abstractmethod
    async def add_timestamp(self, key: str, now: float, window: int) -> None:
        """Record a new request timestamp."""

    @abstractmethod
    async def cleanup(self, key: str, window: int) -> None:
        """Remove expired timestamps for the given key."""


class MemoryBackend(ThrottleBackend):
    """In-memory rate limiting (single process) with asyncio lock."""

    def __init__(self) -> None:
        self._store: dict[str, list[float]] = {}
        self._request_count: int = 0
        self._CLEANUP_EVERY: int = 100
        self._lock = asyncio.Lock()

    async def get_timestamps(self, key: str, window: int) -> list[float]:
        async with self._lock:
            cutoff = time.time() - window
            timestamps = self._store.get(key, [])
            return [t for t in timestamps if t > cutoff]

    async def add_timestamp(self, key: str, now: float, window: int) -> None:
        async with self._lock:
            cutoff = now - window
            timestamps = self._store.get(key, [])
            timestamps = [t for t in timestamps if t > cutoff]
            timestamps.append(now)
            self._store[key] = timestamps

            # Lazy cleanup
            self._request_count += 1
            if self._request_count % self._CLEANUP_EVERY == 0:
                self._global_cleanup_locked(window)

    async def cleanup(self, key: str, window: int) -> None:
        async with self._lock:
            cutoff = time.time() - window
            timestamps = self._store.get(key, [])
            self._store[key] = [t for t in timestamps if t > cutoff]

    def _global_cleanup_locked(self, window: int) -> None:
        """Remove keys whose timestamps are all expired. Must hold lock."""
        cutoff = time.time() - window
        expired = [k for k, ts in self._store.items() if not ts or ts[-1] < cutoff]
        for k in expired:
            del self._store[k]

    def clear(self) -> None:
        """Reset all stored data (for tests)."""
        self._store.clear()
        self._request_count = 0


class RedisBackend(ThrottleBackend):
    """Redis-backed rate limiting using sorted sets."""

    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(redis_url, socket_connect_timeout=5)
        self._prefix = 'throttle:'

    async def get_timestamps(self, key: str, window: int) -> list[float]:
        cutoff = time.time() - window
        rkey = f"{self._prefix}{key}"
        values = await self._redis.zrangebyscore(rkey, cutoff, '+inf')
        return [float(v) for v in values]

    async def add_timestamp(self, key: str, now: float, window: int) -> None:
        rkey = f"{self._prefix}{key}"
        pipe = self._redis.pipeline()
        pipe.zadd(rkey, {str(now): now})
        pipe.zremrangebyscore(rkey, '-inf', now - window)
        pipe.expire(rkey, window + 60)
        await pipe.execute()

    async def cleanup(self, key: str, window: int) -> None:
        cutoff = time.time() - window
        rkey = f"{self._prefix}{key}"
        await self._redis.zremrangebyscore(rkey, '-inf', cutoff)

    async def shutdown(self) -> None:
        """Close the Redis connection pool."""
        await self._redis.close()


_backend: ThrottleBackend | None = None


def get_backend() -> ThrottleBackend:
    """Get or create the singleton throttle backend."""
    global _backend
    if _backend is not None:
        return _backend

    backend_type = config.get('THROTTLE_BACKEND', 'memory').lower()

    if backend_type == 'redis':
        redis_url = config.get('REDIS_URL', 'redis://localhost:6379')
        try:
            _backend = RedisBackend(redis_url)
        except Exception:
            _backend = MemoryBackend()
    else:
        _backend = MemoryBackend()

    return _backend


def reset_backend() -> None:
    """Reset the singleton (for tests)."""
    global _backend
    _backend = None
