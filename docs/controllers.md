# Controladores

Los controladores en Nori son el nexo entre tus Modelos (Base de datos) y tus Vistas (Templates/JSON). Se escriben como clases dentro de `rootsystem/application/modules/` para mantener las reglas de negocio encapsuladas e intuitivas.

## Estructura Básica

Un controlador consta de métodos asíncronos (`async def`). Todos los métodos de un controlador reciben exactamente dos argumentos: `self` y `request`, donde request es un objeto `Request` inyectado por Starlette.

```python
from starlette.requests import Request
from starlette.responses import JSONResponse
from core.jinja import templates
from core.auth.decorators import login_required

class ProductController:
    
    @login_required
    async def list(self, request: Request):
        return templates.TemplateResponse(request, 'product/list.html', {
            'title': 'Mis Productos'
        })
```

## El Objeto Request

El `request` tiene toda la información de la petición HTTP entrante. Todo en Nori es asíncrono, por lo tanto la lectura del *body* debe ser esperada (`await`).

**Lectura de datos:**
```python
async def store(self, request: Request):
    # Parámetros de query: /search?q=gatos
    query = request.query_params.get('q', 'default')

    # Parámetros de ruta dinámica: /products/5
    product_id = request.path_params['product_id']

    # Datos enviados por formulario (application/x-www-form-urlencoded o multipart/form-data)
    form = await request.form()
    name = form.get('name')

    # Datos JSON (application/json)
    data = await request.json()

    # Lectura de la IP del cliente
    ip = request.client.host
```

## Manejo Integrado (GET/POST)

Nori está diseñado para procesar el ciclo de vida completo de un formulario (pintarlo y procesarlo) en **un solo método** del controlador. 

Para lograrlo, la ruta recibe explícitamente ambos métodos (`methods=['GET', 'POST']`), y dentro del controlador simplemente consultas el verbo:

```python
from starlette.responses import RedirectResponse
from core.auth.csrf import csrf_field

async def create(self, request: Request):
    # 1. Pintamos el fomulario cuando el usuario llega a la URL
    if request.method == 'GET':
        return templates.TemplateResponse(request, 'product/form.html', {
            'csrf_field': csrf_field(request.session),
            'errors': {}
        })

    # 2. Si el usuario envía POST, procesamos la lógica aquí
    form = dict(await request.form())
    
    # [Lógica de validación omitida por brevedad]
    
    # 3. Guardado en DB y Redirección
    return RedirectResponse(url='/products', status_code=302)
```

## Formas de Responder

Dado que Nori corre enteramente sobre Starlette, todo controlador **debe retornar un objeto Response**.

### 1. Vistas HTML (Templates)
Utiliza la interfaz de `core.jinja.templates`. El primer parámetro es el request, el segundo es la ruta del HTML, y el tercero es opcionalmente un diccionario de variables para el template.

```python
from core.jinja import templates

return templates.TemplateResponse(request, 'auth/login.html', {'error': True})
```

### 2. Respuestas JSON (APIs)
Para devolver JSON crudo (por ejemplo, para fetch/axios u endpoints nativos).

```python
from starlette.responses import JSONResponse

return JSONResponse({'status': 'success', 'data': [1, 2, 3]})
```

### 3. Redirecciones
Exclusivamente usado tras modificaciones de estado (luego de un POST de creación, edición o borrado exitoso) para evitar doble-submits en caso de que el usuario recargue (F5).

```python
from starlette.responses import RedirectResponse

# status_code 302 ("Found")
# status_code 303 ("See Other") en respuestas a POSTs API
return RedirectResponse(url='/dashboard', status_code=302)
```

### 4. Errores y Excepciones
Si es necesario devolver manualmente un error como "No Encontrado" e invocar las páginas de error globales de Nori:

```python
from starlette.exceptions import HTTPException

async def show(self, request: Request):
    # si el producto no existe, abortamos con status 404:
    raise HTTPException(status_code=404, detail="Producto no localizado")
```
