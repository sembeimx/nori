"""Tests for core.http.security_headers."""
import asyncio

from core.http.security_headers import SecurityHeadersMiddleware


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _dummy_app(scope, receive, send):
    """Minimal ASGI app that returns 200 OK."""
    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [(b'content-type', b'text/html')],
    })
    await send({
        'type': 'http.response.body',
        'body': b'OK',
    })


def _make_scope(path='/'):
    return {'type': 'http', 'method': 'GET', 'path': path, 'headers': []}


def _capture_headers(app, scope):
    """Run the ASGI app and return response headers as a dict."""
    captured = {}

    async def send(message):
        if message['type'] == 'http.response.start':
            for k, v in message.get('headers', []):
                captured[k.decode('latin1')] = v.decode('latin1')

    async def receive():
        return {'type': 'http.request', 'body': b''}

    _run(app(scope, receive, send))
    return captured


# --- Tests ---

def test_default_headers_present():
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = _capture_headers(app, _make_scope())

    assert headers['x-content-type-options'] == 'nosniff'
    assert headers['x-frame-options'] == 'DENY'
    assert headers['x-xss-protection'] == '1; mode=block'
    assert headers['referrer-policy'] == 'strict-origin-when-cross-origin'
    assert 'camera=()' in headers['permissions-policy']


def test_hsts_enabled_by_default():
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = _capture_headers(app, _make_scope())

    assert 'strict-transport-security' in headers
    assert 'max-age=31536000' in headers['strict-transport-security']
    assert 'includeSubDomains' in headers['strict-transport-security']


def test_hsts_disabled():
    app = SecurityHeadersMiddleware(_dummy_app, hsts=False)
    headers = _capture_headers(app, _make_scope())

    assert 'strict-transport-security' not in headers


def test_custom_hsts_max_age():
    app = SecurityHeadersMiddleware(_dummy_app, hsts_max_age=3600)
    headers = _capture_headers(app, _make_scope())

    assert 'max-age=3600' in headers['strict-transport-security']


def test_csp_header():
    csp = "default-src 'self'; script-src 'self'"
    app = SecurityHeadersMiddleware(_dummy_app, csp=csp)
    headers = _capture_headers(app, _make_scope())

    assert headers['content-security-policy'] == csp


def test_no_csp_by_default():
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = _capture_headers(app, _make_scope())

    assert 'content-security-policy' not in headers


def test_custom_header_override():
    app = SecurityHeadersMiddleware(_dummy_app, headers={
        'X-Frame-Options': 'SAMEORIGIN',
    })
    headers = _capture_headers(app, _make_scope())

    assert headers['x-frame-options'] == 'SAMEORIGIN'


def test_preserves_original_headers():
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = _capture_headers(app, _make_scope())

    assert headers['content-type'] == 'text/html'


def test_skips_non_http():
    """Non-HTTP scopes (websocket, lifespan) pass through untouched."""
    called = []

    async def ws_app(scope, receive, send):
        called.append(scope['type'])

    app = SecurityHeadersMiddleware(ws_app)
    scope = {'type': 'websocket', 'path': '/'}

    async def noop_receive():
        return {}

    async def noop_send(msg):
        pass

    _run(app(scope, noop_receive, noop_send))
    assert called == ['websocket']
