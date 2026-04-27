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
