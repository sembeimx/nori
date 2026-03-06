"""
Security Headers Middleware for Starlette.
Adds standard security headers to all HTTP responses.
"""


class SecurityHeadersMiddleware:
    """ASGI middleware that injects security headers into every response."""

    DEFAULT_HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    }

    def __init__(self, app, headers=None, hsts=True, hsts_max_age=31536000,
                 csp=None):
        """
        Args:
            app: ASGI application.
            headers: Dict of custom headers that override the defaults.
            hsts: Enable Strict-Transport-Security (default True).
            hsts_max_age: Max-age for HSTS in seconds (default 1 year).
            csp: Content-Security-Policy string. None = not sent.
        """
        self.app = app
        self.headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        if hsts:
            self.headers['Strict-Transport-Security'] = f'max-age={hsts_max_age}; includeSubDomains'
        if csp:
            self.headers['Content-Security-Policy'] = csp
        # Pre-encode headers to avoid doing it on every request
        self._encoded = [
            (k.lower().encode('latin1'), v.encode('latin1'))
            for k, v in self.headers.items()
        ]

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers.extend(self._encoded)
                message = {**message, 'headers': headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
