"""Tests for CSRF middleware and helpers.

Baseline before csrf-double-submit: 1039 passed, 1 pre-existing failure
(test_throttle_backends::test_redis_check_and_add_refuses_when_at_limit),
27 CSRF tests (all passing with session-bound implementation).

WU-1: RED suite for signed double-submit cookie contract.
All new tests in this file MUST fail against the session-bound implementation
and MUST pass after WU-2 (the signed double-submit rewrite).

Surviving tests from the old suite that pin INV-004 behavior:
  - test_multipart_without_header_is_refused   (unchanged)
  - test_form_body_cap_is_configurable         (unchanged, still uses monkeypatch)
  - test_websocket_scope_passes_through        (renamed from test_non_http_scope_passes)
  - test_safe_method_passes_through            (new name for GET/HEAD/OPTIONS group)
"""

from __future__ import annotations

import base64
import hmac
import os
from urllib.parse import urlencode

import pytest
from core.auth.csrf import CsrfMiddleware, csrf_field, csrf_token
from core.auth.security import Security


# ---------------------------------------------------------------------------
# ASGI test helpers
# ---------------------------------------------------------------------------


class _Captured:
    """Captures ASGI response messages, including headers."""

    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: list[tuple[bytes, bytes]] = []
        self.body = b''

    async def send(self, message: dict) -> None:
        if message['type'] == 'http.response.start':
            self.status = message['status']
            self.headers = list(message.get('headers', []))
        elif message['type'] == 'http.response.body':
            self.body += message.get('body', b'')

    def set_cookie_headers(self) -> list[str]:
        """Return all Set-Cookie header values as decoded strings."""
        return [v.decode('latin1') for k, v in self.headers if k.lower() == b'set-cookie']


async def _make_receive(body: bytes = b''):
    """Return an ASGI receive callable that returns the given body once."""
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


def _scope(
    method: str = 'GET',
    path: str = '/',
    headers: list[tuple[bytes, bytes]] | None = None,
    content_type: str | None = None,
    cookie: str | None = None,
) -> dict:
    """Build a minimal ASGI HTTP scope without a session key."""
    h: list[tuple[bytes, bytes]] = list(headers or [])
    if content_type:
        h.append((b'content-type', content_type.encode('latin1')))
    if cookie:
        h.append((b'cookie', cookie.encode('latin1')))
    return {
        'type': 'http',
        'method': method,
        'path': path,
        'headers': h,
    }


