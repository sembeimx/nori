"""Tests for core.http.throttle_backends."""
import asyncio
import time
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from core.http.throttle_backends import MemoryBackend, get_backend, reset_backend


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def setup_function():
    reset_backend()


def test_memory_backend_empty_initially():
    """New MemoryBackend has no timestamps."""
    backend = MemoryBackend()
    ts = _run(backend.get_timestamps('key', 60))
    assert ts == []


def test_memory_backend_add_and_get():
    """Added timestamps are retrievable."""
    backend = MemoryBackend()
    now = time.time()
    _run(backend.add_timestamp('key', now, 60))
    ts = _run(backend.get_timestamps('key', 60))
    assert len(ts) == 1
    assert ts[0] == now


def test_memory_backend_expired_filtered():
    """Expired timestamps are not returned."""
    backend = MemoryBackend()
    old = time.time() - 120
    now = time.time()
    _run(backend.add_timestamp('key', old, 60))
    _run(backend.add_timestamp('key', now, 60))
    ts = _run(backend.get_timestamps('key', 60))
    assert len(ts) == 1
    assert ts[0] == now


def test_memory_backend_cleanup():
    """Cleanup removes expired timestamps."""
    backend = MemoryBackend()
    old = time.time() - 120
    backend._store['key'] = [old]
    _run(backend.cleanup('key', 60))
    ts = _run(backend.get_timestamps('key', 60))
    assert ts == []


def test_memory_backend_clear():
    """Clear resets all data."""
    backend = MemoryBackend()
    _run(backend.add_timestamp('key', time.time(), 60))
    backend.clear()
    ts = _run(backend.get_timestamps('key', 60))
    assert ts == []


def test_get_backend_defaults_to_memory():
    """Default backend is MemoryBackend."""
    backend = get_backend()
    assert isinstance(backend, MemoryBackend)
