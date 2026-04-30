"""Tests for core.cache."""

import asyncio
import json
import time

import pytest
from core.cache import (
    MemoryCacheBackend,
    cache_atomic_update,
    cache_delete,
    cache_flush,
    cache_get,
    cache_incr,
    cache_response,
    cache_set,
    get_backend,
    reset_backend,
)
from starlette.responses import JSONResponse


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
    await backend.set('d', 4, ttl=60)  # Evicts 'b'
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
async def test_cache_response_key_fn_isolates_per_caller():
    """key_fn lets two callers on the same path get distinct cached responses."""
    call_count = 0

    class FakeURL:
        path = '/dashboard'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

        def __init__(self, user_id):
            self.user_id = user_id

    class Ctrl:
        @cache_response(ttl=60, key_fn=lambda r: f'u={r.user_id}')
        async def dashboard(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'user': request.user_id, 'n': call_count})

    ctrl = Ctrl()

    # Two distinct callers — neither should serve the other's cached body.
    r1a = await ctrl.dashboard(FakeRequest(user_id=1))
    r2a = await ctrl.dashboard(FakeRequest(user_id=2))
    assert call_count == 2

    # Same caller again — served from cache, no extra call.
    r1b = await ctrl.dashboard(FakeRequest(user_id=1))
    r2b = await ctrl.dashboard(FakeRequest(user_id=2))
    assert call_count == 2

    # Bodies still match per-user (sanity check).
    assert json.loads(r1a.body) == json.loads(r1b.body)
    assert json.loads(r2a.body) == json.loads(r2b.body)
    assert json.loads(r1a.body)['user'] != json.loads(r2a.body)['user']


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


@pytest.mark.asyncio
async def test_cache_response_preserves_binary_body():
    """Binary responses (PDF, image, ZIP) must round-trip byte-for-byte.

    Pre-v1.19.0, the decorator did ``body.decode('utf-8')`` before
    storing — which crashed on raw binary or, on backends that swallowed
    the error, served corrupted bytes from the cache. The fix base64s
    the body so JSON-serializing backends (Redis) can store it without
    loss.
    """
    from starlette.responses import Response

    # PDF magic header + bytes that are NOT valid UTF-8 (0x80-0xFF block)
    pdf_bytes = b'%PDF-1.4\n\x80\x81\x82\xff\xfe\xfd binary garbage \x00\x01'
    call_count = 0

    class FakeURL:
        path = '/report.pdf'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

    class Ctrl:
        @cache_response(ttl=60)
        async def report(self, request):
            nonlocal call_count
            call_count += 1
            return Response(
                content=pdf_bytes,
                status_code=200,
                media_type='application/pdf',
            )

    ctrl = Ctrl()
    req = FakeRequest()

    resp1 = await ctrl.report(req)
    resp2 = await ctrl.report(req)

    assert call_count == 1  # second call hit the cache
    assert resp1.body == pdf_bytes
    assert resp2.body == pdf_bytes  # exact byte-for-byte match
    assert resp2.media_type == 'application/pdf'


@pytest.mark.asyncio
async def test_cache_response_legacy_body_field_still_renders():
    """Cache entries written by pre-v1.19.0 used a 'body' field with a
    utf-8 string. After upgrade, those entries should still render until
    they expire — not crash the request."""
    from starlette.responses import Response

    from core.cache import cache_set

    class FakeURL:
        path = '/legacy-cached'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

    # Pre-seed a cache entry in the OLD shape (no body_b64)
    await cache_set(
        'view:/legacy-cached:',
        {
            'body': '<h1>legacy</h1>',
            'status_code': 200,
            'media_type': 'text/html',
        },
        60,
    )

    class Ctrl:
        @cache_response(ttl=60)
        async def page(self, request):
            return Response('<h1>fresh</h1>', media_type='text/html')

    resp = await Ctrl().page(FakeRequest())
    assert resp.body == b'<h1>legacy</h1>'  # served from legacy-shape cache
    assert resp.media_type == 'text/html'


# ---------------------------------------------------------------------------
# @cache_response(vary_on=...) — header-aware cache key
# ---------------------------------------------------------------------------


class _CaseInsensitiveHeaders:
    """Minimal stand-in for Starlette's ``request.headers`` — supports
    case-insensitive lookups via ``.get(name, default)`` exactly like
    the real implementation. Tests use this so they don't need a full
    Starlette request object.
    """

    def __init__(self, mapping=None):
        self._m = {(k or '').lower(): v for k, v in (mapping or {}).items()}

    def get(self, key, default=''):
        return self._m.get((key or '').lower(), default)


