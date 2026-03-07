"""
Request ID middleware for request tracing.

Generates a UUID per HTTP request and:
- Sets ``X-Request-ID`` response header
- Stores on ``request.state.request_id``
- Supports propagation from incoming ``X-Request-ID`` header

The JsonFormatter in ``core.logger`` already supports ``record.request_id``.
"""
from __future__ import annotations

import uuid

__all__ = ['RequestIdMiddleware']


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
                    request_id = value.decode('latin1')
                    break

        if not request_id:
            request_id = str(uuid.uuid4())

        # Store in scope state so request.state.request_id works
        if 'state' not in scope:
            scope['state'] = {}
        scope['state']['request_id'] = request_id

        async def send_with_id(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers.append((self._header_bytes, request_id.encode('latin1')))
                message = {**message, 'headers': headers}
            await send(message)

        await self.app(scope, receive, send_with_id)
