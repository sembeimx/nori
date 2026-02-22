# WebSockets

Nori ofrece una implementación nativa y orientada a objetos para WebSockets, construida sobre las capacidades asíncronas de Starlette. En lugar de lidiar con funciones sueltas y callbacks confusos, WebSockets en Nori se manejan mediante clases dedicadas (Handelers) que encapsulan el ciclo de vida de la conexión.

## Handlers de WebSocket

Los Handlers deben heredar de `WebSocketHandler` o de su variante de conveniencia `JsonWebSocketHandler` (ubicados en `core.ws`).

### Creando un Handler Básico (JSON)

Para la mayoría de implementaciones modernas (chats, notificaciones, paneles en tiempo real), querrás comunicarte en formato JSON.

Crea un archivo en el directorio de módulos, por ejemplo `rootsystem/application/modules/chat_ws.py`:

```python
from core.ws import JsonWebSocketHandler

class ChatHandler(JsonWebSocketHandler):
    
    async def on_connect(self, websocket):
        """Disparado cuando un cliente intenta conectarse."""
        print(f"Nuevo cliente conectado. Envíando mensaje de bienvenida.")
        await websocket.send_json({"event": "welcome", "message": "Conectado al servidor Nori"})

    async def on_receive(self, websocket, data: dict):
        """Disparado cuando el servidor recibe un mensaje JSON del cliente."""
        print(f"Mensaje recibido: {data}")
        
        # Haciendo eco del mensaje de vuelta al cliente
        await websocket.send_json({
            "event": "echo",
            "original_data": data
        })

    async def on_disconnect(self, websocket, close_code: int):
        """Disparado cuando la conexión se pierde o es cerrada."""
        print(f"Cliente desconectado con código: {close_code}")
```

### El Ciclo de Vida del Handler
1. **`on_connect(websocket)`**: Aquí puedes validar cookies de sesión (`websocket.session`), verificar tokens, o interactuar con la DB antes de aceptar al cliente. Si no deseas aceptar la conexión por permisos, puedes cerrarla arrojando una excepción o llamando `await websocket.close()`.
2. **`on_receive(websocket, data)`**: El corazón de la comunicación. Por ser `JsonWebSocketHandler`, el parámetro `data` ya viene parseado y validado como Diccionario de Python.
3. **`on_disconnect(websocket, close_code)`**: Ideal para limpiar memoria, eliminar al usuario de "salas de chat" activas en diccionarios globales o actualizar su estado en base de datos.

## Enrutamiento de WebSockets

A diferencia de las rutas HTTP (`Route()`), los WebSockets se registran explícitamente usando la clase `WebSocketRoute()` en tu archivo `routes.py`.

```python
# routes.py
from starlette.routing import Route, WebSocketRoute
from modules.chat_ws import ChatHandler

routes = [
    # ... tus rutas HTTP ...
    
    # Montando el WebSocket
    WebSocketRoute('/ws/chat', ChatHandler()),
]
```

## Conexiones en el Frontend (Vanilla JS)

La conexión desde el navegador HTML/JavaScript es directa e instanciada mediante el estándar de browser `WebSocket`.

```javascript
// Asegúrate de usar wss:// si estás en producción bajo HTTPS
const ws = new WebSocket('ws://localhost:8000/ws/chat');

ws.onopen = function(event) {
    console.log("WebSocket Abierto");
    
    // Enviando un payload JSON al servidor
    ws.send(JSON.stringify({ asusnto: "Hola Servidor!" }));
};

ws.onmessage = function(event) {
    // Escuchando los envíos JSON de regreso del Servidor
    const response = JSON.parse(event.data);
    console.log("Servidor dice:", response);
};

ws.onclose = function(event) {
    console.log("WebSocket Cerrado");
};
```

*(Recuerda que si configuras tu despliegue en un VPS con Nginx como proxy inverso, el bloque `location /ws` de Nginx requerirá las directivas `proxy_set_header Upgrade $http_upgrade;` y `proxy_set_header Connection "Upgrade";` para evitar truncar el canal).*
