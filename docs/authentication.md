# Autenticación y Autorización

Nori proporciona un sistema de autenticación completo y listo para usar que incluye middlewares de sesión, decorators de rutas para permisos, autenticación basada en JSON Web Tokens (JWT) para APIs, y manejo seguro de contraseñas mediante hashing PBKDF2-SHA256.

## Hash de Contraseñas (Security)

Para crear usuarios o validar logins manuales, siempre debes utilizar la clase `Security` proporcionada por el framework en `core.auth.security`. 

```python
from core.auth.security import Security

# Hashing de contraseña plana
hashed_password = Security.hash_password('mi_password_secreta')
# 'pbkdf2_sha256$100000$salt$hash'

# Comparación / Verificación
es_valida = Security.verify_password('mi_password_secreta', hashed_password) # True
```

`Security` también ofrece generadores rápidos de tokens hexadecimales estocásticos:
```python
token = Security.generate_token()      # 64 caracteres hex
csrf = Security.generate_csrf_token()  # 64 caracteres hex
```

## Middlewares de Sesión

Nori administra el estado del usuario logueado en una cookie de sesión cifrada por la clave `SECRET_KEY` del `.env`.

Para iniciar sesión tras validar la contraseña correctamente, simplemente inyectas variables al dict `request.session`:

```python
async def login(self, request: Request):
    # [Lógica de validación omitida]
    
    # Iniciar Sesión ("Login" efectivo)
    request.session['user_id'] = str(user.id)
    request.session['role'] = 'admin' if user.level > 0 else 'user'
    
    return RedirectResponse(url='/dashboard', status_code=302)

async def logout(self, request: Request):
    # Cerrar Sesión
    request.session.clear()
    
    return RedirectResponse(url='/', status_code=302)
```

## Restricción de Vistas (Decoradores)

Puedes restringir controladores enteros omitiendo o aplicando decoradores según tu necesidad. Se aplican por encima de la definición `async def`:

* `@login_required`
* `@require_role('mi_rol')`
* `@require_any_role('ventas', 'gerencia')`

*(Aviso: El string role `'admin'` posee un bypass general por defecto).*

```python
from core.auth.decorators import login_required, require_role, require_any_role

class DashboardController:

    @login_required # Obliga a que la sesión contenga el dict 'user_id' activo.
    async def account(self, request: Request):
        return ...

    @require_role('editor')
    async def change_password(self, request: Request):
        return ...
```

**Comportamiento de los decoradores:**
Dependiendo de qué intentó acceder el cliente, actúan inteligentemente (Negociación de Contenido por Header `Accept`):
* Si el cliente es un navegador (`Content-Type` HTML), redirigen transparentemente a `/login` (302) o `/forbidden` (403).
* Si el cliente es Fetch/AJAX HTTP puro (`application/json`), arrojan diccionarios JSON estándares `{"error": "Unauthorized"}` con códigos HTTP `401` y `403`.

---

## APIs y JSON Web Tokens (JWT)

Para crear API RESTfuls *Stateless*, el sistema de sesiones tradicional (cookies) no es el adecuado. Nori posee firmas HMAC-SHA256 nativas en `core.auth.jwt`.

### Crear un JWT (Login)
```python
from core.auth.jwt import create_token
from starlette.responses import JSONResponse

async def api_login(self, request: Request):
    # [Validar pwd...]
    
    # Payload general y envío JSON
    jwt_str = create_token({'user_id': user.id}, expires_in=3600)
    return JSONResponse({'token': jwt_str})
```
*Se firman validando contra la variable `JWT_SECRET` y expiran automáticamente bajo los contadores Unix Epoch de Nori.*

### Proteger Rutas API (Decorador)
```python
from core.auth.decorators import token_required

@token_required
async def api_profile(self, request: Request):
    # Si llegó aquí, el token existe, es válido y no expiró.
    
    # El payload inyectado se recupera directamente del decorador:
    user_id = request.state.jwt_payload['user_id']
    
    return JSONResponse({'status': 'ok', 'id': user_id})
```

El decorador leerá de forma implícita y nativa el header HTTP del request del cliente (`Authorization: Bearer <token_string_aqui>`). De no poseerlo devolverá Error `401 JSON` bloqueando la capa.
