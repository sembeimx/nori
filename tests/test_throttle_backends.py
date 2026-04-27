"""Tests for core.http.throttle_backends."""

import time

import pytest
from core.http.throttle_backends import MemoryBackend, get_backend, reset_backend


@pytest.fixture(autouse=True)
def _reset():
    reset_backend()


@pytest.mark.asyncio
async def test_memory_backend_empty_initially():
    """New MemoryBackend has no timestamps."""
    backend = MemoryBackend()
    ts = await backend.get_timestamps('key', 60)
    assert ts == []


@pytest.mark.asyncio
async def test_memory_backend_add_and_get():
    """Added timestamps are retrievable."""
    backend = MemoryBackend()
    now = time.time()
    await backend.add_timestamp('key', now, 60)
    ts = await backend.get_timestamps('key', 60)
    assert len(ts) == 1
    assert ts[0] == now


@pytest.mark.asyncio
async def test_memory_backend_expired_filtered():
    """Expired timestamps are not returned."""
    backend = MemoryBackend()
    old = time.time() - 120
    now = time.time()
    await backend.add_timestamp('key', old, 60)
    await backend.add_timestamp('key', now, 60)
    ts = await backend.get_timestamps('key', 60)
    assert len(ts) == 1
    assert ts[0] == now


@pytest.mark.asyncio
async def test_memory_backend_cleanup():
    """Cleanup removes expired timestamps."""
    backend = MemoryBackend()
    old = time.time() - 120
    backend._store['key'] = [old]
    await backend.cleanup('key', 60)
    ts = await backend.get_timestamps('key', 60)
    assert ts == []


@pytest.mark.asyncio
async def test_memory_backend_clear():
    """Clear resets all data."""
    backend = MemoryBackend()
    await backend.add_timestamp('key', time.time(), 60)
    backend.clear()
    ts = await backend.get_timestamps('key', 60)
    assert ts == []


def test_get_backend_defaults_to_memory():
    """Default backend is MemoryBackend."""
    backend = get_backend()
    assert isinstance(backend, MemoryBackend)


# ---------------------------------------------------------------------------
# RedisBackend (fakeredis)
# ---------------------------------------------------------------------------


def _patched_redis(fake_client):
    """Patch redis.asyncio.from_url to return the supplied fake client."""
    from unittest.mock import patch

    return patch('redis.asyncio.from_url', return_value=fake_client)


@pytest.mark.asyncio
async def test_redis_backend_add_and_get_timestamp():
    """Round-trip a single timestamp through Redis sorted-set storage."""
    import fakeredis.aioredis
    from core.http.throttle_backends import RedisBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis(fake):
        backend = RedisBackend('redis://localhost:6379')

    now = time.time()
    await backend.add_timestamp('user:42', now, 60)
    ts = await backend.get_timestamps('user:42', 60)
    assert len(ts) == 1
    assert abs(ts[0] - now) < 0.01


@pytest.mark.asyncio
async def test_redis_backend_filters_expired_timestamps():
    """Timestamps older than the window are not returned by get_timestamps."""
    import fakeredis.aioredis
    from core.http.throttle_backends import RedisBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis(fake):
        backend = RedisBackend('redis://localhost:6379')

    old = time.time() - 120
    now = time.time()
    await backend.add_timestamp('user:7', old, 60)
    await backend.add_timestamp('user:7', now, 60)

    ts = await backend.get_timestamps('user:7', 60)
    # The pipeline in add_timestamp also runs zremrangebyscore, so old has been
    # pruned during the second add. get_timestamps filters via zrangebyscore by cutoff.
    assert all(t > time.time() - 60 for t in ts)


@pytest.mark.asyncio
async def test_redis_backend_cleanup_removes_expired():
    """cleanup() drops entries below the cutoff."""
    import fakeredis.aioredis
    from core.http.throttle_backends import RedisBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis(fake):
        backend = RedisBackend('redis://localhost:6379')

    # Manually inject an old entry under the prefixed key
    await fake.zadd('throttle:user:9', {'1.0': 1.0})
    await backend.cleanup('user:9', window=60)

    remaining = await fake.zrange('throttle:user:9', 0, -1)
    assert remaining == []


@pytest.mark.asyncio
async def test_redis_backend_verify_succeeds_when_reachable():
    """verify() pings successfully against a live (fake) Redis."""
    import fakeredis.aioredis
    from core.http.throttle_backends import RedisBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis(fake):
        backend = RedisBackend('redis://localhost:6379')

    assert await backend.verify() is None


@pytest.mark.asyncio
async def test_redis_backend_verify_raises_when_unreachable():
    """verify() wraps connection failures in RuntimeError naming the URL."""
    from unittest.mock import AsyncMock

    from core.http.throttle_backends import RedisBackend

    broken = AsyncMock()
    broken.ping = AsyncMock(side_effect=ConnectionError('Connection refused'))

    with _patched_redis(broken):
        backend = RedisBackend('redis://nowhere:6379')

    with pytest.raises(RuntimeError, match='redis://nowhere:6379'):
        await backend.verify()


@pytest.mark.asyncio
async def test_redis_backend_shutdown_closes_connection():
    """shutdown() forwards to the underlying client's close()."""
    from unittest.mock import AsyncMock

    from core.http.throttle_backends import RedisBackend

    closing = AsyncMock()
    closing.close = AsyncMock()
    with _patched_redis(closing):
        backend = RedisBackend('redis://localhost:6379')

    await backend.shutdown()
    closing.close.assert_called_once()


def test_get_backend_returns_redis_when_configured():
    """THROTTLE_BACKEND=redis selects RedisBackend."""
    from unittest.mock import patch

    import fakeredis.aioredis
    from core.http.throttle_backends import RedisBackend, get_backend, reset_backend

    reset_backend()
    fake = fakeredis.aioredis.FakeRedis()
    with (
        patch('core.http.throttle_backends.config') as mock_config,
        patch('redis.asyncio.from_url', return_value=fake),
    ):
        mock_config.get.side_effect = lambda key, default=None: {
            'THROTTLE_BACKEND': 'redis',
            'REDIS_URL': 'redis://localhost:6379',
        }.get(key, default)

        backend = get_backend()
        assert isinstance(backend, RedisBackend)
    reset_backend()


@pytest.mark.asyncio
async def test_memory_backend_global_cleanup_after_threshold():
    """The lazy global cleanup runs every _CLEANUP_EVERY add_timestamp calls."""
    backend = MemoryBackend()
    backend._CLEANUP_EVERY = 5  # accelerate for the test

    # Inject an expired key so we have something to clean
    backend._store['expired-key'] = [time.time() - 1000]

    # Add 5 timestamps to a different key — triggers global cleanup once
    for _ in range(5):
        await backend.add_timestamp('fresh-key', time.time(), 60)

    # The expired key should have been swept by _global_cleanup_locked
    assert 'expired-key' not in backend._store
