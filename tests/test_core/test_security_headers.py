"""Tests for core.http.security_headers."""

import pytest
from core.http.security_headers import SecurityHeadersMiddleware


async def _dummy_app(scope, receive, send):
    """Minimal ASGI app that returns 200 OK."""
    await send(
        {
            'type': 'http.response.start',
            'status': 200,
            'headers': [(b'content-type', b'text/html')],
        }
    )
    await send(
        {
            'type': 'http.response.body',
            'body': b'OK',
        }
    )


def _make_scope(path='/'):
    return {'type': 'http', 'method': 'GET', 'path': path, 'headers': []}


async def _capture_headers(app, scope):
    """Run the ASGI app and return response headers as a dict."""
    captured = {}

    async def send(message):
        if message['type'] == 'http.response.start':
            for k, v in message.get('headers', []):
                captured[k.decode('latin1')] = v.decode('latin1')

    async def receive():
        return {'type': 'http.request', 'body': b''}

    await app(scope, receive, send)
    return captured


# --- Tests ---


@pytest.mark.asyncio
async def test_default_headers_present():
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = await _capture_headers(app, _make_scope())

    assert headers['x-content-type-options'] == 'nosniff'
    assert headers['x-frame-options'] == 'DENY'
    assert headers['x-xss-protection'] == '1; mode=block'
    assert headers['referrer-policy'] == 'strict-origin-when-cross-origin'
    assert 'camera=()' in headers['permissions-policy']


@pytest.mark.asyncio
async def test_hsts_enabled_by_default():
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = await _capture_headers(app, _make_scope())

    assert 'strict-transport-security' in headers
    assert 'max-age=31536000' in headers['strict-transport-security']
    assert 'includeSubDomains' in headers['strict-transport-security']


@pytest.mark.asyncio
async def test_hsts_disabled():
    app = SecurityHeadersMiddleware(_dummy_app, hsts=False)
    headers = await _capture_headers(app, _make_scope())

    assert 'strict-transport-security' not in headers


@pytest.mark.asyncio
async def test_custom_hsts_max_age():
    app = SecurityHeadersMiddleware(_dummy_app, hsts_max_age=3600)
    headers = await _capture_headers(app, _make_scope())

    assert 'max-age=3600' in headers['strict-transport-security']


@pytest.mark.asyncio
async def test_custom_csp_enforced():
    """csp=<string> with csp_report_only=False sends the enforcement header."""
    csp = "default-src 'self'; script-src 'self'"
    app = SecurityHeadersMiddleware(_dummy_app, csp=csp, csp_report_only=False)
    headers = await _capture_headers(app, _make_scope())

    assert headers['content-security-policy'] == csp
    assert 'content-security-policy-report-only' not in headers


@pytest.mark.asyncio
async def test_default_csp_report_only():
    """By default, ship DEFAULT_CSP as Content-Security-Policy-Report-Only."""
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = await _capture_headers(app, _make_scope())

    assert 'content-security-policy-report-only' in headers
    policy = headers['content-security-policy-report-only']
    assert "default-src 'self'" in policy
    assert "script-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    # Enforcement header NOT present when report-only.
    assert 'content-security-policy' not in headers


@pytest.mark.asyncio
async def test_csp_opt_out_with_none():
    """csp=None disables the CSP header entirely."""
    app = SecurityHeadersMiddleware(_dummy_app, csp=None)
    headers = await _capture_headers(app, _make_scope())

    assert 'content-security-policy' not in headers
    assert 'content-security-policy-report-only' not in headers


@pytest.mark.asyncio
async def test_csp_opt_out_with_false():
    """csp=False disables the CSP header entirely."""
    app = SecurityHeadersMiddleware(_dummy_app, csp=False)
    headers = await _capture_headers(app, _make_scope())

    assert 'content-security-policy' not in headers
    assert 'content-security-policy-report-only' not in headers


@pytest.mark.asyncio
async def test_csp_report_uri_appended():
    """csp_report_uri appends a report-uri directive to the policy."""
    app = SecurityHeadersMiddleware(_dummy_app, csp_report_uri='/csp-report')
    headers = await _capture_headers(app, _make_scope())

    policy = headers['content-security-policy-report-only']
    assert 'report-uri /csp-report' in policy


@pytest.mark.asyncio
async def test_default_csp_can_be_enforced():
    """csp='default' + csp_report_only=False sends DEFAULT_CSP as enforcement."""
    app = SecurityHeadersMiddleware(_dummy_app, csp_report_only=False)
    headers = await _capture_headers(app, _make_scope())

    assert 'content-security-policy' in headers
    assert 'content-security-policy-report-only' not in headers
    assert "default-src 'self'" in headers['content-security-policy']


@pytest.mark.asyncio
async def test_custom_header_override():
    app = SecurityHeadersMiddleware(
        _dummy_app,
        headers={
            'X-Frame-Options': 'SAMEORIGIN',
        },
    )
    headers = await _capture_headers(app, _make_scope())

    assert headers['x-frame-options'] == 'SAMEORIGIN'


@pytest.mark.asyncio
async def test_preserves_original_headers():
    app = SecurityHeadersMiddleware(_dummy_app)
    headers = await _capture_headers(app, _make_scope())

    assert headers['content-type'] == 'text/html'


@pytest.mark.asyncio
async def test_skips_non_http():
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

    await app(scope, noop_receive, noop_send)
    assert called == ['websocket']
