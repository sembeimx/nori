# Controllers

Controllers in Nori are the bridge between your Models (Database) and your Views (Templates/JSON). They are written as classes inside `rootsystem/application/modules/` to keep business rules encapsulated and intuitive.

## Basic Structure

A controller consists of asynchronous methods (`async def`). All methods in a controller receive exactly two arguments: `self` and `request`, where request is a `Request` object injected by Starlette.

```python
from starlette.requests import Request
from starlette.responses import JSONResponse
from core.jinja import templates
from core.auth.decorators import login_required

class ProductController:
    
    @login_required
    async def list(self, request: Request):
        return templates.TemplateResponse(request, 'product/list.html', {
            'title': 'My Products'
        })
```

## The Request Object

The `request` has all the information about the incoming HTTP request. Everything in Nori is asynchronous, therefore reading the *body* must be awaited (`await`).

**Reading data:**
```python
async def store(self, request: Request):
    # Query parameters: /search?q=cats
    query = request.query_params.get('q', 'default')

    # Dynamic route parameters: /products/5
    product_id = request.path_params['product_id']

    # Data sent by form (application/x-www-form-urlencoded or multipart/form-data)
    form = await request.form()
    name = form.get('name')

    # JSON Data (application/json)
    data = await request.json()

    # Reading the client IP
    ip = request.client.host
```

## Integrated Handling (GET/POST)

Nori is designed to process the entire life cycle of a form (rendering it and processing it) in **a single controller method**. 

To achieve this, the route explicitly receives both methods (`methods=['GET', 'POST']`), and inside the controller you simply check the verb:

```python
from starlette.responses import RedirectResponse
from core.auth.csrf import csrf_field

async def create(self, request: Request):
    # 1. We render the form when the user arrives at the URL
    if request.method == 'GET':
        return templates.TemplateResponse(request, 'product/form.html', {
            'csrf_field': csrf_field(request.session),
            'errors': {}
        })

    # 2. If the user sends a POST, we process the logic here
    form = dict(await request.form())
    
    # [Validation logic omitted for brevity]
    
    # 3. DB Save and Redirect
    return RedirectResponse(url='/products', status_code=302)
```

## Ways to Respond

Since Nori runs entirely on Starlette, every controller **must return a Response object**.

### 1. HTML Views (Templates)
Uses the `core.jinja.templates` interface. The first parameter is the request, the second is the HTML path, and the third is optionally a dictionary of variables for the template.

```python
from core.jinja import templates

return templates.TemplateResponse(request, 'auth/login.html', {'error': True})
```

### 2. JSON Responses (APIs)
To return raw JSON (for example, for fetch/axios or native endpoints).

```python
from starlette.responses import JSONResponse

return JSONResponse({'status': 'success', 'data': [1, 2, 3]})
```

### 3. Redirects
Exclusively used after state modifications (after a successful creation, edit, or deletion POST) to prevent double-submits in case the user reloads (F5).

```python
from starlette.responses import RedirectResponse

# status_code 302 ("Found")
# status_code 303 ("See Other") in responses to API POSTs
return RedirectResponse(url='/dashboard', status_code=302)
```

### 4. Errors and Exceptions
If you need to manually return an error like "Not Found" and invoke Nori's global error pages:

```python
from starlette.exceptions import HTTPException

async def show(self, request: Request):
    # if the product does not exist, abort with status 404:
    raise HTTPException(status_code=404, detail="Product not found")
```