def _scope_with_cookie(
    method: str,
    cookie_name: str,
    cookie_value: str,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    """Build an ASGI scope with the given cookie; no session key."""
    cookie_str = f'{cookie_name}={cookie_value}'
    h: list[tuple[bytes, bytes]] = list(headers or [])
    h.append((b'cookie', cookie_str.encode('latin1')))
    return {
        'type': 'http',
        'method': method,
        'path': '/',
        'headers': h,
    }


def _signed_cookie(secret: str = 'test-secret', nonce: str | None = None) -> tuple[str, str]:
    """Return (nonce, cookie_value) where cookie_value = '{nonce}.{sig}'."""
    if nonce is None:
        nonce = Security.generate_csrf_token()
    sig = hmac.new(secret.encode(), nonce.encode(), 'sha256').hexdigest()
    return nonce, f'{nonce}.{sig}'


# ---------------------------------------------------------------------------
# REQ-CSRF-003 — raw token acceptance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_accepts_raw_cookie_value():
    """POST with X-CSRF-Token = raw cookie value (what the shim sends) -> 200.

    REQ-CSRF-003 check (2): submitted == cookie_value (raw, not masked).
    Session must NOT be required (REQ-CSRF-014).
    """
    _nonce, cookie_val = _signed_cookie()
    headers = [(b'x-csrf-token', cookie_val.encode())]
    scope = _scope_with_cookie('POST', 'csrftoken', cookie_val, headers=headers)
    # No 'session' key in scope — proving stateless validation
    assert 'session' not in scope

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_validate_accepts_masked_cookie_value():
    """POST with X-CSRF-Token = mask(cookie_value) -> 200 (dual-accept).

    REQ-CSRF-003, design §2: server unmasks before comparing.
    """
    from core.auth.csrf import _mask  # will exist after WU-2

    _nonce, cookie_val = _signed_cookie()
    masked = _mask(cookie_val)
    headers = [(b'x-csrf-token', masked.encode())]
    scope = _scope_with_cookie('POST', 'csrftoken', cookie_val, headers=headers)

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_validate_rejects_signature_invalid_cookie():
    """Cookie = {nonce}.{wrong_sig} + submitted = same cookie -> 403 at check (1).

    REQ-CSRF-002, REQ-CSRF-003: forged cookie (wrong sig under SECRET_KEY).
    This is the writer-attacker defense.
    """
    nonce = Security.generate_csrf_token()
    bad_sig = 'a' * 64  # not a valid HMAC under SECRET_KEY
    forged_cookie = f'{nonce}.{bad_sig}'
    headers = [(b'x-csrf-token', forged_cookie.encode())]
    scope = _scope_with_cookie('POST', 'csrftoken', forged_cookie, headers=headers)

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 403


@pytest.mark.asyncio
async def test_validate_rejects_unsigned_naive_double_submit():
    """Cookie = bare nonce (no .sig), submitted == cookie -> 403.

    REQ-CSRF-002: variant-a (unsigned double-submit) is closed.
    A bare nonce must fail signature check (1) — it has no valid sig part.
    """
    bare_nonce = Security.generate_csrf_token()  # 64 hex chars, no dot
    headers = [(b'x-csrf-token', bare_nonce.encode())]
    scope = _scope_with_cookie('POST', 'csrftoken', bare_nonce, headers=headers)

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 403


@pytest.mark.asyncio
async def test_validate_rejects_mismatched_submission():
    """Valid signed cookie but X-CSRF-Token belongs to a different cookie -> 403 at check (2).

    REQ-CSRF-003: the submitted value must match THIS visitor's cookie.
    """
    _nonce1, cookie_val1 = _signed_cookie()
    _nonce2, cookie_val2 = _signed_cookie()  # different nonce/sig pair
    # Cookie is cookie_val1 but header carries cookie_val2
    headers = [(b'x-csrf-token', cookie_val2.encode())]
    scope = _scope_with_cookie('POST', 'csrftoken', cookie_val1, headers=headers)

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 403


# ---------------------------------------------------------------------------
# REQ-CSRF-009 — BREACH masking: per-render masks differ, both validate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_masked_token_differs_per_render():
    """Two csrf_field(request) calls produce different masked values
    for the same cookie, but both must unmasked-equal the cookie value.

    REQ-CSRF-009, design §2.
    """
    from core.auth.csrf import _unmask  # will exist after WU-2

    _nonce, cookie_val = _signed_cookie()

    class _FakeRequest:
        cookies = {'csrftoken': cookie_val}
        scope: dict = {}

    req = _FakeRequest()
    html1 = csrf_field(req)
    html2 = csrf_field(req)

    # Extract the masked value from the hidden input
    import re

    def _extract_value(html: str) -> str:
        m = re.search(r'value="([^"]+)"', html)
        assert m, f'No value= in: {html!r}'
        return m.group(1)

    val1 = _extract_value(html1)
    val2 = _extract_value(html2)

    # Per-render masks produce different ciphertexts
    assert val1 != val2, 'Two renders should produce different masked values (BREACH resistance)'

    # Both unmask to the same raw cookie value
    assert _unmask(val1) == cookie_val
    assert _unmask(val2) == cookie_val


# ---------------------------------------------------------------------------
# REQ-CSRF-014 — no session dependency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_no_session_dependency():
    """Validation passes with scope['session'] absent (stateless).

    REQ-CSRF-014.
    """
    _nonce, cookie_val = _signed_cookie()
    headers = [(b'x-csrf-token', cookie_val.encode())]
    scope = _scope_with_cookie('POST', 'csrftoken', cookie_val, headers=headers)
    # Explicitly confirm no session key
    assert 'session' not in scope

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 200


# ---------------------------------------------------------------------------
# REQ-CSRF-003 — header token short-circuits body read (INV-004 preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_token_path_still_short_circuits():
    """X-CSRF-Token supplied -> body NOT read; 200 returned.

    REQ-CSRF-003, INV-004.
    """
    _nonce, cookie_val = _signed_cookie()
    headers = [(b'x-csrf-token', cookie_val.encode())]
    scope = _scope_with_cookie(
        'POST', 'csrftoken', cookie_val, headers=headers
    )

    body_read = {'count': 0}

    async def tracking_receive():
        body_read['count'] += 1
        return {'type': 'http.request', 'body': b'_csrf_token=irrelevant', 'more_body': False}

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, tracking_receive, cap.send)
    assert cap.status == 200
    # The middleware should NOT have consumed the body for header validation
    assert body_read['count'] == 0, 'Middleware must not read body when X-CSRF-Token header is present'


