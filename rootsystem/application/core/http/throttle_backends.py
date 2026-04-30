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
        """Return timestamps within the window for the given key.

        Read-only — does not mutate state. Used for inspection in tests and
        for the legacy non-atomic path. The throttle decorator itself goes
        through ``check_and_add`` so the count and the record are observed
        as a single transaction.
        """

    @abstractmethod
    async def add_timestamp(self, key: str, now: float, window: int) -> None:
        """Record a new request timestamp.

        Kept for backwards compatibility and direct test use. The throttle
        decorator MUST use ``check_and_add`` instead — splitting count
        and add into two calls is a TOCTOU race that lets concurrent
        callers all read the same baseline and bypass the limit.
        """

    @abstractmethod
    async def check_and_add(
        self,
        key: str,
        now: float,
        window: int,
        max_requests: int,
    ) -> tuple[bool, int, float | None]:
        """Atomically count requests in the window and either record this one
        or refuse it.

        Returns ``(allowed, count_after_add_if_allowed_else_existing_count,
        oldest_in_window)``. ``oldest_in_window`` is the smallest timestamp
        currently in the window (used to compute ``X-RateLimit-Reset``); it
        is ``None`` when the window is empty.

        Memory backend serializes this with the global lock. Redis backend
        wraps ZREMRANGEBYSCORE + ZCARD + ZADD in a single Lua EVAL — Redis
        runs scripts on a single thread, so the entire decision is observed
        atomically across workers.
        """

    @abstractmethod
    async def cleanup(self, key: str, window: int) -> None:
        """Remove expired timestamps for the given key."""

    async def verify(self) -> None:
        """Probe backend connectivity. Default: no-op (always reachable).

        Backends that depend on a network service (e.g. Redis) override this
        to fail fast at startup rather than at first request.
        """
        return None


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

    async def check_and_add(
        self,
        key: str,
        now: float,
        window: int,
        max_requests: int,
    ) -> tuple[bool, int, float | None]:
        async with self._lock:
            cutoff = now - window
            timestamps = [t for t in self._store.get(key, []) if t > cutoff]
            oldest = timestamps[0] if timestamps else None

            if len(timestamps) >= max_requests:
                # Persist the cleaned list so we don't keep re-filtering expired entries.
                self._store[key] = timestamps
                return False, len(timestamps), oldest

            timestamps.append(now)
            self._store[key] = timestamps

            # Lazy global cleanup
            self._request_count += 1
            if self._request_count % self._CLEANUP_EVERY == 0:
                self._global_cleanup_locked(window)

            return True, len(timestamps), oldest

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


# Atomic check-and-add for Redis: prune expired, count, decide, conditionally
# add. Lua scripts run on a single Redis thread, so the entire sequence is
# observed atomically — no other client can see a partial state. Without
# this the ZRANGEBYSCORE + ZADD pair has a TOCTOU window that lets
# concurrent callers all read the same baseline and bypass the limit.
_CHECK_AND_ADD_LUA = """
local cutoff = tonumber(ARGV[1])
local now_member = ARGV[2]
local now_score = tonumber(ARGV[3])
local max_requests = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)

local count = redis.call('ZCARD', KEYS[1])

local oldest_arr = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local oldest = ''
if #oldest_arr >= 2 then
    oldest = oldest_arr[2]
end

if count >= max_requests then
    return {0, count, oldest}
end

redis.call('ZADD', KEYS[1], now_score, now_member)
redis.call('EXPIRE', KEYS[1], ttl)
return {1, count + 1, oldest}
"""


class RedisBackend(ThrottleBackend):
    """Redis-backed rate limiting using sorted sets."""

    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as aioredis

        self._redis_url = redis_url
        self._redis = aioredis.from_url(redis_url, socket_connect_timeout=5)
        self._prefix = 'throttle:'

    async def verify(self) -> None:
        """Ping Redis to fail fast at startup if unreachable."""
        try:
            # redis-py's ping() stub unions Awaitable[bool] | bool for the sync/async overload.
            # On the asyncio client we always get a coroutine; cast narrows it for mypy.
            from collections.abc import Awaitable
            from typing import cast

            await cast(Awaitable[bool], self._redis.ping())
        except Exception as exc:
            raise RuntimeError(
                f'THROTTLE_BACKEND=redis but Redis at {self._redis_url} is not reachable: {exc}'
            ) from exc

    async def get_timestamps(self, key: str, window: int) -> list[float]:
        cutoff = time.time() - window
        rkey = f'{self._prefix}{key}'
        values = await self._redis.zrangebyscore(rkey, cutoff, '+inf')
        return [float(v) for v in values]

    async def add_timestamp(self, key: str, now: float, window: int) -> None:
        rkey = f'{self._prefix}{key}'
        pipe = self._redis.pipeline()
        pipe.zadd(rkey, {str(now): now})
        pipe.zremrangebyscore(rkey, '-inf', now - window)
        pipe.expire(rkey, window + 60)
        await pipe.execute()

    async def check_and_add(
        self,
        key: str,
        now: float,
        window: int,
        max_requests: int,
    ) -> tuple[bool, int, float | None]:
        from collections.abc import Awaitable
        from typing import Any, cast

        rkey = f'{self._prefix}{key}'
        cutoff = now - window
        ttl = window + 60
        # redis-py's eval() stub unions Awaitable[Any] | Any across the
        # sync/async overload; on the asyncio client it is always a
        # coroutine. Cast narrows it for mypy.
        result = await cast(
            Awaitable[Any],
            self._redis.eval(
                _CHECK_AND_ADD_LUA,
                1,
                rkey,
                cutoff,
                str(now),
                now,
                max_requests,
                ttl,
            ),
        )
        allowed = bool(int(result[0]))
        count = int(result[1])
        oldest_raw = result[2]
        oldest: float | None
        if oldest_raw in (b'', '', None):
            oldest = None
        else:
            s = oldest_raw.decode() if isinstance(oldest_raw, bytes) else oldest_raw
            oldest = float(s)
        return allowed, count, oldest

    async def cleanup(self, key: str, window: int) -> None:
        cutoff = time.time() - window
        rkey = f'{self._prefix}{key}'
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
        _backend = RedisBackend(redis_url)
    else:
        _backend = MemoryBackend()

    return _backend


def reset_backend() -> None:
    """Reset the singleton (for tests)."""
    global _backend
    _backend = None
