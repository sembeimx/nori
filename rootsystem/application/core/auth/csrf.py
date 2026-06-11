"""
CSRF Middleware for Starlette — signed double-submit cookie (v2.0.0).

Replaces the session-bound synchronizer-token approach (v1.x) with an
OWASP *Signed Double-Submit Cookie*. The middleware is now stateless:
it no longer reads or writes the session for CSRF purposes.

Wire format:
    Cookie value = ``{nonce}.{sig}`` where:
        nonce = secrets.token_hex(32)   (64 hex chars)
        sig   = HMAC-SHA256(SECRET_KEY, nonce) hexdigest  (64 hex chars)
    The two parts are joined by a literal ``.`` and split at the **last** ``.``.

    Submitted token = the cookie value, accepted in two forms:
        * **Raw**    — copied verbatim by the JS shim or X-CSRF-Token header clients.
        * **Masked** — BREACH XOR envelope produced by ``csrf_field``; server
          unmasks before comparing (per-render mask prevents compression oracles).

Validation (two checks, both constant-time):
    (1) Cookie integrity: recompute HMAC(SECRET_KEY, nonce) over the cookie's
        nonce part; reject with 403 if the cookie's sig does not match.
        This blocks cookie-writer attackers who cannot forge a valid HMAC
        without SECRET_KEY.
    (2) Double-submit match: unmask the submitted value if masked; reject with
        403 if it does not equal the full cookie value.

Body buffering trade-off:
    To extract a CSRF token from a form body the middleware must buffer the
    entire body — which would defeat Starlette's streaming for file uploads.
    The following rules avoid that:

    * If ``X-CSRF-Token`` is present, the body is NOT read (zero buffer).
      Recommended for AJAX / fetch / non-browser clients.
    * For ``application/x-www-form-urlencoded`` (small forms), the body
      is buffered up to ``CSRF_FORM_MAX_BODY_SIZE`` (default **10 MB**).
      Real urlencoded forms rarely exceed a few KB; the cap was bumped
      from 1 MiB to 10 MB to match documented behavior (INV-015 instance
      closed in v2.0.0).
    * For ``multipart/form-data``, the middleware refuses to buffer.
      Multipart is the file-upload path — clients MUST send the token via
      ``X-CSRF-Token`` header so validation can proceed without consuming
      the upload stream.
    * For ``application/json``, the middleware always rejects without
      reading the body when the header is absent.

Send-wrapper (cookie issuance):
    The middleware intercepts ``http.response.start`` and appends a
    ``Set-Cookie`` header when the request carried no valid CSRF cookie
    (i.e., ``scope['csrf_pending_cookie']`` is set).  The body is never
    buffered by the send-wrapper (INV-002).

First-request coordination:
    When no valid CSRF cookie is present, the middleware generates the
    full ``{nonce}.{sig}`` cookie value **before** calling downstream and
    seeds it in ``scope['csrf_pending_cookie']``.  ``csrf_field`` and
    ``csrf_token`` fall back to this value so that the rendered hidden
    input and the issued ``Set-Cookie`` carry the same value in the same
    request cycle.

CSRF ⟂ session-revocation boundary:
    The CSRF cookie is stateless and does not interact with session
    revocation (INV-016).  A user with a revoked session still holds a
    valid CSRF cookie; auth decorators (``login_required``, etc.) block
    the request at the authorization layer before any handler runs.
    Do NOT file "CSRF cookie outlives session revocation" as a finding.
"""

from __future__ import annotations

import base64
import hmac
import secrets
from collections.abc import MutableMapping
from hashlib import sha256
from html import escape as _html_escape
from typing import Protocol
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.auth.security import Security
from core.conf import config
from core.logger import get_logger

log = get_logger('csrf')

_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}

# Default urlencoded body cap — bumped from 1 MiB to 10 MB to match
# documented behavior.  INV-015 instance closed in v2.0.0.
_DEFAULT_FORM_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

# BREACH mask length in bytes.  Each render produces:
#     _MASK_LEN bytes  ||  XOR(raw, _MASK_LEN-bytes-cycled)
# → total bytes = _MASK_LEN + len(raw) → base64 of that.
# For a 129-char raw cookie value: 32 + 129 = 161 bytes → 216 base64 chars.
_MASK_LEN = 32