# ---------------------------------------------------------------------------
# REQ-CSRF-003 — no cookie -> 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_cookie_rejects():
    """Unsafe method with no CSRF cookie present -> 403 (no nonce to verify).

    REQ-CSRF-003.
    """
    # No cookie in scope headers at all
    scope = _scope('POST', content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    body = urlencode({'_csrf_token': 'anything'}).encode()
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 403


# ---------------------------------------------------------------------------
# REQ-CSRF-007 / REQ-CSRF-006 — body cap default = 10 MB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_form_body_cap_default_is_10mb():
    """_form_body_cap() returns 10 * 1024 * 1024; a 1.5 MB body is accepted.

    REQ-CSRF-006, REQ-CSRF-007: default cap bumped from 1 MiB to 10 MB.
    """
    from core.auth.csrf import _form_body_cap

    assert _form_body_cap() == 10 * 1024 * 1024

    # A body slightly over old 1 MiB cap but under 10 MB must now be accepted
    _nonce, cookie_val = _signed_cookie()
    # 1.5 MB urlencoded body with the valid token appended
    large_prefix = 'x=' + 'a' * (1_500_000 - 100)
    token_part = f'&_csrf_token={cookie_val}'
    body = (large_prefix + token_part).encode()
    # Confirm body is between old cap (1 MiB) and new cap (10 MB)
    assert 1 * 1024 * 1024 < len(body) < 10 * 1024 * 1024

    scope = _scope_with_cookie('POST', 'csrftoken', cookie_val)
    scope['headers'].append((b'content-type', b'application/x-www-form-urlencoded'))

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    # Must NOT be 413 — the new cap allows this size
    assert cap.status == 200, f'Expected 200 (body within 10 MB cap) but got {cap.status}'


@pytest.mark.asyncio
async def test_form_body_cap_is_configurable(monkeypatch):
    """CSRF_FORM_MAX_BODY_SIZE override works via config.get.

    REQ-CSRF-006.
    """
    from core.auth import csrf as csrf_module

    monkeypatch.setattr(csrf_module, '_form_body_cap', lambda: 256)
    body = b'a' * 1024  # over the lowered cap
    scope = _scope('POST', content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 413


# ---------------------------------------------------------------------------
# REQ-CSRF-005 — multipart refusal (INV-004 unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multipart_without_header_is_refused():
    """Multipart bodies must NOT be buffered — clients must send X-CSRF-Token.

    REQ-CSRF-005, INV-004.
    """
    _nonce, cookie_val = _signed_cookie()
    body = (
        b'------WebKitFormBoundary7MA4YWxk\r\n'
        b'Content-Disposition: form-data; name="_csrf_token"\r\n'
        b'\r\n' + cookie_val.encode() + b'\r\n------WebKitFormBoundary7MA4YWxk--\r\n'
    )
    scope = _scope_with_cookie(
        'POST',
        'csrftoken',
        cookie_val,
        headers=[(b'content-type', b'multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxk')],
    )
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 403


# ---------------------------------------------------------------------------
# REQ-CSRF-006 — urlencoded form body paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_urlencoded_form_masked_token_validates():
    """POST with urlencoded body containing _csrf_token = mask(cookie_value) -> 200.

    REQ-CSRF-006, REQ-CSRF-003.
    """
    from core.auth.csrf import _mask

    _nonce, cookie_val = _signed_cookie()
    masked = _mask(cookie_val)
    body = urlencode({'_csrf_token': masked}).encode()
    scope = _scope_with_cookie(
        'POST',
        'csrftoken',
        cookie_val,
        headers=[(b'content-type', b'application/x-www-form-urlencoded')],
    )

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_urlencoded_form_missing_token_is_403():
    """POST with urlencoded body without _csrf_token -> 403.

    REQ-CSRF-006.
    """
    _nonce, cookie_val = _signed_cookie()
    body = urlencode({'name': 'alice', 'age': '30'}).encode()
    scope = _scope_with_cookie(
        'POST',
        'csrftoken',
        cookie_val,
        headers=[(b'content-type', b'application/x-www-form-urlencoded')],
    )

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(body), cap.send)
    assert cap.status == 403


# ---------------------------------------------------------------------------
# REQ-CSRF-008 — exempt paths and safe methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exempt_path_skips_validation():
    """POST to an exempt path with no token -> 200 (no 403).

    REQ-CSRF-008.
    """
    scope = _scope('POST', path='/api/webhook', content_type='application/x-www-form-urlencoded')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app, exempt_paths=['/api/webhook'])
    await mw(scope, await _make_receive(b'no_token=1'), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_safe_method_passes_through():
    """GET bypasses CSRF validation entirely.

    REQ-CSRF-008.
    """
    scope = _scope('GET')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)
    assert cap.status == 200