@pytest.mark.asyncio
async def test_cache_response_vary_on_segments_by_header_value():
    """Pre-1.29 the cache key omitted request headers entirely, so the
    first requester pinned their language variant for every subsequent
    caller within the TTL window — a user with ``Accept-Language: es``
    would receive whatever variant the first ``Accept-Language: en``
    user populated. ``vary_on=['Accept-Language']`` folds the header
    value into the key so each language gets its own cache slot.
    """
    call_count = 0

    class FakeURL:
        path = '/home'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

        def __init__(self, headers=None):
            self.headers = _CaseInsensitiveHeaders(headers)

    class Ctrl:
        @cache_response(ttl=60, vary_on=['Accept-Language'])
        async def home(self, request):
            nonlocal call_count
            call_count += 1
            lang = request.headers.get('Accept-Language', '')
            return JSONResponse({'lang': lang, 'n': call_count})

    ctrl = Ctrl()
    en = FakeRequest({'Accept-Language': 'en'})
    es = FakeRequest({'Accept-Language': 'es'})

    # First en — populates cache slot for English
    await ctrl.home(en)
    # Second en — cache hit, handler not re-invoked
    await ctrl.home(en)
    assert call_count == 1

    # First es — distinct cache slot, handler MUST run again
    resp_es = await ctrl.home(es)
    assert call_count == 2
    body = json.loads(resp_es.body.decode())
    assert body['lang'] == 'es', (
        "vary_on did not segment cache by header — Spanish request received "
        "the previously-cached English variant"
    )


@pytest.mark.asyncio
async def test_cache_response_default_key_unchanged_without_vary_on():
    """Backward-compat regression: when ``vary_on`` is omitted, the
    cache key shape is identical to the pre-1.29 form. Cached entries
    written by a pre-1.29 process must remain reachable across an
    in-place upgrade — they only expire on TTL.
    """
    call_count = 0

    class FakeURL:
        path = '/products'
        query = 'page=1'

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

    class Ctrl:
        @cache_response(ttl=60)  # no vary_on
        async def listing(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'n': call_count})

    ctrl = Ctrl()
    await ctrl.listing(FakeRequest())
    await ctrl.listing(FakeRequest())
    assert call_count == 1

    backend = get_backend()
    keys = list(backend._store.keys())
    assert keys == ['view:/products:page=1'], (
        f'cache key shape regressed (no vary_on path): got {keys!r}'
    )


@pytest.mark.asyncio
async def test_cache_response_vary_on_treats_missing_header_as_empty():
    """Contract: a missing variance header contributes the empty string
    to the cache key segment. Two requests where the header is absent
    map to the same cached entry; a request that DOES carry the header
    gets a distinct slot.
    """
    call_count = 0

    class FakeURL:
        path = '/home'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

        def __init__(self, headers=None):
            self.headers = _CaseInsensitiveHeaders(headers)

    class Ctrl:
        @cache_response(ttl=60, vary_on=['X-Format'])
        async def view(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'n': call_count})

    ctrl = Ctrl()
    await ctrl.view(FakeRequest())  # header absent → '' segment
    await ctrl.view(FakeRequest())  # same → cache hit
    assert call_count == 1

    await ctrl.view(FakeRequest({'X-Format': 'json'}))  # distinct slot → miss
    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_response_vary_on_lookup_is_case_insensitive():
    """Header names in ``vary_on`` are matched case-insensitively, so
    an operator who declares ``vary_on=['Accept-Language']`` and a
    framework that lower-cases internally still hit the same key.
    """
    call_count = 0

    class FakeURL:
        path = '/home'
        query = ''

    class FakeRequest:
        method = 'GET'
        url = FakeURL()

        def __init__(self, headers=None):
            self.headers = _CaseInsensitiveHeaders(headers)

    class Ctrl:
        @cache_response(ttl=60, vary_on=['ACCEPT-LANGUAGE'])
        async def home(self, request):
            nonlocal call_count
            call_count += 1
            return JSONResponse({'n': call_count})

    ctrl = Ctrl()
    await ctrl.home(FakeRequest({'accept-language': 'en'}))
    await ctrl.home(FakeRequest({'Accept-Language': 'en'}))
    assert call_count == 1, (
        'header lookup was case-sensitive — same logical header value '
        'produced different cache keys'
    )


# ---------------------------------------------------------------------------
# RedisCacheBackend unit tests (fakeredis)
# ---------------------------------------------------------------------------
#
# fakeredis is an in-memory drop-in for redis-py's asyncio interface, so we
# can exercise the RedisCacheBackend without a live Redis server. The pattern:
# patch ``redis.asyncio.from_url`` so the constructor receives a FakeRedis
# instance rather than a real connection, then call backend methods normally.


