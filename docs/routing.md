# Routing and Routes

All routes in Nori are defined in the `rootsystem/application/routes.py` file. The system is built on Starlette's native *router*, offering fast, explicit routing based on asynchronous endpoints.

Every route lives in one file because the entire app's URL surface should be visible at a glance. No routes hidden in decorators across dozens of files. A new developer can open `routes.py` and map the full API in seconds.

## Route Declaration

To map a URL to a controller, the `Route` class is used. We recommend instantiating controllers as *singletons* at the beginning of the file to keep memory clean and avoid excessive instantiation.

```python
from starlette.routing import Route
from modules.page import PageController

page = PageController()

routes = [
    Route('/', endpoint=page.home, methods=['GET'], name='page.home'),
    Route('/about', endpoint=page.about, methods=['GET'], name='page.about'),
]
```

### Components of a `Route`:
1. **Path (`'/'`)**: The URL.
2. **Endpoint (`endpoint=page.home`)**: The asynchronous method in your controller that will handle the request.
3. **Methods (`methods=['GET']`)**: An explicit list of accepted HTTP verbs. Always required.
4. **Name (`name='page.home'`)**: A unique identifier using **dot-notation** (`module.action`) to generate reverse links. Examples: `articles.show`, `auth.login`, `page.home`.

## Route Grouping (Mount)

To group URLs under a common prefix (for example, `/products`), use `Mount`. This is ideal for CRUD endpoints.

```python
from starlette.routing import Mount
from modules.product import ProductController

product = ProductController()

routes = [
    Mount('/products', routes=[
        Route('/', endpoint=product.list, methods=['GET'], name='products.list'),
        Route('/create', endpoint=product.create, methods=['GET', 'POST'], name='products.create'),
        Route('/{product_id:int}', endpoint=product.show, methods=['GET'], name='products.show'),
        Route('/{product_id:int}/edit', endpoint=product.edit, methods=['GET', 'POST'], name='products.edit'),
        Route('/{product_id:int}/delete', endpoint=product.delete, methods=['POST'], name='products.delete'),
    ]),
]
```

## Route Parameters (Path Params)

You can capture variables directly from the URL using `{name:type}`. 

```python
Route('/users/{user_id:int}/posts/{post_id:int}', endpoint=user.show_post, methods=['GET'])
```

In your controller, these are accessed via `request.path_params`:

```python
async def show_post(self, request: Request):
    user_id = request.path_params['user_id']
    post_id = request.path_params['post_id']
    # user_id and post_id are already integers thanks to ':int'
```

Available default types in Starlette:
- `:str` (default if omitted)
- `:int` (converts to integer)
- `:float` (converts to float)
- `:uuid` (converts to a UUID object)
- `:path` (captures the rest of the path, including `/` slashes)

## URL Generation (Reversing)

Instead of hardcoding URLs like `/products/5/edit` into your code, you can (and should) generate them using the `name` argument defined in the route.

**In a controller:**
```python
url = request.url_for('products.edit', product_id=5)
# url = RequestURL('http://yourdomain.com/products/5/edit')
```

**In your Jinja Templates:**
```html
<a href="{{ request.url_for('products.edit', product_id=p.id) }}">Edit Product</a>
```

## Best Security Practices in Routes

All routes that execute a destructive action (e.g.: Delete product, Log out, Change password) must be **strictly POST** (or structured as an API with PUT/DELETE).

Never use `GET` for actions that change state, as the browser could pre-fetch the links, or an attacker could send the link to an admin to trick them and execute the unintended action (CSRF Vulnerability).

```python
# CORRECT
Route('/logout', endpoint=auth.logout, methods=['POST'], name='logout')

# INCORRECT - Exposed to CSRF via image tags or links
Route('/logout', endpoint=auth.logout, methods=['GET'], name='logout')
```

## WebSocket Routes

For real-time endpoints, use `WebSocketRoute` instead of `Route`:

```python
from starlette.routing import WebSocketRoute
from modules.chat_ws import ChatHandler

routes = [
    # ... HTTP routes ...
    WebSocketRoute('/ws/chat', ChatHandler(), name='ws.chat'),
]
```

WebSocket routes do not use `methods=` but should include a `name=` using dot-notation (prefix with `ws.`). For full details on WebSocket handlers, see [WebSockets](websockets.md).
