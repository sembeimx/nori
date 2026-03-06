from starlette.routing import Route, WebSocketRoute
from modules.page import PageController
from modules.echo import EchoHandler
from modules.health import HealthController

# Singletons
page = PageController()
echo = EchoHandler()
health = HealthController()

routes = [
    # Health
    Route('/health', endpoint=health.check, methods=['GET'], name='health'),

    # Pages
    Route('/', endpoint=page.home, methods=['GET'], name='home'),

    # WebSockets
    WebSocketRoute('/ws/echo', endpoint=echo, name='ws_echo'),
]
