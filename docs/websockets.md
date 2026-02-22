# WebSockets

Nori offers a native, object-oriented implementation for WebSockets, built on Starlette's asynchronous capabilities. Instead of dealing with loose functions and confusing callbacks, WebSockets in Nori are handled through dedicated classes (Handlers) that encapsulate the connection lifecycle.

## WebSocket Handlers

Handlers must inherit from `WebSocketHandler` or its convenience variant `JsonWebSocketHandler` (located in `core.ws`).

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

    async def on_receive(self, websocket, data: dict):
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
1. **`on_connect(websocket)`**: Here you can validate session cookies (`websocket.session`), verify tokens, or interact with the DB before accepting the client. If you do not wish to accept the connection due to permissions, you can close it by raising an exception or calling `await websocket.close()`.
2. **`on_receive(websocket, data)`**: The heart of communication. Because it is `JsonWebSocketHandler`, the `data` parameter already comes parsed and validated as a Python Dictionary.
3. **`on_disconnect(websocket, close_code)`**: Ideal for clearing memory, removing the user from active "chat rooms" in global dictionaries, or updating their status in the database.

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
