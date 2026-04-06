# Nori

An asynchronous web boilerplate built on **Starlette** and **Tortoise ORM** that preserves the fast, ergonomic development experience inspired by frameworks like Laravel or Nori Engine: a flat file structure, class-based controllers, declarative pipe-separated validation (`required|email|max:255`), authentication decorators, JWT, native CSRF, granular ACL permissions (`@require_permission`), audit logging, an agile collections wrapper (`NoriCollection`), WebSockets, distributed Rate Limiting (Redis), and native utilities for Email sending and file uploads.

---

## Getting Started

### Requirements

- Python 3.9 or higher
- A database: **MySQL**, **PostgreSQL** or **SQLite**

### Installation

```bash
git clone <your-repo> && cd nori

# Virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Dependencies
pip install -r requirements.txt
```

### Configuration

Nori uses environment variables via `python-dotenv`. Copy the template and edit it according to your DB engine:

```bash
cp .env.example rootsystem/application/.env
```

**SQLite** (recommended for a quick start without installing a database server):

```env
DEBUG=true
SECRET_KEY=my-secret-key

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

### Starting the Server (Local)

Nori includes an interactive CLI for rapid development with Hot Reloading for templates and the server.

```bash
python3 nori.py serve
```

*(Alternatively, you can run the application manually: `cd rootsystem/application && uvicorn asgi:app --reload --host 0.0.0.0 --port 8000`)*

### Starting with Docker (Alternative)

If you prefer using Docker, the project includes a `Dockerfile` and a pre-configured `docker-compose.yml` that automatically boots up the app and a MySQL database.

1. Copy and adjust your `.env` if you haven't already:
   ```bash
   cp .env.example rootsystem/application/.env
   ```

2. Verify that the `.env` points to the `db` service:
   ```env
   DB_ENGINE=mysql
   DB_HOST=db
   ```

3. Spin up the services (this will build the image and start MySQL and Nori):
   ```bash
   docker compose up -d --build
   ```

Open `http://localhost:8000` in your browser to see the application running.

---

## Production Deployment

For production environments (Linux/VPS), it is recommended to serve Nori using **Gunicorn** as a process manager (workers), controlled by **Systemd**, and exposed to the internet via a reverse proxy like **Nginx** or **Apache**.

### 1. Start with Gunicorn

The project already includes a `gunicorn.conf.py` file configured to use `uvicorn.workers.UvicornWorker` and scale the workers dynamically based on your CPU cores. You can test it by running:

```bash
cd rootsystem/application
gunicorn asgi:app -c ../gunicorn.conf.py
```

### 2. Configure Systemd (Background Daemon)

Create a service file, for example `/etc/systemd/system/nori.service`:

```ini
[Unit]
Description=Nori Gunicorn Daemon
After=network.target

[Service]
User=your_user
Group=www-data
WorkingDirectory=/path/to/your/project/nori/rootsystem/application
Environment="PATH=/path/to/your/project/nori/.venv/bin"
ExecStart=/path/to/your/project/nori/.venv/bin/gunicorn asgi:app -c ../gunicorn.conf.py

[Install]
WantedBy=multi-user.target
```

Then start and enable the service so it runs on server boot:
```bash
sudo systemctl daemon-reload
sudo systemctl start nori
sudo systemctl enable nori
```

### 3. Configure Nginx (Reverse Proxy)

Add this block to your Nginx site configuration (`/etc/nginx/sites-available/nori`):

```nginx
server {
    listen 80;
    server_name your_domain.com;

    # Serve static files directly for better performance
    location /static/ {
        alias /path/to/your/project/nori/rootsystem/static/;
    }

    # Proxy the rest of the traffic to Gunicorn
    location / {
        proxy_pass http://127.0.0.0:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/nori /etc/nginx/sites-enabled
sudo systemctl restart nginx
```

### 4. Configure Apache (Alternative Reverse Proxy)

If you prefer using Apache instead of Nginx, make sure to enable the necessary proxy modules first:

```bash
sudo a2enmod proxy proxy_http proxy_wstunnel headers
sudo systemctl restart apache2
```

Add this block to your site's virtual configuration (e.g. `/etc/apache2/sites-available/nori.conf`):

```apache
<VirtualHost *:80>
    ServerName your_domain.com

    # Serve static files natively
    Alias /static /path/to/your/project/nori/rootsystem/static

    <Directory /path/to/your/project/nori/rootsystem/static>
        Require all granted
    </Directory>

    # Proxy traffic to Gunicorn
    ProxyPreserveHost On
    ProxyPass /static !
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # Useful headers
    RequestHeader set X-Forwarded-Proto "http"
</VirtualHost>
```

Enable the site in Apache and reload:
```bash
sudo a2ensite nori
sudo systemctl reload apache2
```

---

## Project Architecture

