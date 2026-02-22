# Nori

Un *boilerplate* web asíncrono construido sobre **Starlette** y **Tortoise ORM** que preserva la ergonomía de desarrollo rápida inspirada en frameworks como Laravel o Nori Engine: estructura de archivos plana, controladores basados en clases, validación declarativa por pipes (`required|email|max:255`), decoradores de autenticación, JWT, CSRF propio, un agrupador de colecciones ágil (`NoriCollection`), WebSockets, Rate Limiting distribuido (Redis), y utilidades nativas para envíos de Email y subida de archivos.

---

## Puesta en Marcha

### Requisitos

- Python 3.9 o superior
- Una base de datos: **MySQL**, **PostgreSQL** o **SQLite**

### Instalacion

```bash
git clone <tu-repo> && cd nori

# Entorno virtual
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Dependencias
pip install -r requirements.txt
```

### Configuracion

Nori usa variables de entorno via `python-dotenv`. Copia la plantilla y edita segun tu motor de DB:

```bash
cp .env.example rootsystem/application/.env
```

**SQLite** (recomendado para empezar rapido, sin instalar motor):

```env
DEBUG=true
SECRET_KEY=mi-clave-secreta

DB_ENGINE=sqlite
DB_NAME=db.sqlite3
```

**MySQL:**

```env
DB_ENGINE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=nori_app
```

**PostgreSQL:**

```env
DB_ENGINE=postgres
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=
DB_NAME=nori_app
```

### Arrancar el Servidor (Local)

```bash
cd rootsystem/application
uvicorn asgi:app --reload --host 0.0.0.0 --port 8000
```

### Arrancar con Docker (Alternativa)

Si prefieres usar Docker, el proyecto incluye un `Dockerfile` y `docker-compose.yml` preconfigurado que levanta la app y una base de datos MySQL automáticamente.

1. Copia y ajusta tu `.env` si aún no lo has hecho:
   ```bash
   cp .env.example rootsystem/application/.env
   ```

2. Verifica que el `.env` apunte al servicio `db`:
   ```env
   DB_ENGINE=mysql
   DB_HOST=db
   ```

3. Levanta los servicios (esto construirá la imagen e iniciará MySQL y Nori):
   ```bash
   docker compose up -d --build
   ```

Abre `http://localhost:8000` en tu navegador para ver la aplicación corriendo.

---

## Despliegue en Producción

Para entornos de producción (Linux/VPS), se recomienda servir Nori usando **Gunicorn** como administrador de procesos (workers), controlado por **Systemd**, y expuesto a internet mediante un proxy inverso como **Nginx** o **Apache**.

### 1. Iniciar con Gunicorn

El proyecto ya cuenta con un archivo `gunicorn.conf.py` configurado para usar `uvicorn.workers.UvicornWorker` y escalar los workers dinámicamente según los núcleos de tu CPU. Puedes probarlo ejecutando:

```bash
cd rootsystem/application
gunicorn asgi:app -c ../gunicorn.conf.py
```

### 2. Configurar Systemd (Servicio en Segundo Plano)

Crea un archivo de servicio, por ejemplo `/etc/systemd/system/nori.service`:

```ini
[Unit]
Description=Nori Gunicorn Daemon
After=network.target

[Service]
User=tu_usuario
Group=www-data
WorkingDirectory=/ruta/a/tu/proyecto/nori/rootsystem/application
Environment="PATH=/ruta/a/tu/proyecto/nori/.venv/bin"
ExecStart=/ruta/a/tu/proyecto/nori/.venv/bin/gunicorn asgi:app -c ../gunicorn.conf.py

[Install]
WantedBy=multi-user.target
```

Luego inicia y habilita el servicio para que corra al arrancar el servidor:
```bash
sudo systemctl daemon-reload
sudo systemctl start nori
sudo systemctl enable nori
```

### 3. Configurar Nginx (Proxy Inverso)

Añade este bloque a la configuración de tu sitio en Nginx (`/etc/nginx/sites-available/nori`):

```nginx
server {
    listen 80;
    server_name tu_dominio.com;

    # Servir archivos estáticos directamente para mayor rendimiento
    location /static/ {
        alias /ruta/a/tu/proyecto/nori/rootsystem/static/;
    }

    # Redirigir el resto del tráfico a Gunicorn
    location / {
        proxy_pass http://127.0.0.0:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Habilita el sitio y reinicia Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/nori /etc/nginx/sites-enabled
sudo systemctl restart nginx
```

### 4. Configurar Apache (Proxy Inverso Alternativo)

Si prefieres usar Apache en lugar de Nginx, asegúrate de habilitar los módulos de proxy necesarios primero:

```bash
sudo a2enmod proxy proxy_http proxy_wstunnel headers
sudo systemctl restart apache2
```

Añade este bloque a la configuración virtual de tu sitio (e.g. `/etc/apache2/sites-available/nori.conf`):