def _patched_redis_backend(fake_client):
    """Return a context manager that patches redis.asyncio.from_url."""
    from unittest.mock import patch

    return patch('redis.asyncio.from_url', return_value=fake_client)


@pytest.mark.asyncio
async def test_redis_cache_set_and_get_string():
    """Round-trip a string through Redis (JSON-encoded by the backend)."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.set('hello', 'world', ttl=60)
    assert await backend.get('hello') == 'world'


@pytest.mark.asyncio
async def test_redis_cache_set_and_get_dict():
    """Round-trip a dict through Redis (JSON-encoded)."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.set('user:1', {'name': 'Ana', 'age': 30}, ttl=60)
    assert await backend.get('user:1') == {'name': 'Ana', 'age': 30}


@pytest.mark.asyncio
async def test_redis_cache_get_missing_returns_none():
    """A missing key returns None (not raise)."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    assert await backend.get('nope') is None


@pytest.mark.asyncio
async def test_redis_cache_set_without_ttl_persists():
    """ttl=0 stores without expiry (uses .set, not .setex)."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.set('persistent', 'value', ttl=0)
    assert await backend.get('persistent') == 'value'
    # Direct check: TTL on a no-ttl key should be -1 in Redis semantics
    raw_ttl = await fake.ttl('cache:persistent')
    assert raw_ttl == -1


@pytest.mark.asyncio
async def test_redis_cache_set_with_ttl_uses_setex():
    """Positive ttl applies the expiry (uses .setex)."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.set('ephemeral', 'value', ttl=120)
    raw_ttl = await fake.ttl('cache:ephemeral')
    assert 0 < raw_ttl <= 120


@pytest.mark.asyncio
async def test_redis_cache_delete_removes_key():
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.set('to-remove', 'X', ttl=60)
    await backend.delete('to-remove')
    assert await backend.get('to-remove') is None


@pytest.mark.asyncio
async def test_redis_cache_flush_clears_only_prefixed_keys():
    """flush() must SCAN the cache: prefix only — never touch unrelated keys."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.set('a', '1', ttl=60)
    await backend.set('b', '2', ttl=60)
    # An unrelated key the cache must NOT delete
    await fake.set('not-our-prefix', 'leave-me')

    await backend.flush()

    assert await backend.get('a') is None
    assert await backend.get('b') is None
    # The non-prefixed key survives
    assert await fake.get('not-our-prefix') == b'leave-me'


@pytest.mark.asyncio
async def test_redis_cache_serializes_datetime_decimal_uuid():
    """The custom JSON default handles datetime, Decimal, and UUID."""
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    payload = {
        'when': datetime(2026, 1, 1, 12, 0, 0),
        'price': Decimal('19.99'),
        'id': UUID('12345678-1234-5678-1234-567812345678'),
    }
    await backend.set('mixed', payload, ttl=60)
    out = await backend.get('mixed')
    assert out == {
        'when': '2026-01-01T12:00:00',
        'price': '19.99',
        'id': '12345678-1234-5678-1234-567812345678',
    }


@pytest.mark.asyncio
async def test_redis_cache_serializer_rejects_unsupported_type():
    """Types the JSON default doesn't know about raise TypeError on set."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    class NotSerializable:
        pass

    with pytest.raises(TypeError):
        await backend.set('weird', {'x': NotSerializable()}, ttl=60)


@pytest.mark.asyncio
async def test_redis_cache_get_falls_back_to_string_for_non_json():
    """A raw string (not JSON-encoded) stored directly returns as decoded str."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    # Pre-populate Redis with a value that isn't valid JSON
    await fake.set('cache:legacy', b'plain-string-not-json')

    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    # JSON decode fails → backend returns the bytes-decoded string
    assert await backend.get('legacy') == 'plain-string-not-json'


@pytest.mark.asyncio
async def test_redis_cache_verify_succeeds_when_reachable():
    """verify() pings Redis and returns None on success."""
    import fakeredis.aioredis
    from core.cache import RedisCacheBackend

    fake = fakeredis.aioredis.FakeRedis()
    with _patched_redis_backend(fake):
        backend = RedisCacheBackend('redis://localhost:6379')

    # Should not raise
    assert await backend.verify() is None


