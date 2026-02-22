from starlette.routing import Route, WebSocketRoute
from modules.page import PageController
from modules.echo import EchoHandler

# Singletons
page = PageController()
echo = EchoHandler()

routes = [
    # Pages
    Route('/', endpoint=page.home, methods=['GET'], name='home'),

    # WebSockets
    WebSocketRoute('/ws/echo', endpoint=echo, name='ws_echo'),
]
