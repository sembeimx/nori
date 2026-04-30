"""
WebSocket handler base classes.

    from core.ws import WebSocketHandler, JsonWebSocketHandler

    class ChatHandler(WebSocketHandler):
        async def on_receive(self, websocket, data):
            await websocket.send_text(f"You said: {data}")

    # In routes.py:
    # WebSocketRoute('/ws/chat', ChatHandler())
"""

from __future__ import annotations

import asyncio

from starlette.websockets import WebSocket, WebSocketDisconnect

from core.logger import get_logger

_log = get_logger('ws')

# Idle timeout in seconds — close connection if no message received
_RECEIVE_TIMEOUT: int = 300  # 5 minutes

# Per-message size cap. WebSockets stream until the client closes, so without
# a cap a single 1GB text frame can OOM the worker. 1 MiB is generous for
# chat / control-plane traffic and rejects the obvious DoS.
_MAX_MESSAGE_SIZE: int = 1024 * 1024


class WebSocketHandler:
    """
    Base WebSocket handler. Subclass and override on_receive().
    Use as endpoint for WebSocketRoute.

    Implements the ASGI interface so Starlette can call it
    with (scope, receive, send).

    Set ``receive_timeout`` (seconds) on the subclass to override the
    default idle timeout, and ``max_message_size`` (bytes) to override
    the per-frame size cap.

    Authentication note:
        The default ``on_connect()`` accepts the connection unconditionally.
        WebSockets bypass the HTTP middleware stack for auth checks — if your
        endpoint requires a session, you MUST override ``on_connect()`` and
        validate ``websocket.session`` (or the cookie / header / query token)
        before calling ``await websocket.accept()``. Reject with
        ``await websocket.close(code=1008)`` on auth failure.
    """

    receive_timeout: int = _RECEIVE_TIMEOUT
    max_message_size: int = _MAX_MESSAGE_SIZE

    async def __call__(self, scope, receive, send) -> None:
        websocket = WebSocket(scope, receive=receive, send=send)
        await self.on_connect(websocket)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=self.receive_timeout,
                    )
                except asyncio.TimeoutError:
                    _log.info('WebSocket idle timeout (%ds), closing', self.receive_timeout)
                    await websocket.close(code=1000)
                    break
                if len(data) > self.max_message_size:
                    _log.warning(
                        'WebSocket message exceeds max_message_size (%d > %d), closing',
                        len(data),
                        self.max_message_size,
                    )
                    # 1009 = "message too big" per RFC 6455
                    await websocket.close(code=1009)
                    break
                try:
                    await self.on_receive(websocket, data)
                except Exception as exc:
                    _log.error('Error in on_receive: %s', exc, exc_info=True)
        except WebSocketDisconnect as exc:
            await self.on_disconnect(websocket, exc.code)
        except Exception as exc:
            _log.error('WebSocket error: %s', exc, exc_info=True)

    async def on_connect(self, websocket: WebSocket) -> None:
        """Called when a client connects. Default: accept the connection.

        Override this method to authenticate the connection — the base
        implementation accepts ALL clients. See the class docstring.
        """
        await websocket.accept()

    async def on_receive(self, websocket: WebSocket, data: str) -> None:
        """Called when a text message is received. Override in subclass."""

    async def on_disconnect(self, websocket: WebSocket, code: int) -> None:
        """Called when the client disconnects."""


class JsonWebSocketHandler(WebSocketHandler):
    """
    WebSocket handler that works with JSON messages.
    Uses receive_json()/send_json(). Override on_receive_json().

    Inherits lifecycle and idle timeout from WebSocketHandler.
    """

    async def __call__(self, scope, receive, send) -> None:
        import json

        websocket = WebSocket(scope, receive=receive, send=send)
        await self.on_connect(websocket)
        try:
            while True:
                try:
                    # Receive as raw text first so we can size-cap the frame
                    # before json.loads gets a chance to allocate a giant
                    # parsed structure. receive_json() in Starlette is just
                    # ``json.loads(await receive_text())`` — same semantics.
                    raw = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=self.receive_timeout,
                    )
                except asyncio.TimeoutError:
                    _log.info('WebSocket idle timeout (%ds), closing', self.receive_timeout)
                    await websocket.close(code=1000)
                    break
                if len(raw) > self.max_message_size:
                    _log.warning(
                        'WebSocket JSON message exceeds max_message_size (%d > %d), closing',
                        len(raw),
                        self.max_message_size,
                    )
                    await websocket.close(code=1009)
                    break
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    _log.warning('Invalid JSON over WebSocket: %s', exc)
                    continue
                try:
                    await self.on_receive_json(websocket, data)
                except Exception as exc:
                    _log.error('Error in on_receive_json: %s', exc, exc_info=True)
        except WebSocketDisconnect as exc:
            await self.on_disconnect(websocket, exc.code)
        except Exception as exc:
            _log.error('WebSocket error: %s', exc, exc_info=True)

    async def on_receive_json(self, websocket: WebSocket, data: dict) -> None:
        """Called when a JSON message is received. Override in subclass."""