@pytest.mark.asyncio
async def test_redis_cache_verify_raises_runtime_error_when_unreachable():
    """verify() wraps any exception in RuntimeError naming the URL."""
    from unittest.mock import AsyncMock

    from core.cache import RedisCacheBackend

    broken = AsyncMock()
    broken.ping = AsyncMock(side_effect=ConnectionError('Connection refused'))

    with _patched_redis_backend(broken):
        backend = RedisCacheBackend('redis://unreachable:6379')

    with pytest.raises(RuntimeError, match='redis://unreachable:6379'):
        await backend.verify()


@pytest.mark.asyncio
async def test_redis_cache_shutdown_closes_connection():
    """shutdown() forwards to the underlying client's close()."""
    from unittest.mock import AsyncMock

    from core.cache import RedisCacheBackend

    closing = AsyncMock()
    closing.close = AsyncMock()

    with _patched_redis_backend(closing):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.shutdown()
    closing.close.assert_called_once()


def test_get_backend_returns_redis_when_configured():
    """CACHE_BACKEND=redis selects RedisCacheBackend."""
    from unittest.mock import patch

    import fakeredis.aioredis
    from core.cache import RedisCacheBackend, get_backend, reset_backend

    reset_backend()
    fake = fakeredis.aioredis.FakeRedis()
    with (
        patch('core.cache.config') as mock_config,
        patch('redis.asyncio.from_url', return_value=fake),
    ):
        mock_config.get.side_effect = lambda key, default=None: {
            'CACHE_BACKEND': 'redis',
            'REDIS_URL': 'redis://localhost:6379',
        }.get(key, default)

        backend = get_backend()
        assert isinstance(backend, RedisCacheBackend)
    reset_backend()


def test_memory_backend_clear_helper():
    """MemoryCacheBackend.clear() is a sync helper for tests."""
    from core.cache import MemoryCacheBackend

    backend = MemoryCacheBackend(max_keys=10)
    # Use the sync helper
    backend._store['x'] = ('value', 0.0)
    backend.clear()
    assert len(backend._store) == 0


# ---------------------------------------------------------------------------
# Atomic primitives — incr (memory)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_incr_starts_at_one():
    backend = MemoryCacheBackend()
    assert await backend.incr('counter') == 1


@pytest.mark.asyncio
async def test_memory_incr_increments_sequentially():
    backend = MemoryCacheBackend()
    assert await backend.incr('counter') == 1
    assert await backend.incr('counter') == 2
    assert await backend.incr('counter') == 3


@pytest.mark.asyncio
async def test_memory_incr_atomic_under_concurrency():
    """100 concurrent INCRs must produce all values 1..100 with no duplicates.

    Regression for the read-modify-write race that lets parallel calls
    bypass account lockout and rate limits.
    """
    backend = MemoryCacheBackend()
    results = await asyncio.gather(*[backend.incr('counter') for _ in range(100)])
    assert sorted(results) == list(range(1, 101))
    assert await backend.get('counter') == 100


@pytest.mark.asyncio
async def test_memory_incr_applies_ttl_on_first_only():
    """TTL is set when the counter is born and not refreshed by later INCRs."""
    backend = MemoryCacheBackend()
    await backend.incr('c', ttl=60)
    _, expires_first = backend._store['c']
    assert expires_first > 0

    # Advance the clock virtually — by passing through, second incr should
    # NOT push the expiry forward.
    await asyncio.sleep(0)  # let event loop settle
    await backend.incr('c', ttl=60)
    _, expires_second = backend._store['c']
    assert expires_second == expires_first  # not refreshed


@pytest.mark.asyncio
async def test_memory_incr_restarts_after_ttl_expiry():
    backend = MemoryCacheBackend()
    await backend.incr('c', ttl=60)
    backend._store['c'] = (5, time.time() - 10)  # force expired
    assert await backend.incr('c') == 1


@pytest.mark.asyncio
async def test_memory_incr_rejects_non_int_existing():
    backend = MemoryCacheBackend()
    await backend.set('mistaken', 'string', ttl=0)
    with pytest.raises(TypeError, match='not an int'):
        await backend.incr('mistaken')


@pytest.mark.asyncio
async def test_memory_incr_does_not_apply_ttl_to_existing_no_ttl_counter():
    """Counter pre-exists with no TTL (e.g. a long-lived
    ``cache_set(key, value, ttl=0)`` counter), then a later
    ``cache_incr(key, ttl=60)`` arrives. Pre-1.29 the Memory backend
    would (incorrectly) apply the 60s TTL to the pre-existing entry —
    its branch ``existing_expires_at and existing_expires_at > now``
    failed because ``0.0`` is falsy, indistinguishably from "no entry
    at all". Redis's Lua only fires ``EXPIRE`` when ``INCR`` returns 1
    (i.e. the counter genuinely born), and an existing counter
    returns ``N+1``. Memory must match Redis: a pre-existing counter
    keeps its TTL state verbatim, even when that state is "no TTL".
    """
    backend = MemoryCacheBackend()
    await backend.set('counter', 5, ttl=0)  # no TTL — counter persists indefinitely

    new_value = await backend.incr('counter', ttl=60)
    assert new_value == 6

    _, expires_at = backend._store['counter']
    assert expires_at == 0.0, (
        f'incr applied a TTL retroactively to a counter that pre-existed '
        f'without one (got expires_at={expires_at}); Redis would not'
    )


