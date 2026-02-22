"""Echo WebSocket handler — example/demo."""
from starlette.websockets import WebSocket
from core.ws import WebSocketHandler


class EchoHandler(WebSocketHandler):
    """Echoes back any text message received."""

    async def on_receive(self, websocket: WebSocket, data: str) -> None:
        await websocket.send_text(f"Echo: {data}")