```
nori/
├── .env.example                     ← Environment variables template
├── requirements.txt                 ← Python dependencies
├── tests/                           ← E2E and API Tests (httpx + in-memory SQLite)
│   ├── conftest.py                  ← Fixtures: ASGI app, in-memory DB, async client
│   ├── test_*.py                    ← Endpoint and integration tests
│   └── test_core/                   ← Core unit tests (collection, validation)
│
├── nori.py                          ← Nori Artisan CLI (make:controller, make:model, serve)
└── rootsystem/
    ├── static/                      ← Static files (CSS, JS, images)
    ├── templates/                   ← Jinja2 Views
    │   ├── base.html                ← Base layout with nav
    │   ├── 404.html/500.html        ← Error pages (production)
    │   └── home.html                ← Landing page
    └── application/
        ├── asgi.py                  ← ASGI entry point, middleware stack, error handler
        ├── settings.py              ← Configuration (DB, debug, template paths)
        ├── routes.py                ← Named routes, grouped with Mount
        ├── models/                  ← Application models
        │   ├── __init__.py          ← Model registration (App + Framework)
        │   └── framework/           ← Nori internal models (AuditLog, Job, etc.)
        ├── modules/                 ← Controllers (classes with methods per action)
        │   ├── echo.py              ← WebSockets demo
        │   └── page.py              ← Static pages (home)
        └── core/                    ← Framework engine (Independent)
            ├── conf.py              ← Config provider (Lazy Proxy)
            ├── registry.py          ← Model registry (Inversion of Control)
            ├── jinja.py             ← Jinja2Templates instance + globals
            ├── logger.py            ← Centralized logger (nori.*)
            ├── collection.py        ← NoriCollection: lists with superpowers
            ├── pagination.py        ← Async paginator for QuerySets
            ├── queue.py / worker.py ← Persistent Job Queue system
            ├── auth/
            │   ├── security.py      ← PBKDF2 password hashing, tokens
            │   ├── csrf.py          ← CSRF Middleware + helpers
            │   ├── jwt.py           ← JWT manual implementation
            │   ├── oauth.py         ← OAuth2 security helpers (PKCE/State)
            │   └── decorators.py    ← @login_required, @require_role, etc.
            ├── audit.py             ← Fire-and-forget audit logging
            ├── http/
            │   ├── inject.py        ← @inject decorator for DI
            │   └── validation.py    ← Declarative pipe-separated validation
            └── mixins/
                ├── model.py         ← NoriModelMixin (to_dict)
                ├── soft_deletes.py  ← NoriSoftDeletes
                └── tree.py          ← NoriTreeMixin (recursive CTE)
```

---

## Routes

All routes are named for reversing with `request.url_for()`:

| Method | Route | Name | Description |
|---|---|---|---|
| `GET` | `/` | `home` | Home page |
| `GET` | `/health` | `health` | Health check (DB connectivity, returns 200/503) |
| `WS` | `/ws/echo` | `ws_echo` | Test WebSocket connection |

---

## Framework Documentation

Nori is documented in a modular format so you can quickly find what you need. Check out the guides below:

### Fundamentals
* **[Routing and Routes](docs/routing.md):** Defining HTTP verbs, Path params (`/user/{id}`), and Reverse Routing.
* **[Controllers](docs/controllers.md):** Standardized HTTP classes, the `Request` object, and Response Types (JSON, HTML, Redirects).
* **[Database (Tortoise ORM)](docs/database.md):** Basic Model Creation, Relationships, and advanced Mixins (NoriSoftDeletes, NoriTreeMixin).
* **[Templates (Jinja2)](docs/templates.md):** Rendering views, Blocks, and Static File Injection `/static/`.

### Advanced Logic
* **[Nori Collections](docs/collections.md):** The agile wrapper similar to Laravel Collections (`collect()`), `map`, `filter`, `where`, and native async Pagination (`paginate()`).
* **[Forms, CSRF, and Validation](docs/forms_validation.md):** CSRF injection prevention (`csrf_field`), Declarative Pipe-separated validators (`required|email|max:20`).
* **[Authentication and Sessions](docs/authentication.md):** Classic Cookie login, Automatic PBKDF2 Hashing (`Security`), Stateless APIs via JSON Web Tokens (JWT), Controller Restrictions (`@login_required`, `@require_role`), and Granular ACL (`@require_permission`).
* **[Security and Rate Limiters](docs/security.md):** Distributed brute force protection (`@throttle` via memory/Redis) and automatic Strict HTTP Headers.
* **[WebSockets (Real-Time)](docs/websockets.md):** JSON object-oriented handling of persistent connections for chats and notifications `ws://`.
* **[Built-in Services](docs/services.md):** Async SMTP Mass Mailing engine (`send_mail` visual via Jinja2), secure disk saving for generic FileUploads (`save_upload`), and Audit Logging (`audit()`).

