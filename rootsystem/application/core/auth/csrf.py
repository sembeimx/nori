"""
CSRF Middleware para Starlette.
Valida tokens en requests state-changing (POST, PUT, DELETE, PATCH).
Debe ir DESPUES de SessionMiddleware en el stack.
"""
import hmac
from urllib.parse import parse_qs
from core.auth.security import Security
from core.logger import get_logger

log = get_logger('csrf')

_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}
_CSRF_SESSION_KEY = '_csrf_token'
_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB — limite DoS


class CsrfMiddleware:
    """ASGI middleware que enforce CSRF token."""

    def __init__(self, app, exempt_paths=None):
        self.app = app
        self.exempt_paths = set(exempt_paths or [])

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        # Starlette SessionMiddleware popula scope['session'] como dict
        session = scope.get('session')

        # Asegurar que el token existe
        if session is not None and _CSRF_SESSION_KEY not in session:
            session[_CSRF_SESSION_KEY] = Security.generate_csrf_token()

        method = scope.get('method', 'GET')

        if method in _SAFE_METHODS:
            return await self.app(scope, receive, send)

        path = scope.get('path', '/')
        if path in self.exempt_paths:
            return await self.app(scope, receive, send)

        # JSON requests pasan (APIs protegidas por otros medios)
        headers = dict(scope.get('headers', []))
        content_type = headers.get(b'content-type', b'').decode('latin1', errors='replace')
        if 'application/json' in content_type:
            return await self.app(scope, receive, send)

        # Leer body con limite de tamaño y validar token
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

        async def replay_receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        await self.app(scope, replay_receive, send)

    def _extract_form_token(self, body, content_type):
        """Extrae _csrf_token del body (url-encoded o multipart)."""
        if 'multipart/form-data' in content_type:
            return self._parse_multipart_token(body, content_type)
        try:
            parsed = parse_qs(body.decode('utf-8', errors='replace'))
            values = parsed.get('_csrf_token', [])
            return values[0] if values else None
        except Exception:
            return None

    def _parse_multipart_token(self, body, content_type):
        """Extrae _csrf_token de multipart form data."""
        try:
            for part in content_type.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[len('boundary='):]
                    break
            else:
                return None

            boundary_bytes = ('--' + boundary).encode('utf-8')
            parts = body.split(boundary_bytes)

            for part in parts:
                if b'name="_csrf_token"' in part:
                    chunks = part.split(b'\r\n\r\n', 1)
                    if len(chunks) == 2:
                        value = chunks[1].rstrip(b'\r\n-')
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
    """Retorna HTML hidden input con el CSRF token."""
    token = session.get(_CSRF_SESSION_KEY, '')
    return f'<input type="hidden" name="_csrf_token" value="{token}">'


def csrf_token(session):
    """Retorna el token CSRF como string."""
    return session.get(_CSRF_SESSION_KEY, '')
