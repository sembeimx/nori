# Roadmap — Lo que falta para una app grande

Estado actual de Nori y las piezas que faltan para soportar aplicaciones de produccion a escala.

---

## Lo que ya existe

| Area | Implementado |
|------|-------------|
| **HTTP** | Security headers, CORS, sesiones, CSRF, rate limiting (con backends pluggables), flash messages |
| **Auth** | Login/logout/register, password hashing PBKDF2, decoradores de roles (`login_required`, `require_role`, `require_any_role`), JWT con `@token_required` |
| **Validacion** | Reglas declarativas: `required`, `min`, `max`, `email`, `numeric`, `matches`, `in`, `file`, `file_max`, `file_types`. Mensajes custom |
| **Base de datos** | Tortoise ORM (MySQL, PostgreSQL, SQLite), soft deletes, tree mixin con CTEs recursivos, `to_dict()` |
| **File Uploads** | `save_upload()` con validacion de extension, MIME type, tamaño maximo, nombres UUID |
| **Email** | `send_mail()` con aiosmtplib, soporte templates Jinja2, MIME multipart |
| **JWT / API Tokens** | HMAC-SHA256 manual (`create_token`, `verify_token`), decorator `@token_required` para APIs |
| **Rate Limiting** | Backends pluggables: `MemoryBackend` (default) y `RedisBackend` (sorted sets). Config via `THROTTLE_BACKEND` |
| **WebSockets** | `WebSocketHandler` y `JsonWebSocketHandler` base classes, ruta `/ws/echo` de ejemplo |
| **Utilidades** | NoriCollection (17 metodos), paginacion async, flash messages |
| **Templates** | Jinja2 con globals (`csrf_field`, `get_flashed_messages`), template base para emails |
| **Config** | `.env` con `python-dotenv`, settings centralizados |
| **Logging** | Logger `nori.*` con formato timestamp, nivel por DEBUG flag |
| **Deployment** | Dockerfile multi-stage, docker-compose.yml (app + MySQL), gunicorn con UvicornWorker |
| **Error Handling** | Handlers custom para 404 (JSON + HTML) y 500 |
| **Tests** | pytest + pytest-asyncio, 129 tests (unitarios + E2E con httpx) |

---

## Lo que falta

### Prioridad 1 — Bloquea produccion

#### Migraciones de base de datos

**Problema**: No hay forma de modificar el schema de la DB sin SQL manual. `Tortoise.generate_schemas()` solo funciona en DB nueva.