@pytest.mark.asyncio
async def test_websocket_scope_passes_through():
    """scope['type'] == 'websocket' -> passed through without CSRF logic.

    REQ-CSRF-008.
    """
    called = False

    async def ws_app(scope, receive, send):
        nonlocal called
        called = True

    mw = CsrfMiddleware(ws_app)
    await mw({'type': 'websocket'}, None, None)
    assert called


# ---------------------------------------------------------------------------
# REQ-CSRF-004 — JSON content type without header -> 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_content_type_without_header_is_403():
    """POST with Content-Type: application/json, no X-CSRF-Token -> 403 without reading body.

    REQ-CSRF-004.
    """
    _nonce, cookie_val = _signed_cookie()
    scope = _scope_with_cookie(
        'POST',
        'csrftoken',
        cookie_val,
        headers=[(b'content-type', b'application/json')],
    )

    body_read = {'count': 0}

    async def tracking_receive():
        body_read['count'] += 1
        return {'type': 'http.request', 'body': b'{"key": "value"}', 'more_body': False}

    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, tracking_receive, cap.send)
    assert cap.status == 403
    assert body_read['count'] == 0, 'Middleware must not read body for JSON without header'


# ---------------------------------------------------------------------------
# REQ-CSRF-001, REQ-CSRF-002 — cookie issuance via send-wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csrf_cookie_set_when_absent():
    """GET with no CSRF cookie -> response Set-Cookie includes csrftoken={nonce}.{sig}
    with a verifiable HMAC signature.

    REQ-CSRF-001, REQ-CSRF-002.
    """
    scope = _scope('GET')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)

    assert cap.status == 200
    set_cookies = cap.set_cookie_headers()
    assert set_cookies, 'Expected at least one Set-Cookie header on first GET'

    csrf_cookie = next((c for c in set_cookies if 'csrftoken=' in c), None)
    assert csrf_cookie is not None, f'No csrftoken Set-Cookie found; got: {set_cookies}'

    # Extract the cookie value and verify its signature
    cookie_val = csrf_cookie.split('csrftoken=')[1].split(';')[0].strip()
    assert '.' in cookie_val, f'Cookie must be nonce.sig format; got: {cookie_val!r}'

    nonce_part, sig_part = cookie_val.rsplit('.', 1)
    import settings

    expected_sig = hmac.new(settings.SECRET_KEY.encode(), nonce_part.encode(), 'sha256').hexdigest()
    assert hmac.compare_digest(sig_part, expected_sig), 'Cookie signature must verify under SECRET_KEY'