# ---------------------------------------------------------------------------
# Atomic primitives — atomic_update (memory)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_atomic_update_initial_value_is_none():
    backend = MemoryCacheBackend()
    result = await backend.atomic_update(
        'key', lambda current: 'first' if current is None else 'wrong'
    )
    assert result == 'first'
    assert await backend.get('key') == 'first'


@pytest.mark.asyncio
async def test_memory_atomic_update_modifies_existing():
    backend = MemoryCacheBackend()
    await backend.set('counter', 5, ttl=60)
    result = await backend.atomic_update('counter', lambda v: v + 1)
    assert result == 6
    assert await backend.get('counter') == 6


@pytest.mark.asyncio
async def test_memory_atomic_update_atomic_under_concurrency():
    """50 concurrent atomic_update increments — all distinct return values 1..50."""
    backend = MemoryCacheBackend()

    def increment(current):
        return (current or 0) + 1

    results = await asyncio.gather(
        *[backend.atomic_update('counter', increment) for _ in range(50)]
    )
    assert sorted(results) == list(range(1, 51))
    assert await backend.get('counter') == 50


@pytest.mark.asyncio
async def test_memory_atomic_update_async_fn():
    backend = MemoryCacheBackend()

    async def async_fn(current):
        return 'computed'

    result = await backend.atomic_update('key', async_fn)
    assert result == 'computed'


# ---------------------------------------------------------------------------
# Atomic primitives — convenience functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_incr_convenience():
    assert await cache_incr('test_counter') == 1
    assert await cache_incr('test_counter') == 2


@pytest.mark.asyncio
async def test_cache_atomic_update_convenience():
    result = await cache_atomic_update('test_key', lambda c: (c or 0) + 1)
    assert result == 1
    result = await cache_atomic_update('test_key', lambda c: c + 10)
    assert result == 11


# ---------------------------------------------------------------------------
# Atomic primitives — Redis backend
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis_with_lua():
    """fakeredis instance, skipped if Lua support (lupa) is not installed."""
    try:
        import lupa  # noqa: F401
    except ImportError:
        pytest.skip('Redis incr tests require lupa for fakeredis Lua support')

    import fakeredis.aioredis

    return fakeredis.aioredis.FakeRedis()


@pytest.mark.asyncio
async def test_redis_incr_starts_at_one(fake_redis_with_lua):
    from core.cache import RedisCacheBackend

    with _patched_redis_backend(fake_redis_with_lua):
        backend = RedisCacheBackend('redis://localhost:6379')

    assert await backend.incr('counter') == 1
    assert await backend.incr('counter') == 2
    assert await backend.incr('counter') == 3


@pytest.mark.asyncio
async def test_redis_incr_applies_ttl_on_first_increment(fake_redis_with_lua):
    """First INCR sets EXPIRE; subsequent INCRs don't refresh it."""
    from core.cache import RedisCacheBackend

    with _patched_redis_backend(fake_redis_with_lua):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.incr('c', ttl=60)
    ttl_after_first = await fake_redis_with_lua.ttl('cache:c')
    assert 0 < ttl_after_first <= 60


@pytest.mark.asyncio
async def test_redis_atomic_update_initial_none(fake_redis_with_lua):
    """atomic_update on a missing key passes None to the function."""
    from core.cache import RedisCacheBackend

    with _patched_redis_backend(fake_redis_with_lua):
        backend = RedisCacheBackend('redis://localhost:6379')
        result = await backend.atomic_update(
            'key', lambda c: 'created' if c is None else 'wrong'
        )

    assert result == 'created'
    assert await backend.get('key') == 'created'


@pytest.mark.asyncio
async def test_redis_atomic_update_modifies_existing(fake_redis_with_lua):
    from core.cache import RedisCacheBackend

    with _patched_redis_backend(fake_redis_with_lua):
        backend = RedisCacheBackend('redis://localhost:6379')

    await backend.set('counter', 5, ttl=60)
    result = await backend.atomic_update('counter', lambda v: v + 1)
    assert result == 6
    assert await backend.get('counter') == 6
