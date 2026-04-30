"""
CSRF Middleware for Starlette.
Validates tokens on state-changing requests (POST, PUT, DELETE, PATCH).
Must be placed AFTER SessionMiddleware in the stack.

Body buffering trade-off:
    To extract a CSRF token from a form body the middleware would have
    to read the entire body — which defeats Starlette's streaming for
    file uploads (a 100 MB upload becomes a 100 MB allocation in the
    middleware). To avoid that:

    * If ``X-CSRF-Token`` is present, the body is NOT read (zero buffer).
      Recommended for AJAX / fetch / non-browser clients.
    * For ``application/x-www-form-urlencoded`` (small forms), the body
      is buffered up to ``config.CSRF_FORM_MAX_BODY_SIZE`` (default
      1 MiB). Real urlencoded forms rarely exceed a few KB.
    * For ``multipart/form-data``, the middleware refuses to buffer.
      Multipart is the file-upload path — clients MUST send the token
      via ``X-CSRF-Token`` header so we can validate without consuming
      the upload stream.
"""

from __future__ import annotations

import hmac
from html import escape as _html_escape
from typing import Any
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.auth.security import Security
from core.conf import config
from core.logger import get_logger

log = get_logger('csrf')

_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}
_CSRF_SESSION_KEY = '_csrf_token'
_DEFAULT_FORM_BODY_SIZE = 1 * 1024 * 1024  # 1 MiB — for urlencoded form parsing


def _form_body_cap() -> int:
    """Resolve the per-request urlencoded buffer cap from settings."""
    return int(config.get('CSRF_FORM_MAX_BODY_SIZE', _DEFAULT_FORM_BODY_SIZE))


class CsrfMiddleware:
    """ASGI middleware that enforces CSRF tokens."""

    def __init__(self, app: ASGIApp, exempt_paths: list[str] | None = None) -> None:
        self.app = app
        self.exempt_paths = set(exempt_paths or [])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        # Starlette SessionMiddleware populates scope['session'] as dict
        session = scope.get('session')

        # Ensure token exists
        if session is not None and _CSRF_SESSION_KEY not in session:
            session[_CSRF_SESSION_KEY] = Security.generate_csrf_token()

        method = scope.get('method', 'GET')

        if method in _SAFE_METHODS:
            return await self.app(scope, receive, send)

        path = scope.get('path', '/')
        if path in self.exempt_paths:
            return await self.app(scope, receive, send)

        headers = dict(scope.get('headers', []))
        content_type = headers.get(b'content-type', b'').decode('latin1', errors='replace')
        expected = session.get(_CSRF_SESSION_KEY) if session else None

        # 1. Header token — preferred. Validates without touching the body
        #    so streaming uploads stay streamed.
        token: str | None = None
        header_token = headers.get(b'x-csrf-token')
        if header_token:
            token = header_token.decode('latin1', errors='replace')

        if token is not None:
            if not expected or not hmac.compare_digest(token, expected):
                log.warning('CSRF validation failed (header) for %s %s', method, path)
                return await self._send_403(send)
            return await self.app(scope, receive, send)

        # 2. No header. JSON clients must use the header — the body is
        #    not parsed to avoid Content-Type-based bypass tricks.
        if 'application/json' in content_type:
            log.warning('CSRF token missing (json no header) for %s %s', method, path)
            return await self._send_403(send)

        # 3. multipart/form-data: refuse to buffer. The token has to come
        #    in the X-CSRF-Token header so we don't kill streaming.
        if 'multipart/form-data' in content_type:
            log.warning(
                'CSRF token missing for multipart upload %s %s — multipart requires X-CSRF-Token header',
                method,
                path,
            )
            return await self._send_403(send)

        # 4. urlencoded form: buffer up to the cap, parse the token field.
        try:
            body = await self._read_body(receive, _form_body_cap())
        except ValueError:
            return await self._send_413(send)

        token = self._extract_form_token(body, content_type)
        if not token or not expected or not hmac.compare_digest(token, expected):
            log.warning('CSRF validation failed (form) for %s %s', method, path)
            return await self._send_403(send)

        # Replay body so downstream can read it multiple times
        body_sent = False

        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return {'type': 'http.disconnect'}

        await self.app(scope, replay_receive, send)

    def _extract_form_token(self, body: bytes, content_type: str) -> str | None:
        """Extract ``_csrf_token`` from a urlencoded body.

        Multipart bodies never reach this function — see __call__: we
        refuse them when the X-CSRF-Token header is missing, since
        parsing multipart requires buffering the upload.
        """
        try:
            parsed = parse_qs(body.decode('utf-8', errors='replace'))
            values = parsed.get('_csrf_token', [])
            return values[0] if values else None
        except Exception:
            return None

    async def _read_body(self, receive: Receive, max_size: int) -> bytes:
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

    async def _send_403(self, send: Send) -> None:
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

    async def _send_413(self, send: Send) -> None:
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


def csrf_field(session: dict[str, Any]) -> str:
    """Return HTML hidden input with the CSRF token (XSS-safe)."""
    token = _html_escape(session.get(_CSRF_SESSION_KEY, ''))
    return f'<input type="hidden" name="_csrf_token" value="{token}">'


def csrf_token(session: dict[str, Any]) -> str:
    """Return the raw CSRF token string."""
    token: str = session.get(_CSRF_SESSION_KEY, '')
    return token
