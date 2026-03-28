"""Tests for CSRF middleware and helpers."""
import pytest
from urllib.parse import urlencode
from core.auth.csrf import CsrfMiddleware, csrf_field, csrf_token, _CSRF_SESSION_KEY
from core.auth.security import Security


# ---------------------------------------------------------------------------
# Helpers to simulate ASGI calls
# ---------------------------------------------------------------------------

class _Captured:
    """Captures ASGI response messages."""
    def __init__(self):
        self.status = None
        self.body = b''

    async def send(self, message):
        if message['type'] == 'http.response.start':
            self.status = message['status']
        elif message['type'] == 'http.response.body':
            self.body += message.get('body', b'')


async def _make_receive(body: bytes = b''):
    """Return an ASGI receive callable that returns the given body."""
    sent = False
    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        return {'type': 'http.disconnect'}
    return receive


async def _passthrough_app(scope, receive, send):
    """Dummy ASGI app that returns 200 OK."""
    await send({'type': 'http.response.start', 'status': 200, 'headers': []})
    await send({'type': 'http.response.body', 'body': b'OK'})


def _scope(method='GET', path='/', session=None, headers=None, content_type=None):
    """Build a minimal ASGI HTTP scope."""
    h = list(headers or [])
    if content_type:
        h.append((b'content-type', content_type.encode('latin1')))
    s = {
        'type': 'http',
        'method': method,
        'path': path,
        'headers': h,
    }
    if session is not None:
        s['session'] = session
    return s


# ---------------------------------------------------------------------------
# csrf_field / csrf_token helpers
# ---------------------------------------------------------------------------

def test_csrf_field_returns_html():
    session = {_CSRF_SESSION_KEY: 'abc123'}
    html = csrf_field(session)
    assert 'value="abc123"' in html
    assert 'name="_csrf_token"' in html
    assert '<input' in html


def test_csrf_field_escapes_xss():
    session = {_CSRF_SESSION_KEY: '"><script>alert(1)</script>'}
    html = csrf_field(session)
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_csrf_field_empty_session():
    html = csrf_field({})
    assert 'value=""' in html


def test_csrf_token_returns_raw_string():
    session = {_CSRF_SESSION_KEY: 'mytoken'}
    assert csrf_token(session) == 'mytoken'


def test_csrf_token_empty_session():
    assert csrf_token({}) == ''


# ---------------------------------------------------------------------------
# Middleware: safe methods pass through
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_request_passes():
    session = {}
    scope = _scope('GET', session=session)
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 200
    # Token should be auto-generated in session
    assert _CSRF_SESSION_KEY in session


@pytest.mark.asyncio
async def test_head_request_passes():
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(_scope('HEAD', session={}), await _make_receive(), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_options_request_passes():
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(_scope('OPTIONS', session={}), await _make_receive(), cap.send)
    assert cap.status == 200


# ---------------------------------------------------------------------------
# Middleware: POST without token -> 403
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_without_token_returns_403():
    session = {_CSRF_SESSION_KEY: Security.generate_csrf_token()}
    body = urlencode({'name': 'test'}).encode()
    scope = _scope('POST', session=session, content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 403


@pytest.mark.asyncio
async def test_post_with_wrong_token_returns_403():
    session = {_CSRF_SESSION_KEY: Security.generate_csrf_token()}
    body = urlencode({'_csrf_token': 'wrong-token'}).encode()
    scope = _scope('POST', session=session, content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 403


# ---------------------------------------------------------------------------
# Middleware: valid token passes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_with_valid_token_passes():
    token = Security.generate_csrf_token()
    session = {_CSRF_SESSION_KEY: token}
    body = urlencode({'_csrf_token': token}).encode()
    scope = _scope('POST', session=session, content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_post_with_header_token_passes():
    token = Security.generate_csrf_token()
    session = {_CSRF_SESSION_KEY: token}
    headers = [(b'x-csrf-token', token.encode())]
    scope = _scope('POST', session=session, headers=headers,
                   content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(b''), cap.send)
    assert cap.status == 200


# ---------------------------------------------------------------------------
# JSON bypass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_json_post_bypasses_csrf():
    session = {_CSRF_SESSION_KEY: Security.generate_csrf_token()}
    scope = _scope('POST', session=session, content_type='application/json')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(b'{"key": "value"}'), cap.send)
    assert cap.status == 200


# ---------------------------------------------------------------------------
# Exempt paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exempt_path_passes():
    session = {_CSRF_SESSION_KEY: Security.generate_csrf_token()}
    scope = _scope('POST', path='/api/webhook', session=session,
                   content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app, exempt_paths={'/api/webhook'})
    await mw(scope, await _make_receive(b'no_token=1'), cap.send)
    assert cap.status == 200


# ---------------------------------------------------------------------------
# Multipart form data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multipart_token_extraction():
    token = Security.generate_csrf_token()
    session = {_CSRF_SESSION_KEY: token}
    boundary = '----WebKitFormBoundary7MA4YWxk'
    body = (
        f'------WebKitFormBoundary7MA4YWxk\r\n'
        f'Content-Disposition: form-data; name="_csrf_token"\r\n'
        f'\r\n'
        f'{token}\r\n'
        f'------WebKitFormBoundary7MA4YWxk\r\n'
        f'Content-Disposition: form-data; name="title"\r\n'
        f'\r\n'
        f'Hello\r\n'
        f'------WebKitFormBoundary7MA4YWxk--\r\n'
    ).encode()
    scope = _scope('POST', session=session,
                   content_type=f'multipart/form-data; boundary={boundary}')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_multipart_quoted_boundary():
    token = Security.generate_csrf_token()
    session = {_CSRF_SESSION_KEY: token}
    boundary = '----myboundary'
    body = (
        f'------myboundary\r\n'
        f'Content-Disposition: form-data; name="_csrf_token"\r\n'
        f'\r\n'
        f'{token}\r\n'
        f'------myboundary--\r\n'
    ).encode()
    # Boundary with quotes
    scope = _scope('POST', session=session,
                   content_type=f'multipart/form-data; boundary="{boundary}"')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 200


# ---------------------------------------------------------------------------
# Non-HTTP scope passes through
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_http_scope_passes():
    cap = _Captured()
    called = False

    async def ws_app(scope, receive, send):
        nonlocal called
        called = True

    mw = CsrfMiddleware(ws_app)
    await mw({'type': 'websocket'}, None, None)
    assert called


# ---------------------------------------------------------------------------
# No session -> 403
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_without_session_returns_403():
    scope = _scope('POST', content_type='application/x-www-form-urlencoded')
    # No session key in scope
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(b'_csrf_token=x'), cap.send)
    assert cap.status == 403


# ---------------------------------------------------------------------------
# Body size limit -> 413
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_large_body_returns_413():
    # 10MB + 1 byte
    large_body = b'a' * (10 * 1024 * 1024 + 1)
    scope = _scope('POST', session={}, content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(large_body), cap.send)
    assert cap.status == 413
    assert b'Too Large' in cap.body
