"""
Pluggable caching with TTL support.

Usage::

    from core.cache import cache_get, cache_set, cache_delete, cache_flush
    from core.cache import cache_response

    # Simple key-value
    await cache_set('user:1', user_data, ttl=300)
    data = await cache_get('user:1')
    await cache_delete('user:1')
    await cache_flush()

    # Response caching decorator (GET only)
    class ProductController:
        @cache_response(ttl=60)
        async def list(self, request):
            return JSONResponse(...)
"""

from __future__ import annotations

import asyncio
import base64
import collections
import inspect
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import wraps
from typing import Any

from core.conf import config

__all__ = [
    'CacheBackend',
    'MemoryCacheBackend',
    'RedisCacheBackend',
    'get_backend',
    'reset_backend',
    'cache_get',
    'cache_set',
    'cache_delete',
    'cache_flush',
    'cache_incr',
    'cache_atomic_update',
    'cache_response',
]


def _json_default(obj: object) -> str:
    """Module-level JSON serializer for datetime/Decimal/UUID.

    Shared between RedisCacheBackend.set() and atomic_update() so both go
    through the same serialization rules.
    """
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------


class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> Any | None: ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def flush(self) -> None: ...

    @abstractmethod
    async def incr(self, key: str, ttl: int = 0) -> int:
        """Atomically increment an integer counter; return the new value.

        - Creates the key with value 1 when absent or expired.
        - ``ttl`` is applied only on creation (rolling-window counters need
          to opt out by passing ``ttl=0`` and managing expiry separately).
        - Raises ``TypeError`` if the existing value is not an int.
        """

    @abstractmethod
    async def atomic_update(
        self,
        key: str,
        fn: Callable[[Any], Any],
        ttl: int = 0,
    ) -> Any:
        """Read-modify-write a key under exclusive concurrency control.

        ``fn(current)`` receives the current value (or ``None`` if absent or
        expired) and returns the new value. May be sync or async. The Redis
        backend uses optimistic concurrency (WATCH/MULTI/EXEC retry loop), so
        ``fn`` MUST be idempotent — it can be called multiple times under
        contention. The memory backend serializes via the global lock.
        """

    async def verify(self) -> None:
        """Probe backend connectivity. Default: no-op (always reachable).

        Backends that depend on a network service (e.g. Redis) override this
        to fail fast at startup rather than at first request.
        """
        return None


# ---------------------------------------------------------------------------
# Memory backend
# ---------------------------------------------------------------------------


class MemoryCacheBackend(CacheBackend):
    """In-memory LRU cache with TTL (single process).

    ``max_keys`` limits the number of stored entries (default: 10,000).
    When the limit is reached, the least-recently-used entry is evicted.
    Expired entries are evicted on read (lazy expiration).
    """

    def __init__(self, max_keys: int = 10_000) -> None:
        self._store: collections.OrderedDict[str, tuple[Any, float]] = collections.OrderedDict()
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            self._store.move_to_end(key)  # Mark as recently used
            return value

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        async with self._lock:
            expires_at = (time.time() + ttl) if ttl > 0 else 0.0
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, expires_at)
            while len(self._store) > self._max_keys:
                self._store.popitem(last=False)  # Evict LRU entry

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def flush(self) -> None:
        async with self._lock:
            self._store.clear()

    async def incr(self, key: str, ttl: int = 0) -> int:
        async with self._lock:
            now = time.time()
            entry = self._store.get(key)

            value = 0
            existing_expires_at = 0.0
            if entry is not None:
                stored_value, expires_at = entry
                if expires_at and now > expires_at:
                    pass  # Treat expired entry as missing — counter restarts at 1.
                else:
                    if not isinstance(stored_value, int):
                        raise TypeError(
                            f"cache.incr: existing value at {key!r} is not an int "
                            f"(got {type(stored_value).__name__})"
                        )
                    value = stored_value
                    existing_expires_at = expires_at

            value += 1

            # TTL is applied only when the counter is born (existing TTL preserved).
            new_expires_at = (
                existing_expires_at
                if existing_expires_at and existing_expires_at > now
                else (now + ttl) if ttl > 0 else 0.0
            )

            self._store[key] = (value, new_expires_at)
            self._store.move_to_end(key)
            while len(self._store) > self._max_keys:
                self._store.popitem(last=False)
            return value

    async def atomic_update(
        self,
        key: str,
        fn: Callable[[Any], Any],
        ttl: int = 0,
    ) -> Any:
        async with self._lock:
            now = time.time()
            entry = self._store.get(key)

            current: Any = None
            existing_expires_at = 0.0
            if entry is not None:
                value, expires_at = entry
                if not (expires_at and now > expires_at):
                    current = value
                    existing_expires_at = expires_at

            result = fn(current)
            if inspect.iscoroutine(result):
                result = await result

            new_expires_at = (now + ttl) if ttl > 0 else existing_expires_at
            self._store[key] = (result, new_expires_at)
            self._store.move_to_end(key)
            while len(self._store) > self._max_keys:
                self._store.popitem(last=False)
            return result

    def clear(self) -> None:
        """Synchronous clear for tests."""
        self._store.clear()


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------

