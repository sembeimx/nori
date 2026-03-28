# Deployment

How to take Nori from development to a production server.

---

## Environment checklist

Before deploying, verify these settings in your `.env`:

```env
# REQUIRED — must change from defaults
DEBUG=false
SECRET_KEY=<random-64-chars>
JWT_SECRET=<random-32-chars-different-from-SECRET_KEY>

# Database — use MySQL or PostgreSQL, never SQLite in production
DB_ENGINE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=nori_user
DB_PASSWORD=<strong-password>
DB_NAME=nori_app

# Recommended — switch memory backends to Redis
CACHE_BACKEND=redis
THROTTLE_BACKEND=redis
REDIS_URL=redis://localhost:6379

# Logging — use JSON for log aggregation, file for persistence
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=/var/log/nori/app.log

# Trusted proxies — set to your reverse proxy IP
TRUSTED_PROXIES=127.0.0.1
```

Generate secrets with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Nori validates critical settings at startup when `DEBUG=false` (`validate_settings()` in `settings.py`). It will refuse to start if:
- `SECRET_KEY` is still the default `'change-me'`
- `DB_USER` or `DB_PASSWORD` are missing (non-SQLite engines)
- `JWT_SECRET` equals `SECRET_KEY`
- `JWT_SECRET` is shorter than 32 characters
- `TEMPLATE_DIR` or `STATIC_DIR` do not exist on disk

---

## Single server (VPS)

The standard production stack is **Gunicorn + Uvicorn workers** behind **Nginx**, managed by **systemd**. This handles most sites comfortably up to several million visits/month on a single VPS.

### 1. Gunicorn

The project includes `gunicorn.conf.py` at the repository root:

```python
from multiprocessing import cpu_count

workers = cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8000"
```

This auto-scales workers based on CPU cores. On a 2-core VPS you get 5 workers, which is enough for hundreds of requests/second.

Test it manually before configuring systemd:

```bash
cd rootsystem/application
gunicorn asgi:app -c ../gunicorn.conf.py
```

To override workers or bind address without editing the file:

```bash
gunicorn asgi:app -c ../gunicorn.conf.py --workers 3 --bind 127.0.0.1:8000
```

### 2. Systemd service

Create `/etc/systemd/system/nori.service`:

```ini
[Unit]
Description=Nori Web Application
After=network.target mysql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/nori/rootsystem/application
Environment="PATH=/srv/nori/.venv/bin"
ExecStart=/srv/nori/.venv/bin/gunicorn asgi:app -c ../gunicorn.conf.py --bind 127.0.0.1:8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable nori
sudo systemctl start nori
sudo systemctl status nori
```

View logs:

```bash
sudo journalctl -u nori -f
```

### 3. Nginx reverse proxy

Create `/etc/nginx/sites-available/nori`:

```nginx
server {
    listen 80;
    server_name example.com;

    # Static files — served by Nginx directly, bypasses Python entirely
    location /static/ {
        alias /srv/nori/rootsystem/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Uploaded files (if serving from local storage)
    location /uploads/ {
        alias /srv/nori/rootsystem/application/uploads/;
        expires 7d;
    }

    # Application
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }

    # WebSocket support (if using WebSocket routes)
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
}
```

Enable and reload:

```bash
sudo ln -s /etc/nginx/sites-available/nori /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4. SSL with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d example.com
```

Certbot rewrites the Nginx config to add SSL and sets up auto-renewal. After this, make sure `TRUSTED_PROXIES=127.0.0.1` is set in `.env` so `get_client_ip()` trusts the `X-Forwarded-For` header from Nginx.

### 5. Apache (alternative)

If using Apache instead of Nginx, enable the required modules:

```bash
sudo a2enmod proxy proxy_http proxy_wstunnel headers
sudo systemctl restart apache2
```

Create `/etc/apache2/sites-available/nori.conf`:

```apache
<VirtualHost *:80>
    ServerName example.com

    Alias /static /srv/nori/rootsystem/static
    <Directory /srv/nori/rootsystem/static>
        Require all granted
    </Directory>

    ProxyPreserveHost On
    ProxyPass /static !
    ProxyPass /ws/ ws://127.0.0.1:8000/ws/
    ProxyPassReverse /ws/ ws://127.0.0.1:8000/ws/
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    RequestHeader set X-Forwarded-Proto "https"
</VirtualHost>
```

```bash
sudo a2ensite nori
sudo systemctl reload apache2
```

---

## Docker