### Operations
* **[Deployment](docs/deployment.md):** Production checklist, Gunicorn + systemd, Nginx/Apache reverse proxy, SSL, Docker, Redis, sizing guide.
* **[Logging](docs/logging.md):** JSON/text formatters, rotating file handler, structured audit logs.
* **[Caching](docs/caching.md):** Memory and Redis backends, TTL, response caching decorator.
* **[Background Tasks](docs/background_tasks.md):** In-process async tasks with error logging.
* **[Philosophy](docs/philosophy.md):** What Nori is, design principles, and comparable frameworks.
* **[Roadmap](docs/roadmap.md):** Current state, production hardening gaps, and planned features.

---

## Nori CLI & New Modules

Nori includes its own command-line manager at the root to streamline your programming ("Nori Artisan"):

| Command | Description |
|---------|-------------|
| `python3 nori.py serve` | Start the dev server with hot reload |
| `python3 nori.py make:model Name` | Generate a model skeleton in `models/` |
| `python3 nori.py make:controller Name` | Generate a controller skeleton in `modules/` |
| `python3 nori.py make:seeder Name` | Generate a seeder skeleton in `seeders/` |
| `python3 nori.py migrate:init` | Initialize the Aerich migration system |
| `python3 nori.py migrate:make <name>` | Create a new migration from model changes |
| `python3 nori.py migrate:upgrade` | Run pending migrations |
| `python3 nori.py migrate:downgrade` | Roll back the last migration |
| `python3 nori.py db:seed` | Run all registered database seeders |
| `python3 nori.py queue:work` | Run the persistent job queue worker |
| `python3 nori.py framework:update` | Update Nori core from GitHub |
| `python3 nori.py framework:version` | Show current framework version |
4. **Dependency Injection (@inject)**: Forget about manually extracting dictionaries from the request. Use `@inject()` above your controller method and define parameters with native *Type Hints*:
   ```python
   from core.http.inject import inject

   @inject()
   async def create(self, request, form: dict, user_id: int):
       # user_id automatically extracted from ?user_id=X or from the path variable /user/{user_id}
       # form automatically parsed and converted to dict from await request.form()
       pass
   ```

---

## Testing

The project has a robust unified suite combining unit tests and E2E flows:

```bash
# Complete suite
pytest tests/ -v
```

Tests use `conftest.py` to boot up the entire app and perform assertions in isolation without touching the local DB, utilizing a persistent *in-memory* SQLite and `httpx.AsyncClient`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `false` | Debug mode (`true` = interactive traceback, `false` = 500 error handler) |
| `SECRET_KEY` | `change-me-in-production` | Key for sessions and tokens |
| `DB_ENGINE` | `mysql` | DB Engine: `mysql`, `postgres` or `sqlite` |
| `DB_HOST` | `localhost` | Database host (MySQL/Postgres) |
| `DB_PORT` | `3306` / `5432` | Port (auto-detected based on engine) |
| `DB_USER` | *(empty)* | Database user |
| `DB_PASSWORD` | *(empty)* | Database password |
| `DB_NAME` | *(empty)* / `db.sqlite3` | DB Name or SQLite file path |
| `THROTTLE_BACKEND` | `memory` | Rate limiting backend (`memory` or `redis`) |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string (if used) |
| `JWT_SECRET` | *Same as SECRET_KEY* | JWT signing secret |
| `JWT_EXPIRATION` | `3600` | JWT token expiration in seconds |
| `CORS_ORIGINS` | *(empty)* | Comma-separated allowed origins (empty = disabled) |
| `MAIL_HOST` | `localhost` | SMTP Server |
| `MAIL_PORT` | `587` | SMTP Port |
| `MAIL_USER` / `MAIL_PASSWORD` | *(empty)* | SMTP Credentials |
| `MAIL_FROM` | `noreply@example.com` | Default sender address |
| `MAIL_TLS` | `true` | Enable STARTTLS for SMTP |
| `UPLOAD_DIR` | `uploads/` | Destination directory for uploaded files |
| `UPLOAD_MAX_SIZE` | `10485760` (10MB) | Default limit for uploaded files |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `LOG_FORMAT` | `text` | Log output format (`text` or `json`) |
| `LOG_FILE` | *(empty)* | Optional log file path (enables rotating file handler) |

---

## Contributing

Contributions are welcome. To collaborate:

1. Fork the repository.
2. Create a branch for your feature or fix: `git checkout -b my-feature`.
3. Make your changes following the project conventions:
   - Controllers as classes in `modules/`.
   - Type hints with `from __future__ import annotations` in core modules.
   - Tests for new logic grouped in the `tests/` suite.
4. Ensure the entire suite passes: `pytest -v`.
5. Commit with a descriptive message and submit a Pull Request.

### Code Conventions

- **Routes**: always with `name=` and explicit methods (`methods=['GET']`).
- **Logout and destructive actions**: `POST` only (never `GET` to prevent CSRF via links).
- **Validation**: use the declarative validator instead of manual validation.
- **Models**: inherit from `NoriModelMixin` for `to_dict()`.

---

## License

This project is distributed under the **MIT** license. See the [LICENSE](LICENSE) file for more details.