@pytest.mark.asyncio
async def test_csrf_cookie_not_reissued_when_present():
    """GET with a valid signed CSRF cookie -> no new Set-Cookie for cookie name.

    REQ-CSRF-001, Decision 3 (no rotation).
    """
    import settings

    _nonce, cookie_val = _signed_cookie(secret=settings.SECRET_KEY)
    scope = _scope_with_cookie('GET', 'csrftoken', cookie_val)
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)

    assert cap.status == 200
    csrf_set_cookies = [c for c in cap.set_cookie_headers() if 'csrftoken=' in c]
    assert not csrf_set_cookies, (
        f'Should NOT re-issue cookie when valid one is present; got Set-Cookie: {csrf_set_cookies}'
    )


@pytest.mark.asyncio
async def test_csrf_cookie_reissued_when_signature_invalid():
    """GET with a cookie that fails signature check -> fresh valid cookie issued.

    REQ-CSRF-001, REQ-CSRF-002: invalid cookie treated as absent.
    """
    nonce = Security.generate_csrf_token()
    bad_sig = 'b' * 64
    bad_cookie = f'{nonce}.{bad_sig}'
    scope = _scope_with_cookie('GET', 'csrftoken', bad_cookie)
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)

    assert cap.status == 200
    csrf_set_cookies = [c for c in cap.set_cookie_headers() if 'csrftoken=' in c]
    assert csrf_set_cookies, 'Must re-issue a fresh cookie when the existing one has an invalid signature'


@pytest.mark.asyncio
async def test_host_prefix_forces_secure_path_no_domain(monkeypatch):
    """CSRF_COOKIE_NAME='__Host-csrftoken' -> Set-Cookie includes Secure; Path=/; no Domain=.

    REQ-CSRF-001, Decision 4.
    """
    from core.conf import config

    monkeypatch.setattr(config, 'get', lambda key, default=None: {
        'CSRF_COOKIE_NAME': '__Host-csrftoken',
        'CSRF_COOKIE_SECURE': True,
        'CSRF_COOKIE_SAMESITE': 'Lax',
        'CSRF_COOKIE_HTTPONLY': False,
        'CSRF_COOKIE_PATH': '/',
        'CSRF_COOKIE_MAX_AGE': None,
    }.get(key, default))

    scope = _scope('GET')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)

    csrf_set_cookies = [c for c in cap.set_cookie_headers() if '__Host-csrftoken=' in c]
    assert csrf_set_cookies, 'Expected __Host-csrftoken Set-Cookie header'
    cookie_str = csrf_set_cookies[0]

    assert 'Secure' in cookie_str, f'__Host- cookie must have Secure; got: {cookie_str!r}'
    assert 'Path=/' in cookie_str, f'__Host- cookie must have Path=/; got: {cookie_str!r}'
    assert 'Domain=' not in cookie_str, f'__Host- cookie must NOT have Domain=; got: {cookie_str!r}'


@pytest.mark.asyncio
async def test_samesite_default_is_lax():
    """No CSRF_COOKIE_SAMESITE setting -> cookie SameSite=Lax.

    REQ-CSRF-013.
    """
    scope = _scope('GET')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)

    csrf_set_cookies = [c for c in cap.set_cookie_headers() if 'csrftoken=' in c]
    assert csrf_set_cookies, 'Expected Set-Cookie header'
    assert 'SameSite=Lax' in csrf_set_cookies[0], (
        f'Default SameSite must be Lax; got: {csrf_set_cookies[0]!r}'
    )