**Solucion**: Integrar [Aerich](https://github.com/tortoise/aerich) (migraciones nativas de Tortoise ORM).

**Alcance**:
- Agregar `aerich` a `requirements.txt`
- Configurar en `settings.py` apuntando a `TORTOISE_ORM`
- Crear script o comando para `init`, `migrate`, `upgrade`, `downgrade`
- Documentar workflow de migraciones

---

### Prioridad 2 — Limita funcionalidad

#### Background tasks

**Problema**: Todo se ejecuta dentro del request. Operaciones lentas (emails, procesamiento de archivos, reportes) bloquean la respuesta.

**Solucion**: Aprovechar `BackgroundTask` de Starlette para tareas simples. Para colas persistentes, integrar con herramientas externas.

**Alcance**:
- Fase 1: Helper para `BackgroundTask` de Starlette (in-process, sin persistencia)
- Fase 2 (opcional): Integrar con sistema de colas externo si se necesita persistencia

---

#### Caching

**Problema**: Cada request golpea la DB. No hay cache de queries ni de vistas.

**Solucion**: Cache in-memory simple (mismo patron que throttle backends).

**Alcance**:
- Modulo `core/cache.py` con store in-memory (dict con TTL)
- Funciones: `cache_get(key)`, `cache_set(key, value, ttl)`, `cache_delete(key)`
- Decorator `@cache_response(ttl=60)` para cachear respuestas de vistas
- Backend pluggable (memory / Redis) reutilizando el patron de `throttle_backends.py`

---

### Prioridad 3 — Mejora calidad

#### Database seeding

**Problema**: No hay forma rapida de poblar la DB con datos de prueba para desarrollo.

**Solucion**: Sistema de seeders.

**Alcance**:
- Directorio `seeders/` con archivos por modelo
- Funcion factory para generar datos fake
- Comando para ejecutar seeders

---

#### Structured logging

**Problema**: Los logs son texto plano. En produccion se necesitan logs estructurados (JSON) para herramientas como ELK, CloudWatch, Datadog.

**Solucion**: Extender `core/logger.py`.

**Alcance**:
- Formato JSON cuando `DEBUG=False`
- Campos automaticos: timestamp, level, request_id, ip, path
- Middleware para inyectar request_id en cada request

---

#### Request ID / Tracing

**Problema**: No hay forma de correlacionar logs de un mismo request.

**Solucion**: Middleware que genera un UUID por request.

**Alcance**:
- Middleware que genera `X-Request-ID` header
- Inyectar en el logger context
- Propagable a servicios downstream

---

#### Test factories

**Problema**: Los tests que necesitan modelos deben crearlos manualmente. Boilerplate repetitivo.

**Solucion**: Factories por modelo.

**Alcance**:
- Funcion `make_user(**overrides)` que crea User con defaults sensatos
- Funcion `make_product(**overrides)` idem
- Pattern para que cada modelo nuevo tenga su factory

---

### Prioridad 4 — Features avanzados

| Feature | Descripcion | Cuando implementar |
|---------|-------------|-------------------|
| **Admin panel** | Interfaz CRUD generada automaticamente a partir de los modelos | Cuando se necesite gestion sin codigo custom |
| **OAuth / Social login** | Login con Google, GitHub, etc. | Cuando se necesite auth de terceros |
| **Permisos granulares** | ACL por recurso (no solo por rol) | Cuando los roles no sean suficientes |
| **i18n** | Internacionalizacion de mensajes y templates | Cuando se necesite soporte multi-idioma |
| **OpenAPI / Swagger** | Documentacion automatica de endpoints API | Cuando se expongan APIs publicas |
| **Audit logging** | Registro de quien hizo que y cuando | Cuando se necesite trazabilidad de acciones |
| **2FA** | Autenticacion de dos factores (TOTP) | Cuando la seguridad lo requiera |

---

## Orden sugerido de implementacion

```
1. Migraciones (Aerich)        ← sin esto no se puede evolucionar la DB
2. Background tasks            ← desbloquea emails y procesamiento async
3. Caching                     ← mejora performance
4. Database seeding            ← mejora DX en desarrollo
5. Structured logging          ← necesario para monitoreo en produccion
```

Cada item es independiente y se puede implementar sin afectar los demas. La arquitectura actual soporta todas estas adiciones sin refactoring.

---

## Implementado recientemente

Los siguientes items del roadmap original fueron completados:

| Feature | Archivos principales | Tests |
|---------|---------------------|-------|
| **Error 404** | `asgi.py`, `templates/404.html` | `test_404.py` (2) |
| **Deployment** | `Dockerfile`, `docker-compose.yml`, `gunicorn.conf.py`, `.dockerignore` | — |
| **File Uploads** | `core/http/upload.py`, `core/http/validation.py` (reglas file) | `test_upload.py` (5) |
| **Email** | `core/mail.py`, `templates/email/base_email.html` | `test_mail.py` (4) |
| **JWT / API Tokens** | `core/auth/jwt.py`, `core/auth/decorators.py` (`@token_required`) | `test_jwt.py` (6), `test_token_required.py` (4) |
| **Rate Limiting Distribuido** | `core/http/throttle_backends.py`, `core/http/throttle.py` (refactored) | `test_throttle_backends.py` (6) |
| **WebSockets** | `core/ws.py`, `modules/echo.py`, `routes.py` | `test_ws.py` (3) |
