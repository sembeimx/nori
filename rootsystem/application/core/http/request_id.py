"""
Request ID middleware for request tracing.

Generates a UUID per HTTP request and:

- Sets ``X-Request-ID`` response header
- Stores on ``request.state.request_id``
- Stores in the ``request_id_var`` ContextVar so any code in the request
  task tree (including ``asyncio.create_task`` background work spawned
  during the request) can read it without threading the request through
- Supports propagation from incoming ``X-Request-ID`` header

The ContextVar is what makes Request-ID reach logs from async background
tasks (audit, queue, push, background). ``RequestIdLogFilter`` in
``core.logger`` consumes it; the JSON formatter then writes it on every
log record.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

__all__ = ['RequestIdMiddleware', 'request_id_var', 'get_request_id']

# ContextVar carries the current request's ID through the asyncio task tree.
# `asyncio.create_task` copies the context at spawn time, so background
# tasks created inside a request handler inherit this value automatically.
request_id_var: ContextVar[str | None] = ContextVar('request_id', default=None)

# Accept incoming X-Request-ID values that look like ASCII identifiers up
# to 64 chars. Refusing CR/LF is the load-bearing part — newlines in a
# logged request_id let an attacker forge fake log entries downstream.
_VALID_REQUEST_ID = re.compile(r'^[A-Za-z0-9_\-]{1,64}$')


def get_request_id() -> str | None:
    """Return the current request's ID, or None outside an HTTP context."""
    return request_id_var.get()


class RequestIdMiddleware:
    """ASGI middleware that assigns a unique ID to each HTTP request."""

    def __init__(self, app, header_name: str = 'x-request-id', trust_incoming: bool = True):
        self.app = app
        self._header_bytes = header_name.lower().encode('latin1')
        self._trust_incoming = trust_incoming

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        # Extract or generate request ID
        request_id = None
        if self._trust_incoming:
            for name, value in scope.get('headers', []):
                if name == self._header_bytes:
                    candidate = value.decode('latin1', errors='replace')
                    if _VALID_REQUEST_ID.match(candidate):
                        request_id = candidate
                    break

        if not request_id:
            request_id = str(uuid.uuid4())

        # Store in scope state so request.state.request_id works
        if 'state' not in scope:
            scope['state'] = {}
        scope['state']['request_id'] = request_id

        # Set the ContextVar so logging.Filter and any background task
        # spawned inside this handler picks it up without manual threading.
        token = request_id_var.set(request_id)

        async def send_with_id(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers.append((self._header_bytes, request_id.encode('latin1')))
                message = {**message, 'headers': headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