# Atomic INCR + conditional EXPIRE. Redis runs Lua scripts on a single thread,
# so the whole operation is observed atomically by other clients. EXPIRE only
# fires on the FIRST increment (return value 1) so subsequent INCRs don't
# refresh the TTL — counters represent a window that started at first hit.
_INCR_LUA = """
local v = redis.call('INCR', KEYS[1])
if v == 1 and tonumber(ARGV[1]) > 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return v
"""


class RedisCacheBackend(CacheBackend):
    """Redis-backed cache using string keys with expiry."""

    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as aioredis

        self._redis_url = redis_url
        self._redis = aioredis.from_url(redis_url, socket_connect_timeout=5)
        self._prefix = 'cache:'

    async def verify(self) -> None:
        """Ping Redis to fail fast at startup if unreachable."""
        try:
            # redis-py's ping() stub unions Awaitable[bool] | bool for the sync/async overload.
            # On the asyncio client we always get a coroutine; cast narrows it for mypy.
            from collections.abc import Awaitable
            from typing import cast

            await cast(Awaitable[bool], self._redis.ping())
        except Exception as exc:
            raise RuntimeError(f'CACHE_BACKEND=redis but Redis at {self._redis_url} is not reachable: {exc}') from exc

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(f'{self._prefix}{key}')
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw.decode('utf-8') if isinstance(raw, bytes) else raw

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        rkey = f'{self._prefix}{key}'
        serialized = json.dumps(value, default=_json_default)
        if ttl > 0:
            await self._redis.setex(rkey, ttl, serialized)
        else:
            await self._redis.set(rkey, serialized)

    async def incr(self, key: str, ttl: int = 0) -> int:
        """INCR + EXPIRE wrapped in a Lua script so the whole operation is
        atomic across workers — INCR alone is atomic, but the EXPIRE that
        applies the TTL needs to ride along to avoid a TOCTOU window."""
        rkey = f'{self._prefix}{key}'
        result = await self._redis.eval(_INCR_LUA, 1, rkey, ttl)
        return int(result)

    async def atomic_update(
        self,
        key: str,
        fn: Callable[[Any], Any],
        ttl: int = 0,
    ) -> Any:
        from redis.exceptions import WatchError

        rkey = f'{self._prefix}{key}'
        async with self._redis.pipeline(transaction=True) as pipe:
            while True:
                try:
                    await pipe.watch(rkey)
                    raw = await pipe.get(rkey)

                    if raw is None:
                        current: Any = None
                    else:
                        try:
                            current = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            current = raw.decode('utf-8') if isinstance(raw, bytes) else raw

                    result = fn(current)
                    if inspect.iscoroutine(result):
                        result = await result

                    serialized = json.dumps(result, default=_json_default)

                    pipe.multi()
                    if ttl > 0:
                        pipe.setex(rkey, ttl, serialized)
                    else:
                        pipe.set(rkey, serialized)

                    await pipe.execute()
                    return result
                except WatchError:
                    # Another client wrote between WATCH and EXEC. Retry.
                    # fn() will be called again — caller must keep it idempotent.
                    continue

    async def delete(self, key: str) -> None:
        await self._redis.delete(f'{self._prefix}{key}')

    async def flush(self) -> None:
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor,
                match=f'{self._prefix}*',
                count=100,
            )
            if keys:
                await self._redis.delete(*keys)
            if cursor == 0:
                break

    async def shutdown(self) -> None:
        await self._redis.close()


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_backend: CacheBackend | None = None


