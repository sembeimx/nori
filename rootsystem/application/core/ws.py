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

__all__ = [
    'JsonWebSocketHandler',
    'WebSocketHandler',
    'close_all_connections',
]

# Idle timeout in seconds — close connection if no message received
_RECEIVE_TIMEOUT: int = 300  # 5 minutes

# Per-message size cap. WebSockets stream until the client closes, so without
# a cap a single 1GB text frame can OOM the worker. 1 MiB is generous for
# chat / control-plane traffic and rejects the obvious DoS.
_MAX_MESSAGE_SIZE: int = 1024 * 1024

# Registry of currently-open WebSocket connections. Each handler adds itself
# on connect and removes itself on disconnect (via try/finally). The ASGI
# lifespan walks this set on shutdown and sends a clean ``close(1001)`` to
# every active client so they reconnect immediately, instead of waiting on
# a TCP timeout after uvicorn forces the socket closed without a frame.
#
# A regular ``set`` (not WeakSet) is used because the WebSocket object is
# already kept alive by the running coroutine — explicit add/discard in the
# handler's try/finally gives a deterministic lifecycle that does not depend
# on GC timing during shutdown, which is exactly when GC is least reliable.
_active_connections: set[WebSocket] = set()


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
        # Register before on_connect so even an auth-rejected connection
        # is tracked for the brief window it exists; the ``finally`` clause
        # guarantees removal whether on_connect raises, the loop exits
        # cleanly, or a timeout / size-cap closes the socket.
        _active_connections.add(websocket)
        try:
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
        finally:
            _active_connections.discard(websocket)

    async def on_connect(self, websocket: WebSocket) -> None:
        """Called when a client connects. Default: accept the connection.

        .. warning::

           **The base implementation accepts ALL clients without
           authentication.** Anyone who can reach the WebSocket route can
           open a connection. WebSockets do NOT go through Nori's
           ``CsrfMiddleware`` (CSRF does not apply to the WS handshake),
           and HTTP-only middlewares that gate by ``scope['type'] == 'http'``
           are skipped during the upgrade.

           ``SessionMiddleware`` *does* run for WebSockets and populates
           ``websocket.session`` — for any auth-required endpoint, override
           this method and check the session yourself before calling
           ``await websocket.accept()``::

               async def on_connect(self, websocket):
                   if not websocket.session.get('user_id'):
                       await websocket.close(code=1008)  # policy violation
                       return
                   await websocket.accept()

           For JWT-based auth, read the token from a query parameter
           (browsers cannot set custom headers on WebSocket upgrades).
           See ``docs/websockets.md`` for full examples.
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
        _active_connections.add(websocket)
        try:
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
        finally:
            _active_connections.discard(websocket)

    async def on_receive_json(self, websocket: WebSocket, data: dict) -> None:
        """Called when a JSON message is received. Override in subclass."""


async def close_all_connections(code: int = 1001, timeout: float = 2.0) -> None:
    """Send a clean ``close(code)`` frame to every active WebSocket.

    Called from the ASGI lifespan during graceful shutdown so connected
    clients receive a real WebSocket close frame (default ``1001`` —
    "going away" per RFC 6455) and reconnect immediately, instead of
    waiting on a TCP timeout after uvicorn forces the socket shut
    without a frame. The latter ends up looking like ``1006`` (Abnormal
    Closure) on the client, which most reconnect strategies treat as
    a transient network error and back off exponentially — clients
    that should reconnect in ~100 ms end up reconnecting in ~30 s.

    A stuck close (e.g. a client whose TCP write buffer is full) does
    not block shutdown forever — on timeout the operation logs a
    warning and returns; uvicorn still drops the socket. The trade is
    deliberate: a noisy partial close is better than a hung process.

    Args:
        code: WebSocket close code to send. ``1001`` is the right
            choice for "the server is going away cleanly". ``1012``
            ("service restart") is also valid; some clients treat it
            as a stronger signal to reconnect.
        timeout: Maximum seconds to wait for the close fan-out.
    """
    if not _active_connections:
        return
    active = list(_active_connections)
    _log.info('Closing %d active WebSocket connection(s) for shutdown', len(active))

    async def _close(ws: WebSocket) -> None:
        try:
            await ws.close(code=code)
        except Exception:  # noqa: S110 — best-effort fan-out; see comment
            # Already closed, network gone, partner crashed — none of
            # these should derail shutdown of the remaining connections.
            # Logging here would spam ERRORs on every rolling restart for
            # peers that already disconnected (the common case).
            pass

    try:
        await asyncio.wait_for(
            asyncio.gather(*(_close(ws) for ws in active), return_exceptions=True),
            timeout,
        )
    except (TimeoutError, asyncio.TimeoutError):
        _log.warning(
            'Timed out (%.1fs) closing %d WebSocket(s); shutdown continues.',
            timeout,
            len(active),
        )
