"""Tests for core.cache."""
import time
import pytest
from starlette.responses import JSONResponse

from core.cache import (
    MemoryCacheBackend,
    get_backend,
    reset_backend,
    cache_get,
    cache_set,
    cache_delete,
    cache_flush,
    cache_response,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_backend()
    yield
    reset_backend()


# --- MemoryCacheBackend unit tests ---

@pytest.mark.asyncio
async def test_memory_cache_empty():
    backend = MemoryCacheBackend()
    assert await backend.get('missing') is None


@pytest.mark.asyncio
async def test_memory_cache_set_and_get():
    backend = MemoryCacheBackend()
    await backend.set('key', {'data': 1}, ttl=60)
    assert await backend.get('key') == {'data': 1}


@pytest.mark.asyncio
async def test_memory_cache_ttl_expiry():
    backend = MemoryCacheBackend()
    backend._store['key'] = ({'data': 1}, time.time() - 10)
    assert await backend.get('key') is None


@pytest.mark.asyncio
async def test_memory_cache_no_ttl_persists():
    backend = MemoryCacheBackend()
    await backend.set('key', 'forever', ttl=0)
    assert await backend.get('key') == 'forever'


@pytest.mark.asyncio
async def test_memory_cache_delete():
    backend = MemoryCacheBackend()
    await backend.set('key', 'value', ttl=60)
    await backend.delete('key')
    assert await backend.get('key') is None


@pytest.mark.asyncio
async def test_memory_cache_delete_missing():
    backend = MemoryCacheBackend()
    await backend.delete('nonexistent')  # should not raise


@pytest.mark.asyncio
async def test_memory_cache_flush():
    backend = MemoryCacheBackend()
    await backend.set('a', 1, ttl=60)
    await backend.set('b', 2, ttl=60)
    await backend.flush()
    assert await backend.get('a') is None
    assert await backend.get('b') is None


# --- LRU eviction ---

@pytest.mark.asyncio
async def test_lru_evicts_oldest_when_full():
    backend = MemoryCacheBackend(max_keys=3)
    await backend.set('a', 1, ttl=60)
    await backend.set('b', 2, ttl=60)
    await backend.set('c', 3, ttl=60)
    await backend.set('d', 4, ttl=60)  # Evicts 'a'
    assert await backend.get('a') is None
    assert await backend.get('b') == 2
    assert await backend.get('d') == 4


@pytest.mark.asyncio
async def test_lru_get_refreshes_key():
    backend = MemoryCacheBackend(max_keys=3)
    await backend.set('a', 1, ttl=60)
    await backend.set('b', 2, ttl=60)
    await backend.set('c', 3, ttl=60)
    await backend.get('a')  # Refresh 'a' — now 'b' is LRU
    await backend.set('d', 4, ttl=60)  # Evicts 'b', not 'a'
    assert await backend.get('a') == 1
    assert await backend.get('b') is None


@pytest.mark.asyncio
async def test_lru_set_existing_refreshes_key():
    backend = MemoryCacheBackend(max_keys=3)
    await backend.set('a', 1, ttl=60)
    await backend.set('b', 2, ttl=60)
    await backend.set('c', 3, ttl=60)
    await backend.set('a', 10, ttl=60)  # Update 'a' — now 'b' is LRU
    await backend.set('d', 4, ttl=60)   # Evicts 'b'
    assert await backend.get('a') == 10
    assert await backend.get('b') is None


@pytest.mark.asyncio
async def test_lru_respects_max_keys():
    backend = MemoryCacheBackend(max_keys=5)
    for i in range(20):
        await backend.set(f'key{i}', i, ttl=60)
    assert len(backend._store) == 5
    # Only the last 5 should survive
    for i in range(15):
        assert await backend.get(f'key{i}') is None
    for i in range(15, 20):
        assert await backend.get(f'key{i}') == i


@pytest.mark.asyncio
async def test_lru_default_max_keys():
    backend = MemoryCacheBackend()
    assert backend._max_keys == 10_000


# --- Convenience functions ---

@pytest.mark.asyncio
async def test_cache_set_and_get():
    await cache_set('test', 'value', ttl=60)
    assert await cache_get('test') == 'value'


@pytest.mark.asyncio
async def test_cache_delete():
    await cache_set('del_me', 'value', ttl=60)
    await cache_delete('del_me')
    assert await cache_get('del_me') is None


@pytest.mark.asyncio
async def test_cache_flush():
    await cache_set('x', 1, ttl=60)
    await cache_flush()
    assert await cache_get('x') is None


# --- Singleton ---

def test_get_backend_defaults_to_memory():
    backend = get_backend()
    assert isinstance(backend, MemoryCacheBackend)


# --- @cache_response decorator ---

@pytest.mark.asyncio
async def test_cache_response_caches_get():
    call_count = 0

    class FakeURL:
        path = '/products'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

    class Ctrl:
        @cache_response(ttl=60)
        async def list(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'count': call_count})

    ctrl = Ctrl()
    req = FakeRequest()

    await ctrl.list(req)
    await ctrl.list(req)
    assert call_count == 1  # second call was cached


@pytest.mark.asyncio
async def test_cache_response_skips_post():
    call_count = 0

    class FakeRequest:
        method = 'POST'

    class Ctrl:
        @cache_response(ttl=60)
        async def create(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'ok': True})

    ctrl = Ctrl()
    await ctrl.create(FakeRequest())
    await ctrl.create(FakeRequest())
    assert call_count == 2  # not cached


@pytest.mark.asyncio
async def test_cache_response_does_not_cache_errors():
    """Error responses (non-2xx) should not be cached."""
    call_count = 0

    class FakeURL:
        path = '/error-test'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

    class Ctrl:
        @cache_response(ttl=60)
        async def failing(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'error': 'fail'}, status_code=500)

    ctrl = Ctrl()
    req = FakeRequest()

    resp1 = await ctrl.failing(req)
    assert resp1.status_code == 500

    resp2 = await ctrl.failing(req)
    assert resp2.status_code == 500
    assert call_count == 2  # not cached — handler called both times


@pytest.mark.asyncio
async def test_cache_response_caches_only_200():
    """404 responses should not be cached either."""
    call_count = 0

    class FakeURL:
        path = '/notfound-test'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

    class Ctrl:
        @cache_response(ttl=60)
        async def maybe_missing(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'error': 'not found'}, status_code=404)

    ctrl = Ctrl()
    await ctrl.maybe_missing(FakeRequest())
    await ctrl.maybe_missing(FakeRequest())
    assert call_count == 2
