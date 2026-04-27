"""
CSRF Middleware for Starlette.
Validates tokens on state-changing requests (POST, PUT, DELETE, PATCH).
Must be placed AFTER SessionMiddleware in the stack.
"""
import hmac
from html import escape as _html_escape
from urllib.parse import parse_qs

from core.auth.security import Security
from core.logger import get_logger

log = get_logger('csrf')

_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}
_CSRF_SESSION_KEY = '_csrf_token'
_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB — DoS limit


class CsrfMiddleware:
    """ASGI middleware that enforces CSRF tokens."""

    def __init__(self, app, exempt_paths=None):
        self.app = app
        self.exempt_paths = set(exempt_paths or [])

    async def __call__(self, scope, receive, send):
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

        # JSON requests pass through (APIs protected by other means)
        headers = dict(scope.get('headers', []))
        content_type = headers.get(b'content-type', b'').decode('latin1', errors='replace')
        if 'application/json' in content_type:
            return await self.app(scope, receive, send)

        # Read body with size limit and validate token
        try:
            body = await self._read_body(receive)
        except ValueError:
            return await self._send_413(send)

        token = None
        header_token = headers.get(b'x-csrf-token')
        if header_token:
            token = header_token.decode('latin1', errors='replace')

        if not token:
            token = self._extract_form_token(body, content_type)

        expected = session.get(_CSRF_SESSION_KEY) if session else None

        if not token or not expected or not hmac.compare_digest(token, expected):
            log.warning("CSRF validation failed for %s %s", method, path)
            return await self._send_403(send)

        # Replay body so downstream can read it multiple times
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return {'type': 'http.disconnect'}

        await self.app(scope, replay_receive, send)

    def _extract_form_token(self, body, content_type):
        """Extract _csrf_token from body (url-encoded or multipart)."""
        if 'multipart/form-data' in content_type:
            return self._parse_multipart_token(body, content_type)
        try:
            parsed = parse_qs(body.decode('utf-8', errors='replace'))
            values = parsed.get('_csrf_token', [])
            return values[0] if values else None
        except Exception:
            return None

    def _parse_multipart_token(self, body, content_type):
        """Extract _csrf_token from multipart form data."""
        try:
            boundary = None
            for part in content_type.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[len('boundary='):]
                    # Strip quotes per RFC 2046
                    if len(boundary) >= 2 and boundary[0] in ('"', "'") and boundary[-1] == boundary[0]:
                        boundary = boundary[1:-1]
                    break

            if not boundary:
                return None

            boundary_bytes = ('--' + boundary).encode('utf-8')
            parts = body.split(boundary_bytes)

            for part in parts:
                if b'name="_csrf_token"' in part:
                    chunks = part.split(b'\r\n\r\n', 1)
                    if len(chunks) == 2:
                        # Strip only trailing CRLF, not dashes that could be part of the token
                        value = chunks[1].split(b'\r\n', 1)[0]
                        return value.decode('utf-8', errors='replace')
        except Exception:
            return None
        return None

    async def _read_body(self, receive):
        """Read the ASGI request body with size limit to prevent DoS."""
        body = b''
        while True:
            message = await receive()
            body += message.get('body', b'')
            if len(body) > _MAX_BODY_SIZE:
                raise ValueError(f"Body exceeds max size ({_MAX_BODY_SIZE} bytes)")
            if not message.get('more_body', False):
                break
        return body

    async def _send_403(self, send):
        await send({
            'type': 'http.response.start',
            'status': 403,
            'headers': [(b'content-type', b'text/plain; charset=utf-8')],
        })
        await send({
            'type': 'http.response.body',
            'body': b'403 Forbidden - CSRF token missing or invalid',
        })

    async def _send_413(self, send):
        """Send a 413 Payload Too Large response."""
        await send({
            'type': 'http.response.start',
            'status': 413,
            'headers': [(b'content-type', b'text/plain; charset=utf-8')],
        })
        await send({
            'type': 'http.response.body',
            'body': b'413 Payload Too Large',
        })


def csrf_field(session):
    """Return HTML hidden input with the CSRF token (XSS-safe)."""
    token = _html_escape(session.get(_CSRF_SESSION_KEY, ''))
    return f'<input type="hidden" name="_csrf_token" value="{token}">'


def csrf_token(session):
    """Return the raw CSRF token string."""
    return session.get(_CSRF_SESSION_KEY, '')