@pytest.mark.asyncio
async def test_pending_cookie_seeded_in_scope_before_handler():
    """On first GET (no cookie), scope['csrf_pending_cookie'] is set before the inner app runs.

    REQ-CSRF-009, design §7 first-request coordination.
    """
    scope = _scope('GET')
    pending_seen: list[str] = []

    async def capturing_app(scope, receive, send):
        val = scope.get('csrf_pending_cookie', '')
        pending_seen.append(val)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'OK'})

    mw = CsrfMiddleware(capturing_app)
    await mw(scope, await _make_receive(), _Captured().send)

    assert pending_seen, 'Inner app was never called'
    assert pending_seen[0], 'csrf_pending_cookie must be set before the handler runs'
    # Verify the pending value has the correct signed structure
    pending = pending_seen[0]
    assert '.' in pending, f'Pending cookie must be nonce.sig; got: {pending!r}'


@pytest.mark.asyncio
async def test_settings_default_cookie_name():
    """No CSRF_COOKIE_NAME in settings -> uses 'csrftoken' without AttributeError.

    REQ-CSRF-013, INV-029.
    """
    scope = _scope('GET')
    cap = _Captured()
    mw = CsrfMiddleware(_passthrough_app)
    await mw(scope, await _make_receive(), cap.send)

    assert cap.status == 200
    csrf_set_cookies = [c for c in cap.set_cookie_headers() if c.startswith('csrftoken=')]
    assert csrf_set_cookies, 'Default cookie name must be csrftoken'


# ---------------------------------------------------------------------------
# REQ-CSRF-009, REQ-CSRF-010 — csrf_field and csrf_token helpers (jinja tests)
# ---------------------------------------------------------------------------


def test_csrf_field_accepts_request():
    """csrf_field(request) reads request.cookies[CSRF_COOKIE_NAME] and emits a masked input.

    REQ-CSRF-009.
    """
    _nonce, cookie_val = _signed_cookie()

    class _FakeRequest:
        cookies = {'csrftoken': cookie_val}
        scope: dict = {}

    html = csrf_field(_FakeRequest())
    assert 'name="_csrf_token"' in html
    assert '<input' in html
    # The value should NOT be the raw cookie (it should be masked)
    assert f'value="{cookie_val}"' not in html, 'csrf_field must return a masked value, not the raw cookie'


def test_csrf_field_uses_pending_cookie_when_no_cookie():
    """First GET: scope['csrf_pending_cookie'] set -> csrf_field returns masked form of that value.

    REQ-CSRF-009.
    """
    _nonce, cookie_val = _signed_cookie()

    class _FakeRequest:
        cookies: dict = {}  # no cookie in request
        scope = {'csrf_pending_cookie': cookie_val}

    html = csrf_field(_FakeRequest())
    assert 'name="_csrf_token"' in html
    assert html != '<input type="hidden" name="_csrf_token" value="">', (
        'On first request, csrf_field must use scope[csrf_pending_cookie], not return empty'
    )


def test_csrf_token_returns_raw_cookie_value():
    """csrf_token(request) returns the full {nonce}.{sig} string verbatim.

    REQ-CSRF-010.
    """
    _nonce, cookie_val = _signed_cookie()

    class _FakeRequest:
        cookies = {'csrftoken': cookie_val}
        scope: dict = {}

    result = csrf_token(_FakeRequest())
    assert result == cookie_val, f'csrf_token must return the raw cookie value; got {result!r}'


def test_csrf_token_returns_pending_cookie_on_first_visit():
    """No cookie, scope['csrf_pending_cookie'] set -> csrf_token returns that value.

    REQ-CSRF-010.
    """
    _nonce, cookie_val = _signed_cookie()

    class _FakeRequest:
        cookies: dict = {}
        scope = {'csrf_pending_cookie': cookie_val}

    result = csrf_token(_FakeRequest())
    assert result == cookie_val
