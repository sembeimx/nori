# Routing y Rutas

Todas las rutas en Nori se definen en el archivo `rootsystem/application/routes.py`. El sistema está construido sobre el *router* nativo de Starlette, ofreciendo un enrutamiento rápido, explícito y basado en endpoints asíncronos.

## Declaración de Rutas

Para mapear una URL a un controlador, se utiliza la clase `Route`. Recomendamos instanciar los controladores como *singletons* al inicio del archivo para mantener la memoria limpia y evitar instanciación excesiva.

```python
from starlette.routing import Route
from modules.page import PageController

page = PageController()

routes = [
    Route('/', endpoint=page.home, methods=['GET'], name='home'),
    Route('/about', endpoint=page.about, methods=['GET'], name='about'),
]
```

### Componentes de una `Route`:
1. **Path (`'/'`)**: La URL.
2. **Endpoint (`endpoint=page.home`)**: El método asíncrono en tu controlador que manejará el request.
3. **Methods (`methods=['GET']`)**: Una lista explícita de los verbos HTTP aceptados.
4. **Name (`name='home'`)**: El identificador único para generar links reversos (URL Building).

## Agrupación de Rutas (Mount)

Para agrupar URLs bajo un prefijo común (por ejemplo, `/products`), utiliza `Mount`. Esto es ideal para los endpoints CRUD.

```python
from starlette.routing import Mount
from modules.product import ProductController

product = ProductController()

routes = [
    Mount('/products', routes=[
        Route('/', endpoint=product.list, methods=['GET'], name='product_list'),
        Route('/create', endpoint=product.create, methods=['GET', 'POST'], name='product_create'),
        Route('/{product_id:int}', endpoint=product.show, methods=['GET'], name='product_show'),
        Route('/{product_id:int}/edit', endpoint=product.edit, methods=['GET', 'POST'], name='product_edit'),
        Route('/{product_id:int}/delete', endpoint=product.delete, methods=['POST'], name='product_delete'),
    ]),
]
```

## Parámetros de Ruta (Path Params)

Puedes capturar variables directamente desde la URL utilizando `{nombre:tipo}`. 

```python
Route('/users/{user_id:int}/posts/{post_id:int}', endpoint=user.show_post, methods=['GET'])
```

En tu controlador, estos se acceden mediante `request.path_params`:

```python
async def show_post(self, request: Request):
    user_id = request.path_params['user_id']
    post_id = request.path_params['post_id']
    # user_id y post_id ya son enteros gracias a ':int'
```

Tipos disponibles por defecto en Starlette:
- `:str` (por defecto si se omite)
- `:int` (convierte a entero)
- `:float` (convierte a flotante)
- `:uuid` (convierte a objeto UUID)
- `:path` (captura el resto del path, ignorando las barras `/`)

## Generación de URLs (Reversing)

En vez de quemar (hardcodear) URLs como `/products/5/edit` en tu código, puedes (y deberías) generarlas usando el argumento `name` definido en la ruta.

**En un controlador:**
```python
url = request.url_for('product_edit', product_id=5)
# url = RequestURL('http://tudominio.com/products/5/edit')
```

**En tus Templates Jinja:**
```html
<a href="{{ request.url_for('product_edit', product_id=p.id) }}">Editar Producto</a>
```

## Mejores Prácticas de Seguridad en Rutas

Todas las rutas que ejecuten una acción destructiva (ej: Borrar producto, Cerrar sesión, Cambiar contraseña) deben ser **estrictamente POST** (o estructurarse como API con PUT/DELETE).

Nunca uses `GET` para acciones que cambian estado, ya que el navegador podría hacer un pre-fetch de los links, o un atacante podría enviar el link a un admin para engañarlo y ejecutar la acción no intencionada (Vulnerabilidad CSRF).

```python
# CORRECTO
Route('/logout', endpoint=auth.logout, methods=['POST'], name='logout')

# INCORRECTO - Expuesto a CSRF via tags de imagenes o links
Route('/logout', endpoint=auth.logout, methods=['GET'], name='logout')
```
