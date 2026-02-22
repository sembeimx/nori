"""Tests for core.http.throttle."""
import asyncio
import time

from core.http.throttle import throttle
from core.http.throttle_backends import get_backend, reset_backend, MemoryBackend


# --- Helpers ---

class FakeClient:
    def __init__(self, host: str = '127.0.0.1'):
        self.host = host


class FakeURL:
    def __init__(self, path: str = '/test'):
        self.path = path


class FakeHeaders:
    def __init__(self, accept: str = 'text/html'):
        self._accept = accept

    def get(self, key: str, default: str = '') -> str:
        if key.lower() == 'accept':
            return self._accept
        return default


class FakeRequest:
    def __init__(self, ip: str = '127.0.0.1', path: str = '/test', accept: str = 'text/html'):
        self.client = FakeClient(ip)
        self.url = FakeURL(path)
        self.headers = FakeHeaders(accept)


class FakeResponse:
    def __init__(self):
        self.headers: dict[str, str] = {}


class FakeController:
    @throttle('3/minute')
    async def action(self, request):
        resp = FakeResponse()
        return resp

    @throttle('2/second')
    async def fast_action(self, request):
        resp = FakeResponse()
        return resp


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def setup_function():
    reset_backend()
    backend = get_backend()
    if isinstance(backend, MemoryBackend):
        backend.clear()


# --- Tests ---

def test_allows_within_limit():
    ctrl = FakeController()
    req = FakeRequest()
    for _ in range(3):
        resp = _run(ctrl.action(req))
        assert not hasattr(resp, 'status_code') or resp.status_code != 429


def test_blocks_over_limit():
    ctrl = FakeController()
    req = FakeRequest()
    for _ in range(3):
        _run(ctrl.action(req))
    resp = _run(ctrl.action(req))
    assert resp.status_code == 429


def test_window_resets():
    ctrl = FakeController()
    req = FakeRequest()

    # Fill the limit with timestamps that are already expired (older than 60s)
    key = '127.0.0.1:/test'
    old = time.time() - 120
    backend = get_backend()
    backend._store[key] = [old, old + 1, old + 2]

    # Should be allowed since all timestamps are outside the window
    resp = _run(ctrl.action(req))
    assert not hasattr(resp, 'status_code') or resp.status_code != 429


def test_different_ips_independent():
    ctrl = FakeController()
    req_a = FakeRequest(ip='10.0.0.1')
    req_b = FakeRequest(ip='10.0.0.2')

    for _ in range(3):
        _run(ctrl.action(req_a))

    # IP A blocked
    resp_a = _run(ctrl.action(req_a))
    assert resp_a.status_code == 429

    # IP B still allowed
    resp_b = _run(ctrl.action(req_b))
    assert not hasattr(resp_b, 'status_code') or resp_b.status_code != 429


def test_response_headers():
    ctrl = FakeController()
    req = FakeRequest()

    resp = _run(ctrl.action(req))
    assert resp.headers['X-RateLimit-Limit'] == '3'
    assert resp.headers['X-RateLimit-Remaining'] == '2'
    assert 'X-RateLimit-Reset' in resp.headers


def test_json_response_on_api_request():
    ctrl = FakeController()
    req = FakeRequest(accept='application/json')

    for _ in range(3):
        _run(ctrl.action(req))
    resp = _run(ctrl.action(req))
    assert resp.status_code == 429
    assert resp.body == b'{"error":"Too Many Requests"}'