# ---------------------------------------------------------------------------
# Settings helpers (all via config.get — INV-029)
# ---------------------------------------------------------------------------


def _form_body_cap() -> int:
    """Resolve the per-request urlencoded buffer cap from settings."""
    return int(config.get('CSRF_FORM_MAX_BODY_SIZE', _DEFAULT_FORM_BODY_SIZE))


def _cookie_name() -> str:
    return str(config.get('CSRF_COOKIE_NAME', 'csrftoken'))


# One-time guard so the __Host-/insecure misconfiguration warning fires once per
# process, not on every cookie issuance (design §5 — loud, not spammy).
_host_prefix_warned = False


def _warn_host_prefix_insecure_once() -> None:
    """Emit a one-time ``log.warning`` when ``CSRF_COOKIE_NAME`` uses the ``__Host-``
    prefix while the configured ``CSRF_COOKIE_SECURE`` is ``False``.

    The middleware still force-secures the cookie (a ``__Host-`` cookie requires
    ``Secure`` or the browser rejects it); this warning is *in addition* to that,
    so the misconfiguration is loud rather than silently corrected (design §5,
    Decision 4).
    """
    global _host_prefix_warned
    if _host_prefix_warned:
        return
    if not _cookie_name().startswith('__Host-'):
        return
    # Read the operator's RAW intent (default True), NOT the forced value.
    configured_secure = bool(config.get('CSRF_COOKIE_SECURE', not config.get('DEBUG', False)))
    if configured_secure:
        return
    _host_prefix_warned = True
    log.warning(
        'CSRF_COOKIE_NAME uses the __Host- prefix but CSRF_COOKIE_SECURE is False. '
        'A __Host- cookie REQUIRES Secure; the middleware is force-securing the cookie, '
        'but you should set CSRF_COOKIE_SECURE=True (and serve over HTTPS) to match.'
    )


def _cookie_secure() -> bool:
    name = _cookie_name()
    if name.startswith('__Host-'):
        _warn_host_prefix_insecure_once()
        return True  # __Host- requires Secure (forced; warning emitted above)
    return bool(config.get('CSRF_COOKIE_SECURE', not config.get('DEBUG', False)))


def _cookie_samesite() -> str:
    return str(config.get('CSRF_COOKIE_SAMESITE', 'Lax'))


def _cookie_httponly() -> bool:
    # MUST default False — the JS shim reads document.cookie
    return bool(config.get('CSRF_COOKIE_HTTPONLY', False))


def _cookie_path() -> str:
    name = _cookie_name()
    if name.startswith('__Host-'):
        return '/'  # __Host- requires Path=/
    return str(config.get('CSRF_COOKIE_PATH', '/'))


def _cookie_max_age() -> int | None:
    value = config.get('CSRF_COOKIE_MAX_AGE', None)
    return int(value) if value is not None else None


# ---------------------------------------------------------------------------
# HMAC helpers (REQ-CSRF-002, design §7)
# ---------------------------------------------------------------------------


def _sign_nonce(nonce: str) -> str:
    """Return HMAC-SHA256(SECRET_KEY, nonce) as a hex string."""
    key = config.SECRET_KEY.encode('utf-8')
    return hmac.new(key, nonce.encode('utf-8'), sha256).hexdigest()