```apache
<VirtualHost *:80>
    ServerName tu_dominio.com

    # Servir archivos estáticos nativamente
    Alias /static /ruta/a/tu/proyecto/nori/rootsystem/static

    <Directory /ruta/a/tu/proyecto/nori/rootsystem/static>
        Require all granted
    </Directory>

    # Redirigir tráfico a Gunicorn
    ProxyPreserveHost On
    ProxyPass /static !
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # Cabeceras útiles
    RequestHeader set X-Forwarded-Proto "http"
</VirtualHost>
```

Habilita el sitio en Apache y recarga:
```bash
sudo a2ensite nori
sudo systemctl reload apache2
```

---

## Arquitectura del Proyecto

```
nori/
├── .env.example                     ← Plantilla de variables de entorno
├── requirements.txt                 ← Dependencias Python
├── tests/                           ← Tests E2E y de API (httpx + SQLite en memoria)
│   ├── conftest.py                  ← Fixtures: app ASGI, DB en memoria, client async
│   ├── test_api/test_auth.py        ← Tests de endpoints de autenticacion
│   └── test_core/                   ← Tests unitarios de core (collection, validation)
│
└── rootsystem/
    ├── static/                      ← Archivos estaticos (CSS, JS, imagenes)
    ├── templates/                   ← Vistas Jinja2
    │   ├── base.html                ← Layout base con nav
    │   ├── 500.html                 ← Pagina de error interno (produccion)
    │   ├── auth/                    ← Login, registro, perfil
    │   └── product/                 ← Listado, detalle, formulario
    └── application/
        ├── asgi.py                  ← Entry point ASGI, middleware stack, error handler
        ├── settings.py              ← Configuracion (DB, debug, rutas de templates)
        ├── routes.py                ← Rutas con nombres, agrupadas con Mount
        ├── models/                  ← Modelos Tortoise ORM
        │   ├── user.py              ← User (id, name, email, password, level, status)
        │   └── product.py           ← Product (id, name, price, status)
        ├── modules/                 ← Controladores (clases con metodos por accion)
        │   ├── auth.py              ← Login, logout, registro, perfil
        │   ├── page.py              ← Paginas estaticas (home)
        │   └── product.py           ← CRUD de productos
        └── core/                    ← Motor del framework
            ├── jinja.py             ← Instancia Jinja2Templates + globals
            ├── logger.py            ← Logger centralizado (nori.*)
            ├── collection.py        ← NoriCollection: listas con superpoderes
            ├── pagination.py        ← Paginador asincrono para QuerySets
            ├── auth/
            │   ├── security.py      ← PBKDF2 password hashing, tokens
            │   ├── csrf.py          ← Middleware CSRF + helpers
            │   └── decorators.py    ← @login_required, @require_role
            ├── http/
            │   └── validation.py    ← Validacion declarativa pipe-separated
            └── mixins/
                ├── model.py         ← NoriModelMixin (to_dict)
                ├── soft_deletes.py  ← NoriSoftDeletes (delete/restore/force_delete)
                └── tree.py          ← NoriTreeMixin (arboles con CTE recursivo)
```

---

## Rutas

Todas las rutas tienen nombre para reversing con `request.url_for()`:

| Metodo | Ruta | Nombre | Descripcion |
|---|---|---|---|
| `GET` | `/` | `home` | Pagina de inicio |
| `GET, POST` | `/login` | `login` | Formulario y procesamiento de login |
| `POST` | `/logout` | `logout` | Cierre de sesion (POST por seguridad CSRF) |
| `GET, POST` | `/register` | `register` | Formulario y procesamiento de registro |
| `GET` | `/profile` | `profile` | Perfil del usuario autenticado |
| `GET` | `/products/` | `product_list` | Listado paginado de productos |
| `GET, POST` | `/products/create` | `product_create` | Formulario y creacion |
| `GET` | `/products/{id}` | `product_show` | Detalle de producto |
| `GET, POST` | `/products/{id}/edit` | `product_edit` | Formulario y edicion |
| `POST` | `/products/{id}/delete` | `product_delete` | Eliminacion de producto |

---

## Documentación del Framework

Nori está documentado en un formato modular para que encuentres rápidamente lo que necesitas. Consulta las guías a continuación:

### Fundamentos
* **[Enrutamiento y Rutas](docs/routing.md):** Definir verbos HTTP, Path params (`/user/{id}`), y Reverse Routing.
* **[Controladores](docs/controllers.md):** Clases HTTP estandarizadas, el objeto `Request`, y Tipos de Respuesta (JSON, HTML, Redirecciones).
* **[Base de Datos (Tortoise ORM)](docs/database.md):** Creación de Modelos Básicos, Relaciones, y Mixins avanzados (NoriSoftDeletes, NoriTreeMixin).
* **[Plantillas (Jinja2)](docs/templates.md):** Renderizado de vistas, Blocks e Inyección de Archivos Estáticos `/static/`.