def get_backend() -> CacheBackend:
    global _backend
    if _backend is not None:
        return _backend

    backend_type = config.get('CACHE_BACKEND', 'memory').lower()

    if backend_type == 'redis':
        redis_url = config.get('REDIS_URL', 'redis://localhost:6379')
        _backend = RedisCacheBackend(redis_url)
    else:
        max_keys = int(config.get('CACHE_MAX_KEYS', 10_000))
        _backend = MemoryCacheBackend(max_keys=max_keys)

    return _backend


def reset_backend() -> None:
    global _backend
    _backend = None


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


async def cache_get(key: str) -> Any | None:
    return await get_backend().get(key)


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    await get_backend().set(key, value, ttl)


async def cache_delete(key: str) -> None:
    await get_backend().delete(key)


async def cache_flush() -> None:
    await get_backend().flush()


async def cache_incr(key: str, ttl: int = 0) -> int:
    """Atomically increment a counter; return the new value.

    Use for any counter that can be touched concurrently (rate-limit windows,
    failed-login attempts, queue depth tracking, etc.). Plain ``cache_get +
    cache_set`` is NOT a substitute — it has a TOCTOU window that lets
    parallel callers all see the same baseline and clobber each other.
    """
    return await get_backend().incr(key, ttl)


async def cache_atomic_update(
    key: str,
    fn: Callable[[Any], Any],
    ttl: int = 0,
) -> Any:
    """Read-modify-write a key atomically.

    ``fn(current)`` receives the current value (or ``None``) and returns the
    new value; may be sync or async. Use whenever the new value depends on
    the old one and another worker could race you. Under the Redis backend
    this uses optimistic concurrency (WATCH/MULTI/EXEC retry), so ``fn``
    must be idempotent — it can be invoked more than once if a competing
    write lands first.
    """
    return await get_backend().atomic_update(key, fn, ttl)


# ---------------------------------------------------------------------------
# Response caching decorator
# ---------------------------------------------------------------------------


def cache_response(
    ttl: int = 60,
    key_prefix: str = 'view',
    key_fn: Callable[[Any], str] | None = None,
) -> Callable:
    """Cache GET response bodies. Non-GET requests pass through.

    Bodies are stored base64-encoded so binary responses (PDFs, images,
    archives) round-trip byte-for-byte. The Redis backend serializes
    cache values via JSON, which cannot represent raw bytes — and the
    pre-v1.19.0 implementation called ``body.decode('utf-8')`` before
    storing, which crashed or silently corrupted binary content.

    Multi-tenant / authenticated routes:

    The default cache key is built from the URL path and query string —
    appropriate for **anonymous, public** endpoints. If you decorate an
    authenticated or per-tenant route, two different users hitting the
    same path will share the cached response, leaking data across
    sessions. Pass a ``key_fn(request) -> str`` to inject the auth
    context (user_id, tenant_id, role) into the key::

        @cache_response(ttl=60, key_fn=lambda r: f'u={r.session.get("user_id")}')
        async def my_dashboard(self, request): ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
            if request.method != 'GET':
                return await func(self, request, *args, **kwargs)

            # Default key shape is unchanged — stable across upgrades for the
            # public-endpoint case. ``key_fn`` adds an extra segment so existing
            # cached entries don't conflict with the new scoped keys.
            if key_fn is None:
                cache_key = f'{key_prefix}:{request.url.path}:{request.url.query}'
            else:
                cache_key = f'{key_prefix}:{key_fn(request)}:{request.url.path}:{request.url.query}'
            cached = await cache_get(cache_key)
            if cached is not None:
                from starlette.responses import Response

                # New shape: body_b64 (bytes-safe). Old shape: body (utf-8
                # string only, pre-v1.19.0). Fall back so cached entries
                # survive an upgrade — they expire on TTL anyway.
                body_b64 = cached.get('body_b64')
                if body_b64 is not None:
                    body: bytes = base64.b64decode(body_b64)
                else:
                    legacy = cached.get('body', b'')
                    body = legacy.encode('utf-8') if isinstance(legacy, str) else legacy

                return Response(
                    content=body,
                    status_code=cached['status_code'],
                    media_type=cached.get('media_type'),
                )

            response = await func(self, request, *args, **kwargs)

            # Only cache successful responses (2xx)
            if 200 <= response.status_code < 300:
                raw = response.body
                if isinstance(raw, str):
                    raw = raw.encode('utf-8')
                await cache_set(
                    cache_key,
                    {
                        'body_b64': base64.b64encode(raw).decode('ascii'),
                        'status_code': response.status_code,
                        'media_type': response.media_type,
                    },
                    ttl,
                )

            return response

        return wrapper

    return decorator
