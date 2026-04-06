# WebSockets

Nori offers a native, object-oriented implementation for WebSockets, built on Starlette's asynchronous capabilities. Instead of dealing with loose functions and confusing callbacks, WebSockets in Nori are handled through dedicated classes (Handlers) that encapsulate the connection lifecycle.

The WebSocket lifecycle is: connect, receive messages, disconnect. A class makes this linear and readable. Loose functions with callbacks hide the flow and scatter state across closures.

## WebSocket Handlers

Handlers must inherit from `WebSocketHandler` or its convenience variant `JsonWebSocketHandler` (located in `core.ws`). `JsonWebSocketHandler` inherits from `WebSocketHandler`, so both share the same lifecycle and configuration.

### Creating a Basic Handler (JSON)

For most modern implementations (chats, notifications, real-time dashboards), you will want to communicate in JSON format.

Create a file in the modules directory, for example `rootsystem/application/modules/chat_ws.py`:

```python
from core.ws import JsonWebSocketHandler

class ChatHandler(JsonWebSocketHandler):
    
    async def on_connect(self, websocket):
        """Triggered when a client attempts to connect."""
        print(f"New client connected. Sending welcome message.")
        await websocket.send_json({"event": "welcome", "message": "Connected to the Nori server"})

    async def on_receive_json(self, websocket, data: dict):
        """Triggered when the server receives a JSON message from the client."""
        print(f"Message received: {data}")

        # Echoing the message back to the client
        await websocket.send_json({
            "event": "echo",
            "original_data": data
        })

    async def on_disconnect(self, websocket, close_code: int):
        """Triggered when the connection is lost or closed."""
        print(f"Client disconnected with code: {close_code}")
```

### The Handler Lifecycle
1. **`on_connect(websocket)`**: Runs after the connection is accepted. Validate session cookies, verify tokens, or query the DB. To reject a connection, call `await websocket.close(code)`.
2. **`on_receive(websocket, data)` / `on_receive_json(websocket, data)`**: The heart of communication. In `WebSocketHandler`, `data` is a raw string. In `JsonWebSocketHandler`, `data` is already parsed as a Python dictionary (override `on_receive_json` instead of `on_receive`).
3. **`on_disconnect(websocket, close_code)`**: Ideal for clearing memory, removing the user from active rooms, or updating status in the database.

### Idle Timeout

Both handlers enforce an idle timeout (default: **5 minutes**). If no message is received within the timeout window, the connection is gracefully closed with code `1000`. Override `receive_timeout` on your subclass to customize:

```python
class LongPollHandler(JsonWebSocketHandler):
    receive_timeout = 600  # 10 minutes
```

### Authentication in WebSockets

Since `SessionMiddleware` populates `websocket.session` (WebSocket shares Starlette's `HTTPConnection`), you can check the session in `on_connect` to reject unauthenticated clients:

```python
class ProtectedChatHandler(JsonWebSocketHandler):

    async def on_connect(self, websocket):
        user_id = websocket.session.get('user_id')
        if not user_id:
            await websocket.close(code=4001)  # Custom close code
            return

        # Store user info for later use in on_receive
        websocket.state.user_id = user_id
        await websocket.send_json({"event": "welcome", "user_id": user_id})

    async def on_receive(self, websocket, data: dict):
        user_id = websocket.state.user_id
        await websocket.send_json({"from": user_id, "message": data.get("message")})
```

For JWT-based authentication, read the token from a query parameter (`/ws/chat?token=...`) since browsers cannot set custom headers on WebSocket connections:

```python
from core.auth.jwt import verify_token

async def on_connect(self, websocket):
    token = websocket.query_params.get('token')
    payload = verify_token(token) if token else None
    if not payload:
        await websocket.close(code=4001)
        return
    websocket.state.user_id = payload['user_id']
```

## Routing WebSockets

Unlike HTTP routes (`Route()`), WebSockets are explicitly registered using the `WebSocketRoute()` class in your `routes.py` file.

```python
# routes.py
from starlette.routing import Route, WebSocketRoute
from modules.chat_ws import ChatHandler

routes = [
    # ... your HTTP routes ...
    
    # Mounting the WebSocket
    WebSocketRoute('/ws/chat', ChatHandler()),
]
```

## Connections in the Frontend (Vanilla JS)

Connecting from the HTML/JavaScript browser is straightforward and instantiated via the browser standard `WebSocket`.

```javascript
// Make sure to use wss:// if you are in production under HTTPS
const ws = new WebSocket('ws://localhost:8000/ws/chat');

ws.onopen = function(event) {
    console.log("WebSocket Opened");
    
    // Sending a JSON payload to the server
    ws.send(JSON.stringify({ subject: "Hello Server!" }));
};

ws.onmessage = function(event) {
    // Listening to JSON sends back from the Server
    const response = JSON.parse(event.data);
    console.log("Server says:", response);
};

ws.onclose = function(event) {
    console.log("WebSocket Closed");
};
```

*(Remember that if you configure your deployment on a VPS with Nginx as a reverse proxy, the Nginx `location /ws` block will require the directives `proxy_set_header Upgrade $http_upgrade;` and `proxy_set_header Connection "Upgrade";` to avoid truncating the channel).*
