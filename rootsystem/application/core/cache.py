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
import json
import time
from abc import ABC, abstractmethod
from functools import wraps
from typing import Any, Callable

import settings
from core.logger import get_logger

_log = get_logger('cache')

__all__ = [
    'CacheBackend', 'MemoryCacheBackend', 'RedisCacheBackend',
    'get_backend', 'reset_backend',
    'cache_get', 'cache_set', 'cache_delete', 'cache_flush',
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


# ---------------------------------------------------------------------------
# Memory backend
# ---------------------------------------------------------------------------

class MemoryCacheBackend(CacheBackend):
    """In-memory cache with TTL (single process)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        async with self._lock:
            expires_at = (time.time() + ttl) if ttl > 0 else 0.0
            self._store[key] = (value, expires_at)

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
        self._redis = aioredis.from_url(redis_url, socket_connect_timeout=5)
        self._prefix = 'cache:'

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(f"{self._prefix}{key}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw.decode('utf-8') if isinstance(raw, bytes) else raw

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        rkey = f"{self._prefix}{key}"
        serialized = json.dumps(value, default=str)
        if ttl > 0:
            await self._redis.setex(rkey, ttl, serialized)
        else:
            await self._redis.set(rkey, serialized)

    async def delete(self, key: str) -> None:
        await self._redis.delete(f"{self._prefix}{key}")

    async def flush(self) -> None:
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor, match=f"{self._prefix}*", count=100,
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

    backend_type = getattr(settings, 'CACHE_BACKEND', 'memory').lower()

    if backend_type == 'redis':
        redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379')
        try:
            _backend = RedisCacheBackend(redis_url)
        except Exception:
            _log.warning("Redis cache unavailable, falling back to memory")
            _backend = MemoryCacheBackend()
    else:
        _backend = MemoryCacheBackend()

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

            cache_key = f"{key_prefix}:{request.url.path}:{request.url.query}"
            cached = await cache_get(cache_key)
            if cached is not None:
                from starlette.responses import Response
                return Response(
                    content=cached['body'],
                    status_code=cached['status_code'],
                    media_type=cached.get('media_type'),
                )

            response = await func(self, request, *args, **kwargs)

            body = response.body
            await cache_set(cache_key, {
                'body': body.decode('utf-8') if isinstance(body, bytes) else body,
                'status_code': response.status_code,
                'media_type': response.media_type,
            }, ttl)

            return response
        return wrapper
    return decorator
