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
import collections
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
    'cache_response',
]


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

    def clear(self) -> None:
        """Synchronous clear for tests."""
        self._store.clear()


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


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

        def _json_default(obj: object) -> str:
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

        serialized = json.dumps(value, default=_json_default)
        if ttl > 0:
            await self._redis.setex(rkey, ttl, serialized)
        else:
            await self._redis.set(rkey, serialized)

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


# ---------------------------------------------------------------------------
# Response caching decorator
# ---------------------------------------------------------------------------


def cache_response(ttl: int = 60, key_prefix: str = 'view') -> Callable:
    """Cache GET response bodies. Non-GET requests pass through."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
            if request.method != 'GET':
                return await func(self, request, *args, **kwargs)

            cache_key = f'{key_prefix}:{request.url.path}:{request.url.query}'
            cached = await cache_get(cache_key)
            if cached is not None:
                from starlette.responses import Response

                return Response(
                    content=cached['body'],
                    status_code=cached['status_code'],
                    media_type=cached.get('media_type'),
                )

            response = await func(self, request, *args, **kwargs)

            # Only cache successful responses (2xx)
            if 200 <= response.status_code < 300:
                body = response.body
                await cache_set(
                    cache_key,
                    {
                        'body': body.decode('utf-8') if isinstance(body, bytes) else body,
                        'status_code': response.status_code,
                        'media_type': response.media_type,
                    },
                    ttl,
                )

            return response

        return wrapper

    return decorator