### Lógica Avanzada
* **[Colecciones Nori](docs/collections.md):** El envoltorio ágil similar a Laravel Collections (`collect()`), `map`, `filter`, `where`, y Paginación asíncrona nativa (`paginate()`).
* **[Formularios, CSRF y Validación](docs/forms_validation.md):** Prevención de inyección CSRF (`csrf_field`), Validadores declarativos Pipe-separated (`required|email|max:20`).
* **[Autenticación y Sesiones](docs/authentication.md):** Login clásico por Cookies, Hashing Automático PBKDF2 (`Security`), APIs Stateless por JSON Web Tokens (JWT), y Restricciones de Controladores (`@login_required`, `@require_role`).
* **[Seguridad y Limitadores](docs/security.md):** Protección de fuerza bruta distribuida (`@throttle` via memoria/Redis) y Cabeceras Strict HTTP automáticas.
* **[WebSockets (Tiempo Real)](docs/websockets.md):** Manejo orientado a objetos JSON de conexiones persistentes para chats y notificaciones `ws://`.
* **[Servicios Integrados](docs/services.md):** Motor de Envíos Masivos SMTP asíncronos (`send_mail` visual por Jinja2) y carga segura en disco de FileUploads genéricos (`save_upload`).

---

## Agregar un Nuevo Modulo

1. **Modelo**: Crea tu entidad en `models/` y registrala en `models/__init__.py` y en `settings.TORTOISE_ORM['apps']['models']['models']`.
2. **Controlador**: Crea una clase en `modules/` con metodos async por accion.
3. **Rutas**: Instancia el controlador en `routes.py` y monta las rutas con `name=` para reversing.
4. **Templates**: Disena las vistas en `templates/`.
5. **Tests**: Agrega tests en la carpeta unificada `tests/` (por ejemplo, unitarios en `tests/test_core/` o E2E en `tests/test_api/`).

---

## Pruebas

El proyecto cuenta con una robusta suite unificada combinando unit tests y flujos E2E:

```bash
# Suite completa
pytest tests/ -v
```

Los tests utilizan `conftest.py` para levantar la app completa y realizar aserciones de forma aislada sin tocar la DB local, valiéndose de un SQLite persistido *in-memory* y `httpx.AsyncClient`.

---

## Variables de Entorno

| Variable | Default | Descripcion |
|---|---|---|
| `DEBUG` | `false` | Modo debug (`true` = traceback interactivo, `false` = error handler 500) |
| `SECRET_KEY` | `change-me-in-production` | Clave para sesiones y tokens |
| `DB_ENGINE` | `mysql` | Motor de DB: `mysql`, `postgres` o `sqlite` |
| `DB_HOST` | `localhost` | Host de la base de datos (MySQL/Postgres) |
| `DB_PORT` | `3306` / `5432` | Puerto (auto-detectado segun engine) |
| `DB_USER` | *(vacio)* | Usuario de la base de datos |
| `DB_PASSWORD` | *(vacio)* | Password de la base de datos |
| `DB_NAME` | *(vacio)* / `db.sqlite3` | Nombre de la DB o path del archivo SQLite |
| `THROTTLE_BACKEND` | `memory` | Backend de rate limiting (`memory` o `redis`) |
| `REDIS_URL` | `redis://localhost:6379` | Cadena de conexión a Redis (si se usa) |
| `JWT_SECRET` | *Mismo que SECRET_KEY* | Secreto de firmado JWT |
| `JWT_EXPIRATION` | `3600` | Expiración de tokens JWT en segundos |
| `MAIL_HOST` | `localhost` | Servidor SMTP |
| `MAIL_PORT` | `587` | Puerto SMTP |
| `MAIL_USER` / `MAIL_PASSWORD` | *(vacios)* | Credenciales SMTP |
| `UPLOAD_DIR` | `uploads/` | Directorio destino para archivos estáticos |
| `UPLOAD_MAX_SIZE` | `10485760` (10MB) | Límite por defecto de archivos subidos |

---

## Contribucion

Las contribuciones son bienvenidas. Para colaborar:

1. Haz un fork del repositorio.
2. Crea una rama para tu feature o fix: `git checkout -b mi-feature`.
3. Realiza tus cambios siguiendo las convenciones del proyecto:
   - Controladores como clases en `modules/`.
   - Type hints con `from __future__ import annotations` en modulos core.
   - Tests para logica nueva agrupados en la suite `tests/`.
4. Asegurate de que toda la suite pase: `pytest -v`.
5. Haz commit con un mensaje descriptivo y envia un Pull Request.

### Convenciones de Codigo

- **Rutas**: siempre con `name=` y metodos explicitos (`methods=['GET']`).
- **Logout y acciones destructivas**: solo `POST` (nunca `GET` para evitar CSRF via links).
- **Validacion**: usar el validador declarativo en lugar de validacion manual.
- **Modelos**: heredar de `NoriModelMixin` para `to_dict()`.

---

## Licencia

Este proyecto se distribuye bajo la licencia **MIT**. Consulta el archivo [LICENSE](LICENSE) para mas detalles.
