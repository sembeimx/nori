"""Echo WebSocket handler — example/demo."""

from __future__ import annotations

from core.ws import WebSocketHandler
from starlette.websockets import WebSocket


class EchoHandler(WebSocketHandler):
    """Echoes back any text message received."""

    async def on_receive(self, websocket: WebSocket, data: str) -> None:
        await websocket.send_text(f"Echo: {data}")
