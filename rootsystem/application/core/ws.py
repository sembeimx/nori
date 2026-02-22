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

from starlette.websockets import WebSocket, WebSocketDisconnect


class WebSocketHandler:
    """
    Base WebSocket handler. Subclass and override on_receive().
    Use as endpoint for WebSocketRoute.

    Implements the ASGI interface so Starlette can call it
    with (scope, receive, send).
    """

    async def __call__(self, scope, receive, send) -> None:
        websocket = WebSocket(scope, receive=receive, send=send)
        await self.on_connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                await self.on_receive(websocket, data)
        except WebSocketDisconnect as exc:
            await self.on_disconnect(websocket, exc.code)

    async def on_connect(self, websocket: WebSocket) -> None:
        """Called when a client connects. Default: accept the connection."""
        await websocket.accept()

    async def on_receive(self, websocket: WebSocket, data: str) -> None:
        """Called when a text message is received. Override in subclass."""

    async def on_disconnect(self, websocket: WebSocket, code: int) -> None:
        """Called when the client disconnects."""


class JsonWebSocketHandler:
    """
    WebSocket handler that works with JSON messages.
    Uses receive_json()/send_json(). Override on_receive_json().
    """

    async def __call__(self, scope, receive, send) -> None:
        websocket = WebSocket(scope, receive=receive, send=send)
        await self.on_connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                await self.on_receive_json(websocket, data)
        except WebSocketDisconnect as exc:
            await self.on_disconnect(websocket, exc.code)

    async def on_connect(self, websocket: WebSocket) -> None:
        """Called when a client connects. Default: accept the connection."""
        await websocket.accept()

    async def on_receive_json(self, websocket: WebSocket, data: dict) -> None:
        """Called when a JSON message is received. Override in subclass."""

    async def on_disconnect(self, websocket: WebSocket, code: int) -> None:
        """Called when the client disconnects."""
