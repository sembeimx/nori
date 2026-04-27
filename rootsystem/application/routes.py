from __future__ import annotations

from modules.echo import EchoHandler
from modules.health import HealthController
from modules.page import PageController
from starlette.routing import Route, WebSocketRoute

# Singletons
page = PageController()
echo = EchoHandler()
health = HealthController()

routes = [
    # Health
    Route('/health', endpoint=health.check, methods=['GET'], name='health.check'),

    # Pages
    Route('/', endpoint=page.home, methods=['GET'], name='page.home'),

    # WebSockets
    WebSocketRoute('/ws/echo', endpoint=echo, name='ws.echo'),
]
