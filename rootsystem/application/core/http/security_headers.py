"""
Security Headers Middleware for Starlette.
Adds standard security headers to all HTTP responses.

Since v1.13.0 a sensible Content-Security-Policy is sent in **report-only**
mode by default. Browsers evaluate the policy and log violations to the
console / report endpoint without blocking content — so existing pages
continue to render unchanged while operators discover what would break
if the policy were enforced. Migration to enforcement is one flag away
(``csp_report_only=False``).
"""

from __future__ import annotations

DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "  # Jinja templates routinely use inline styles
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware:
    """ASGI middleware that injects security headers into every response."""

    DEFAULT_HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    }

    def __init__(
        self,
        app,
        headers=None,
        hsts=True,
        hsts_max_age=31536000,
        csp='default',
        csp_report_only=True,
        csp_report_uri=None,
    ):
        """
        Args:
            app: ASGI application.
            headers: Dict of custom headers that override the defaults.
            hsts: Enable Strict-Transport-Security (default True).
            hsts_max_age: Max-age for HSTS in seconds (default 1 year).
            csp: Content-Security-Policy.
                 - ``'default'`` (default): ship ``DEFAULT_CSP`` in report-only mode.
                 - ``None`` or ``False``: do not send a CSP header.
                 - Any other string: send that policy verbatim.
            csp_report_only: Send as ``Content-Security-Policy-Report-Only`` (browsers
                 log violations but don't block content) instead of enforcing. Default True.
                 Flip to False once you've reviewed the violation reports and confirmed
                 the policy doesn't break anything.
            csp_report_uri: If set, append ``report-uri <url>`` to the policy so browsers
                 POST violation reports to that endpoint. Default None (browsers log to
                 their own console only). Pair with a controller that accepts and logs
                 the JSON payload to your observability stack.
        """
        self.app = app
        self.headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        if hsts:
            self.headers['Strict-Transport-Security'] = f'max-age={hsts_max_age}; includeSubDomains'

        policy = self._resolve_csp(csp, csp_report_uri)
        if policy:
            header_name = 'Content-Security-Policy-Report-Only' if csp_report_only else 'Content-Security-Policy'
            self.headers[header_name] = policy

        # Pre-encode headers to avoid doing it on every request
        self._encoded = [(k.lower().encode('latin1'), v.encode('latin1')) for k, v in self.headers.items()]

    @staticmethod
    def _resolve_csp(csp, report_uri):
        """Resolve the csp parameter to a final policy string (or empty for opt-out)."""
        if csp is None or csp is False:
            return ''
        policy = DEFAULT_CSP if csp == 'default' else csp
        if report_uri:
            policy = f'{policy}; report-uri {report_uri}'
        return policy

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