The project includes a multi-stage `Dockerfile` and a `docker-compose.yml` for containerized deployments.

### docker-compose (app + MySQL)

```bash
# Set your .env first
cp .env.example rootsystem/application/.env
# Edit .env: set DB_HOST=db, DEBUG=false, secrets, etc.

docker compose up -d --build
```

The compose file starts two services:
- **app** — Gunicorn with Uvicorn workers on port 8000
- **db** — MySQL 8.0 with a health check and a persistent volume

To add Redis for cache and rate limiting, extend `docker-compose.yml`:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

Then set in `.env`:

```env
CACHE_BACKEND=redis
THROTTLE_BACKEND=redis
REDIS_URL=redis://redis:6379
```

### Custom Dockerfile

The included Dockerfile uses a two-stage build to keep the image small:

1. **Builder** — installs Python dependencies (including C extensions for asyncmy)
2. **Runtime** — copies only the installed packages and application code

The final image runs Gunicorn with the included `gunicorn.conf.py`.

---

## Database migrations

Run migrations before the first deploy and after every model change:

```bash
# First time only — initialize Aerich
python3 nori.py migrate:init

# Create and apply a migration
python3 nori.py migrate:make initial
python3 nori.py migrate:upgrade
```

In Docker:

```bash
docker compose exec app python3 /app/nori.py migrate:upgrade
```

---

## Health check

Nori exposes `GET /health` which returns:

```json
{"status": "healthy", "db": "connected"}
```

Or on database failure:

```json
{"status": "degraded", "db": "error: ..."}
```

Use this endpoint for:
- Load balancer health checks
- Docker `healthcheck` directives
- Uptime monitoring (Uptime Robot, Pingdom, etc.)

---

## Logging in production

Set these in `.env` for production logging:

```env
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=/var/log/nori/app.log
```

- **JSON format** outputs structured logs suitable for ELK, CloudWatch, Datadog, or any log aggregator.
- **File handler** rotates automatically at 10 MB with 5 backups.
- Each log entry includes the `request_id` when available, enabling distributed tracing.

Framework loggers: `nori.asgi`, `nori.audit`, `nori.tasks`, `nori.ws`, `nori.csrf`, `nori.throttle`, `nori.mail`, `nori.upload`, `nori.auth`.

---

## Redis in production

When running multiple Gunicorn workers (the default), **memory backends are isolated per worker**. This means:

- Rate limiting counters are not shared — a client gets N requests per worker, not N total
- Cache entries are duplicated across workers — wasted memory
- Login guard lockouts only apply to the worker that recorded the failures

Set `CACHE_BACKEND=redis` and `THROTTLE_BACKEND=redis` to share state across all workers. Redis is lightweight — a $5 instance or a single container is enough.

---

## Sizing guide

| Monthly visits | Avg req/s | Peak req/s | Server | Workers | Redis needed? |
|---------------|-----------|------------|--------|---------|---------------|
| 100k | ~2 | ~7 | 1 core, 2 GB | 1-2 | Optional |
| 500k | ~12 | ~35 | 2 cores, 4 GB | 3-5 | Recommended |
| 1M | ~23 | ~70 | 2 cores, 4 GB | 3-5 | Yes |
| 5M | ~115 | ~350 | 4 cores, 8 GB | 5-9 | Yes |

These assume a typical mix of cached and dynamic pages. With `@cache_response` on static-ish pages, most read traffic resolves from Redis in <1ms and never reaches your controllers.

For sites above 5M visits/month, consider horizontal scaling (multiple servers behind a load balancer) and a persistent job queue for background work.

---

## Documentation site

Nori includes a [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) configuration for generating a documentation website from the `docs/` directory.

### Build and deploy

```bash
# Install (one-time)
pip install mkdocs-material

# Build the static site
mkdocs build --strict

# Deploy to your server
rsync -avz --delete site/ yourserver:/srv/websites/nori-docs/
```

### Local preview

```bash
mkdocs serve
# Open http://localhost:8000
```

### Apache configuration

```apache
<VirtualHost *:80>
    ServerName nori.yourdomain.com
    DocumentRoot /srv/websites/nori-docs

    <Directory /srv/websites/nori-docs>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
```

Add SSL with Certbot: `sudo certbot --apache -d nori.yourdomain.com`

### GitLab CI (automatic)

The project includes `.gitlab-ci.yml` that builds and publishes the docs to GitLab Pages on every push to `main` that changes `docs/` or `mkdocs.yml`.