def _cookie_signature_valid(cookie_val: str) -> bool:
    """Return True iff ``cookie_val`` is a well-formed ``{nonce}.{sig}``
    whose sig matches HMAC-SHA256(SECRET_KEY, nonce).

    Returns False for any malformed or forged value.
    """
    if not cookie_val or '.' not in cookie_val:
        return False
    # Split at the LAST dot so nonces that happen to contain dots are handled
    nonce, _, sig = cookie_val.rpartition('.')
    if not nonce or not sig:
        return False
    try:
        expected = _sign_nonce(nonce)
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# BREACH masking helpers (design §2, REQ-CSRF-009)
#
# Mask envelope: _MASK_LEN random bytes prepended to XOR(raw_bytes, mask)
#     where mask = os.urandom(_MASK_LEN) cycled over len(raw_bytes)
# Base64-encode the whole envelope to get a URL-safe printable string.
#
# _looks_masked discriminator (what the code ACTUALLY checks):
#     Raw cookie form:   exactly _RAW_COOKIE_LEN (129) chars AND every char in
#                        [0-9a-fA-F.]  (64 hex + '.' + 64 hex). No dot-POSITION
#                        check is performed — length + charset alone are decisive.
#     Masked form:       a base64 envelope of (_MASK_LEN + len(raw)) bytes, whose
#                        length is therefore always ≡ 0 (mod 4) after padding and,
#                        for the 129-char raw cookie, is 216 chars (> 129).
#     The two forms are DISJOINT because:
#       - A 129-char string is not ≡ 0 (mod 4) (129 = 4*32 + 1), so it can never
#         be a (padded) base64 envelope length — the masked branch can't produce it.
#       - The masked base64 of a 161-byte envelope is 216 chars and carries
#         upper-case letters and/or +/= absent from the raw [0-9a-fA-F.] charset.
#     Hence a value matching the raw length+charset is unambiguously raw, and
#     anything else is treated as masked.
# ---------------------------------------------------------------------------

_RAW_COOKIE_CHARSET = frozenset('0123456789abcdefABCDEF.')
_RAW_COOKIE_LEN = 129  # 64 hex + '.' + 64 hex


def _mask(raw: str) -> str:
    """Return a base64-encoded BREACH-masked form of ``raw``.

    Each call produces a different ciphertext for the same ``raw`` value
    (per-render random mask).  ``_unmask`` is the inverse.
    """
    raw_bytes = raw.encode('utf-8')
    mask_bytes = secrets.token_bytes(_MASK_LEN)
    # XOR raw_bytes against mask_bytes cyclically
    xored = bytes(b ^ mask_bytes[i % _MASK_LEN] for i, b in enumerate(raw_bytes))
    envelope = mask_bytes + xored
    return base64.b64encode(envelope).decode('ascii')


def _unmask(masked: str) -> str:
    """Reverse ``_mask``.  Raises ``ValueError`` on invalid input."""
    try:
        envelope = base64.b64decode(masked)
    except Exception as exc:
        raise ValueError(f'Invalid base64 in masked CSRF token: {exc}') from exc
    if len(envelope) <= _MASK_LEN:
        raise ValueError('Masked CSRF token envelope is too short')
    mask_bytes = envelope[:_MASK_LEN]
    xored = envelope[_MASK_LEN:]
    raw_bytes = bytes(b ^ mask_bytes[i % _MASK_LEN] for i, b in enumerate(xored))
    return raw_bytes.decode('utf-8')


def _looks_masked(val: str) -> bool:
    """Return True iff ``val`` looks like a BREACH-masked token.

    Discriminates between:
        * Raw cookie ``{nonce}.{sig}``:  exactly 129 chars, charset [0-9a-fA-F.]
        * Masked envelope:              base64 string, always longer than 129 chars

    Neither direction can produce a false positive:
        - A raw 129-char hex.hex value is not a valid base64 encoding of a
          161-byte sequence (which encodes to 216 base64 chars).
        - A base64-encoded 161-byte sequence is always 216 chars and contains
          upper-case letters and/or +/= that are absent from [0-9a-f.].

    Returns False (treat as raw) if neither form matches unambiguously.
    """
    if not val:
        return False
    # Raw cookie: exactly _RAW_COOKIE_LEN chars AND every char in [0-9a-fA-F.].
    # (No dot-position check — length + charset alone make raw and masked disjoint,
    #  since 129 is not ≡ 0 mod 4 and so is never a valid base64 envelope length.)
    if len(val) == _RAW_COOKIE_LEN and all(c in _RAW_COOKIE_CHARSET for c in val):
        return False
    # Anything else (longer, or carrying base64-only chars) is treated as masked.
    return True


# ---------------------------------------------------------------------------
# Set-Cookie header builder
# ---------------------------------------------------------------------------


def _build_set_cookie_header(cookie_val: str) -> bytes:
    """Build the ``Set-Cookie`` header bytes for the CSRF cookie.

    Enforces ``__Host-`` constraints when the configured cookie name starts
    with ``__Host-``: forces ``Secure``, ``Path=/``, and suppresses ``Domain``.
    """
    name = _cookie_name()
    parts = [f'{name}={cookie_val}']

    # Path (always included; forced to / for __Host-)
    path = _cookie_path()
    parts.append(f'Path={path}')

    # Secure
    if _cookie_secure():
        parts.append('Secure')

    # HttpOnly
    if _cookie_httponly():
        parts.append('HttpOnly')

    # SameSite
    samesite = _cookie_samesite()
    if samesite:
        parts.append(f'SameSite={samesite}')

    # Max-Age (omit for session cookie)
    max_age = _cookie_max_age()
    if max_age is not None:
        parts.append(f'Max-Age={max_age}')

    # __Host- prefix: NO Domain attribute (browser would reject it)
    # For non-__Host- cookies, Domain is intentionally omitted (host-only scope)
    # to avoid inadvertent subdomain sharing.

    return ('; '.join(parts)).encode('latin1')


# ---------------------------------------------------------------------------
# CsrfMiddleware
# ---------------------------------------------------------------------------


class CsrfMiddleware:
    """ASGI middleware enforcing signed double-submit cookie CSRF (v2.0.0).

    Replaces the session-bound synchronizer token.  The middleware is
    stateless: it reads ``scope['headers']`` for the incoming cookie and
    writes ``scope['csrf_pending_cookie']`` when a fresh cookie must be
    issued.  It does NOT read or write ``scope['session']``.

    Args:
        app:           The next ASGI application.
        exempt_paths:  Paths that bypass CSRF validation for all methods.
    """

    def __init__(self, app: ASGIApp, exempt_paths: list[str] | None = None) -> None:
        self.app = app
        self.exempt_paths = set(exempt_paths or [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        # Parse cookies from incoming headers
        raw_cookies = _parse_cookies(scope.get('headers', []))
        cookie_name = _cookie_name()
        cookie_val: str | None = raw_cookies.get(cookie_name)

        # Check whether the incoming cookie is valid; if not, generate a
        # fresh one and seed it into scope before calling downstream.
        # The send-wrapper will emit Set-Cookie on the live response.
        if not cookie_val or not _cookie_signature_valid(cookie_val):
            nonce = Security.generate_csrf_token()
            sig = _sign_nonce(nonce)
            cookie_val = f'{nonce}.{sig}'
            scope['csrf_pending_cookie'] = cookie_val

        method = scope.get('method', 'GET')
        path = scope.get('path', '/')

        # Safe methods and exempt paths: pass through with the send-wrapper
        # so the cookie is issued (or not) based on scope['csrf_pending_cookie'].
        if method in _SAFE_METHODS or path in self.exempt_paths:
            return await self.app(scope, receive, _make_send_wrapper(scope, send))

        # Unsafe method: two-check validation sequence
        # Retrieve the live cookie value (may have been set above from a fresh one,
        # but for a POST the cookie MUST have come from a previous GET — a newly
        # generated pending cookie on a POST means the request arrived with no
        # valid cookie at all, which we reject below).
        live_cookie = raw_cookies.get(cookie_name)
        if not live_cookie or not _cookie_signature_valid(live_cookie):
            # No valid cookie present — cannot validate (check 1 has nothing to check against)
            log.warning('CSRF check (1) failed: no valid cookie for %s %s', method, path)
            return await _send_403(send)

        # Check (1) is implicitly passed by _cookie_signature_valid above.
        # Now determine the submitted token.
        headers = dict(scope.get('headers', []))
        header_token_bytes = headers.get(b'x-csrf-token')

        if header_token_bytes is not None:
            # Header path — body NOT read (REQ-CSRF-003, INV-004)
            submitted = header_token_bytes.decode('latin1', errors='replace')
            if not _validate_submission(submitted, live_cookie):
                log.warning('CSRF check (2) failed (header) for %s %s', method, path)
                return await _send_403(send)
            return await self.app(scope, receive, _make_send_wrapper(scope, send))

        # No X-CSRF-Token header — inspect Content-Type
        content_type = headers.get(b'content-type', b'').decode('latin1', errors='replace')

        if 'application/json' in content_type:
            # JSON clients must use the header (REQ-CSRF-004)
            log.warning('CSRF token missing (json no header) for %s %s', method, path)
            return await _send_403(send)

        if 'multipart/form-data' in content_type:
            # Refuse to buffer multipart (REQ-CSRF-005, INV-004)
            log.warning(
                'CSRF token missing for multipart upload %s %s — multipart requires X-CSRF-Token header',
                method,
                path,
            )
            return await _send_403(send)

        # Urlencoded form body path (REQ-CSRF-006)
        try:
            body = await _read_body(receive, _form_body_cap())
        except ValueError:
            return await _send_413(send)

        form_token = _extract_form_token(body)
        if not form_token or not _validate_submission(form_token, live_cookie):
            log.warning('CSRF check (2) failed (form) for %s %s', method, path)
            return await _send_403(send)

        # Replay body so downstream handlers can read it
        body_sent = False

        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return {'type': 'http.disconnect'}

        await self.app(scope, replay_receive, _make_send_wrapper(scope, send))


# ---------------------------------------------------------------------------
# Internal helpers (module-level functions, not methods — easier to test)
# ---------------------------------------------------------------------------


def _parse_cookies(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    """Parse the ``Cookie`` header from ASGI headers list into a dict."""
    cookies: dict[str, str] = {}
    for key, value in headers:
        if key.lower() == b'cookie':
            raw = value.decode('latin1', errors='replace')
            for part in raw.split(';'):
                part = part.strip()
                if '=' in part:
                    name, _, val = part.partition('=')
                    cookies[name.strip()] = val.strip()
    return cookies


def _validate_submission(submitted: str, cookie_val: str) -> bool:
    """Return True iff ``submitted`` (raw or masked) equals ``cookie_val``.

    Unmasks ``submitted`` if ``_looks_masked`` identifies it as a BREACH envelope.
    Uses ``hmac.compare_digest`` for constant-time comparison (check 2).
    """
    try:
        candidate = _unmask(submitted) if _looks_masked(submitted) else submitted
    except (ValueError, TypeError):
        return False
    # Compare BYTES, not str: ``_unmask`` can yield a valid-UTF-8 but non-ASCII
    # ``str`` for an attacker-crafted masked token, and ``hmac.compare_digest``
    # raises ``TypeError`` on non-ASCII ``str``. Encoding both sides keeps the
    # comparison constant-time and content-agnostic — a non-ASCII candidate
    # simply compares unequal and returns False (-> 403) instead of crashing.
    return hmac.compare_digest(candidate.encode('utf-8'), cookie_val.encode('utf-8'))


def _make_send_wrapper(scope: Scope, send: Send) -> Send:
    """Return a send-wrapper that appends ``Set-Cookie`` to ``http.response.start``
    iff ``scope['csrf_pending_cookie']`` is set.

    The response body is never buffered (INV-002).
    """
    cookie_issued = False

    async def wrapped_send(message: Message) -> None:
        nonlocal cookie_issued
        if message['type'] == 'http.response.start' and not cookie_issued:
            pending = scope.get('csrf_pending_cookie')
            if pending:
                cookie_issued = True
                cookie_bytes = _build_set_cookie_header(pending)
                existing_headers = list(message.get('headers', []))
                existing_headers.append((b'set-cookie', cookie_bytes))
                message = {**message, 'headers': existing_headers}
        await send(message)

    return wrapped_send


def _extract_form_token(body: bytes) -> str | None:
    """Extract ``_csrf_token`` from a urlencoded body.

    Multipart bodies never reach this function — the middleware rejects them
    earlier when X-CSRF-Token is absent, since multipart parsing would
    require buffering the entire upload.
    """
    try:
        parsed = parse_qs(body.decode('utf-8', errors='replace'))
        values = parsed.get('_csrf_token', [])
        return values[0] if values else None
    except Exception:
        return None


async def _read_body(receive: Receive, max_size: int) -> bytes:
    """Read the ASGI request body up to ``max_size`` bytes.

    Raises ``ValueError`` if the body exceeds the cap.
    """
    body: bytes = b''
    while True:
        message = await receive()
        chunk: bytes = message.get('body', b'')
        body += chunk
        if len(body) > max_size:
            raise ValueError(f'Body exceeds CSRF form cap ({max_size} bytes)')
        if not message.get('more_body', False):
            break
    return body


async def _send_403(send: Send) -> None:
    await send(
        {
            'type': 'http.response.start',
            'status': 403,
            'headers': [(b'content-type', b'text/plain; charset=utf-8')],
        }
    )
    await send(
        {
            'type': 'http.response.body',
            'body': b'403 Forbidden - CSRF token missing or invalid',
        }
    )


async def _send_413(send: Send) -> None:
    """Send a 413 Payload Too Large response."""
    await send(
        {
            'type': 'http.response.start',
            'status': 413,
            'headers': [(b'content-type', b'text/plain; charset=utf-8')],
        }
    )
    await send(
        {
            'type': 'http.response.body',
            'body': b'413 Payload Too Large',
        }
    )


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


class _CsrfRequest(Protocol):
    """Structural type for the objects ``csrf_field`` / ``csrf_token`` accept.

    A Starlette ``starlette.requests.Request`` satisfies this Protocol, as does
    any duck-typed object exposing the same two attributes. Using a Protocol
    (rather than ``object``) makes the helpers' contract explicit per CLAUDE.md's
    mandatory type-hint rule without importing Starlette at runtime.
    """

    cookies: dict[str, str]
    scope: MutableMapping[str, object]


def csrf_field(request: _CsrfRequest) -> str:
    """Return an HTML hidden input with a BREACH-masked CSRF token.

    Accepts a Starlette ``Request`` object (or any object with
    ``.cookies: dict`` and ``.scope: dict``).

    Resolution order:
        1. ``request.cookies[CSRF_COOKIE_NAME]`` — present on all but the
           first GET.
        2. ``request.scope['csrf_pending_cookie']`` — seeded by
           ``CsrfMiddleware`` before calling downstream on a first GET;
           ensures the hidden input and the issued ``Set-Cookie`` carry the
           same value in the same request cycle.

    REQ-CSRF-009.
    """
    name = _cookie_name()
    cookies: dict = getattr(request, 'cookies', {}) or {}
    scope: dict = getattr(request, 'scope', {}) or {}
    raw = cookies.get(name) or scope.get('csrf_pending_cookie', '')
    masked = _mask(raw) if raw else ''
    escaped = _html_escape(masked)
    return f'<input type="hidden" name="_csrf_token" value="{escaped}">'


def csrf_token(request: _CsrfRequest) -> str:
    """Return the raw ``{nonce}.{sig}`` cookie value (not masked, not HMAC-only).

    Accepts a Starlette ``Request`` object (or any object with
    ``.cookies: dict`` and ``.scope: dict``).

    Uses the same resolution order as ``csrf_field``.  Returns an empty
    string when no value is available.

    REQ-CSRF-010.
    """
    name = _cookie_name()
    cookies: dict = getattr(request, 'cookies', {}) or {}
    scope: dict = getattr(request, 'scope', {}) or {}
    return str(cookies.get(name) or scope.get('csrf_pending_cookie', ''))


def csrf_cookie_name() -> str:
    """Return the configured CSRF cookie name (``config.get('CSRF_COOKIE_NAME', ...)``).

    Exposed as a Jinja global so ``base.html`` can render the cookie name into the
    page (``window.NORI_CSRF_COOKIE_NAME``) for the JS shim. The cookie NAME is
    configuration, not a per-visitor secret, so rendering it is cache-safe and lets
    the shim track an operator's ``__Host-csrftoken`` choice (Decision 4) without
    editing ``csrf.js``.

    REQ-CSRF-012, REQ-CSRF-013, design §5.
    """
    return _cookie_name()
