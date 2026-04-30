# Services and Core Utilities

Nori abstracts common backend operations into clean, native modules with a consistent **multi-driver** pattern. Each module ships with sensible defaults (local disk, SMTP) and can be extended with custom drivers in `services/` — no modifications to the core required.

Why drivers? Because your production stack is different from your dev machine. Local disk in development, S3 in production. SMTP locally, Resend in the cloud. The interface stays the same — only the backend changes.

---

## Architecture: The Driver Pattern

Three core modules — **Storage**, **Email**, and **Search** — follow the same extensibility pattern:

1. **Core dispatcher** (`core/`) defines the public API and a driver registry.
2. **Built-in drivers** cover the most common use case (local disk, SMTP).
3. **Custom drivers** live in `services/` as application-level plug-ins.
4. **Configuration** via `.env` selects the active driver; per-call overrides are always available.

```
.env                    → STORAGE_DRIVER=s3
services/storage_s3.py  → register()   # called at app startup
core/http/upload.py     → save_upload(file)  # dispatches to s3 driver
```

### Creating a Custom Driver

The process is the same for all three modules:

1. Write an async function (or dict of functions for search) matching the driver contract.
2. Wrap it in a `register()` function that calls `register_*_driver()`.
3. Call `register()` at app startup (e.g. in `routes.py` or `asgi.py` lifespan).
4. Set the env var (`STORAGE_DRIVER`, `MAIL_DRIVER`, `SEARCH_DRIVER`) or pass `driver=` per-call.

Each driver contract is documented below. The core never imports or knows about your custom drivers — registration is explicit and happens at runtime.

### Driver Configuration Access

Custom drivers should access settings via `core.conf.config` to stay consistent with the framework's decoupled architecture:

```python
from core.conf import config

async def my_handler(...):
    api_key = config.get('MY_SERVICE_API_KEY')
    ...
```

---

## File Uploads & Storage (`core.http.upload`)

Centralized file upload with strict validation and pluggable storage backends.

### Validation Layers

Every upload passes through three security checks before being stored:

1. **Extension** — only extensions listed in `allowed_types` are accepted.
2. **MIME type** — the client-declared `Content-Type` header must match the expected MIME for the extension.
3. **Magic bytes** — the **actual file content** is inspected for known file signatures (JPEG `\xff\xd8\xff`, PNG `\x89PNG\r\n\x1a\n`, GIF `GIF87a`/`GIF89a`, PDF `%PDF`, WebP `RIFF`). This prevents an attacker from uploading a disguised file (e.g. an executable renamed to `.jpg` with a spoofed `Content-Type`).

Magic byte verification is implemented in pure Python — no `python-magic` or `libmagic` dependency. Extensions without known signatures (e.g. SVG, CSV) skip this check gracefully; the extension and MIME checks still apply.

### Configuration (.env)

```text
# Storage driver: local (default) | (register custom drivers in your app)
STORAGE_DRIVER=local
UPLOAD_DIR=/path/to/uploads     # only used by the local driver
UPLOAD_MAX_SIZE=10485760        # 10 MB default
```

### Basic Usage

```python
from core.http.upload import save_upload, UploadError

async def update_avatar(self, request):
    form = await request.form()
    uploaded_file = form.get('avatar_file')

    try:
        result = await save_upload(
            uploaded_file,
            allowed_types=['jpg', 'png', 'jpeg'],
            max_size=2 * 1024 * 1024,  # 2 MB
        )
    except UploadError as e:
        return JSONResponse({'error': str(e)}, status_code=422)

    # result.filename     → UUID-based name (e.g. 'a1b2c3.jpg')
    # result.path         → absolute path (local) or object key (cloud)
    # result.url          → public URL
    # result.size         → file size in bytes
    # result.original_name → original client filename
```

### Per-Call Driver Override

```python
# Upload to S3 for this specific call, regardless of STORAGE_DRIVER
result = await save_upload(file, allowed_types=['jpg'], driver='s3')
```

### Driver Contract

A storage driver is an async function with this signature:

```python
async def handler(filename: str, source, upload_dir: str) -> tuple[str, str]:
    """
    Store the file and return (path_or_key, public_url).

    Args:
        filename: Generated UUID filename (e.g. 'a1b2c3d4.jpg').
        source:   File-like object positioned at byte 0 (a
                  ``tempfile.SpooledTemporaryFile`` produced by
                  ``save_upload``). Stream from it via
                  ``shutil.copyfileobj`` or a chunked iterator —
                  do NOT call ``source.read()`` unbounded, the
                  payload may be a multi-GB file already on disk.
                  The handler MUST NOT close ``source``; its
                  lifetime is owned by ``save_upload``.
        upload_dir: Target directory or key prefix.

    Returns:
        Tuple of (storage_path, public_url).
    """
```

!!! warning "Driver protocol changed in 1.23"
    Pre-1.23 drivers received ``content: bytes`` instead of a
    streaming ``source``. The change bounds framework RAM use to
    ~8 MB per upload regardless of file size. If you have a custom
    driver, the simplest mechanical migration is
    ``content = source.read()`` at the top of the handler — but
    for large uploads switch to a streaming copy.

Register it at app startup:

```python
from core.http.upload import register_storage_driver

register_storage_driver('my_cdn', my_cdn_handler)
```

### Introspection

```python
from core.http.upload import get_storage_drivers

print(get_storage_drivers())  # e.g. {'local', 's3'}
```

---

## Email (`core.mail`)

Multi-driver email dispatcher with built-in SMTP and log drivers.

### Configuration (.env)

```text
# Mail driver: smtp (default) | log | (register custom drivers)
MAIL_DRIVER=smtp

# SMTP settings (used by the smtp driver)
MAIL_HOST=smtp.mailgun.org
MAIL_PORT=587
MAIL_USER=postmaster@your-domain.com
MAIL_PASSWORD=secret
MAIL_FROM=Nori Notifications <hello@your-domain.com>
MAIL_TLS=true
```

For development, set `MAIL_DRIVER=log` to log emails without sending them.

### Basic Usage (HTML Body)

```python
from core.mail import send_mail

await send_mail(
    to='client@example.com',
    subject='Welcome to our platform',
    body_html='<p>Thank you for registering!</p>',
    body_text='Thank you for registering!',  # optional plain text fallback
)
```

### Jinja2 Template Emails

```python
await send_mail(
    to='ceo@myapp.com',
    subject='New sale registered',
    template='mails/sale.html',
    context={'name': 'Acme Corp', 'amount': 150000.50},
)
```

Templates are resolved from `rootsystem/templates/` automatically.

### Per-Call Driver Override

```python
# Log this email instead of sending it, regardless of MAIL_DRIVER
await send_mail(to='...', subject='...', body_html='...', driver='log')
```

### Driver Contract

A mail driver is an async function with this signature:

```python
async def handler(to: list[str], subject: str, body_html: str, body_text: str | None) -> None:
    """
    Send the email.

    Args:
        to:        List of recipient email addresses.
        subject:   Email subject line.
        body_html: HTML body (already rendered from template if applicable).
        body_text: Optional plain-text fallback (may be None).
    """
```

Register it at app startup:

```python
from core.mail import register_mail_driver

register_mail_driver('resend', my_resend_handler)
```

### Introspection

```python
from core.mail import get_mail_drivers

print(get_mail_drivers())  # e.g. {'smtp', 'log', 'resend'}
```

---

## Search (`core.search`)

Multi-driver full-text search dispatcher. The core ships with **no built-in driver** — search is an external concern. For simple queries, use Tortoise ORM directly (e.g. `Article.filter(title__icontains=query)`).

### Configuration (.env)

```text
# Search driver: empty by default (opt-in)
SEARCH_DRIVER=meilisearch

# Meilisearch settings (used by the meilisearch driver)
MEILISEARCH_URL=http://localhost:7700
MEILISEARCH_API_KEY=your-master-key
```

### Setup

Register a driver at app startup (e.g. in `routes.py`):

```python
from services.search_meilisearch import register
register()
```

### Searching

```python
from core.search import search

results = await search(
    'articles',                          # index name
    'async python',                      # query string
    filters={'status': 'published'},     # optional filters
    limit=10,                            # default: 20
    offset=0,                            # default: 0
)

for hit in results:
    print(hit['title'], hit['id'])
```

### Indexing Documents

Indexing is **explicit** — you call it from your controller. No automatic model hooks.

```python
from core.search import index_document

# After creating or updating a record
article = await Article.create(title='Hello', body='World')
await index_document('articles', article.id, article.to_dict())
```

For non-blocking indexing, combine with `background()`:

```python
from core.tasks import background
from core.search import index_document

task = background(index_document, 'articles', article.id, article.to_dict())
return JSONResponse({'id': article.id}, background=task)
```

### Removing Documents

```python
from core.search import remove_document

await article.delete()
await remove_document('articles', article.id)
```

### Driver Contract

A search driver is a dict with three async callables:

```python
driver = {
    'search': search_fn,
    'index_document': index_fn,
    'remove_document': remove_fn,
}
```

Each callable must match these signatures:

```python
async def search_fn(index: str, query: str, filters: dict, limit: int, offset: int) -> list[dict]:
    """Execute a search query. Returns a list of hit dicts."""

async def index_fn(index: str, doc_id: str | int, document: dict) -> None:
    """Add or update a document in the index."""

async def remove_fn(index: str, doc_id: str | int) -> None:
    """Remove a document from the index."""
```

Register it at app startup:

```python
from core.search import register_search_driver

register_search_driver('typesense', {
    'search': my_search_fn,
    'index_document': my_index_fn,
    'remove_document': my_remove_fn,
})
```

### Meilisearch Filters

The Meilisearch driver converts filter dicts automatically:

```python
# Simple key-value filters → 'status = "published" AND lang = "en"'
results = await search('articles', 'query', filters={'status': 'published', 'lang': 'en'})

# Advanced filters with _raw → passed as-is to Meilisearch
results = await search('articles', 'query', filters={
    '_raw': 'status = "published" AND (lang = "en" OR lang = "es")'
})
```

### Introspection

```python
from core.search import get_search_drivers

print(get_search_drivers())  # e.g. {'meilisearch'}
```

---

## Audit Logging (`core.audit`)

Native audit logging that records who did what and when, running as a non-blocking background task.

### Basic Usage

```python
from core.audit import audit

class ArticleController:
    async def create(self, request):
        article = await Article.create(title='New Post', body='...')

        audit(request, 'create', model_name='Article', record_id=article.id)
        return JSONResponse({'ok': True})
```

`audit()` is **fire-and-forget** — it schedules the database write immediately via `asyncio`. There is no need to capture the return value or attach it to a response. If the write fails, the error is logged to `nori.audit` but never raised.

### Tracking Changes

For update operations, pass a `changes` dictionary with before/after values:

```python
audit(
    request, 'update',
    model_name='Article',
    record_id=article.id,
    changes={
        'title': {'before': 'Old Title', 'after': 'New Title'},
        'status': {'before': 'draft', 'after': 'published'},
    },
)
```

### What Gets Captured Automatically

- **user_id**: Resolved from `request.session['user_id']` (can be overridden with the `user_id=` parameter). Cast to `int` before storing.
- **ip_address**: Extracted via `get_client_ip(request)`, which respects `X-Forwarded-For` only from trusted proxies (see [Security — Trusted Proxies](security.md#trusted-proxies-ip-spoofing-protection))
- **request_id**: From `request.state.request_id` (set by `RequestIdMiddleware`)
- **Structured log**: Every audit call also emits a log line via `nori.audit` logger

### Helper: get_client_ip

```python
from core.audit import get_client_ip

ip = get_client_ip(request)  # Respects X-Forwarded-For from TRUSTED_PROXIES only
```

`get_client_ip()` only reads `X-Forwarded-For` when the direct connection IP is in `TRUSTED_PROXIES` (configured in `.env`). This prevents IP spoofing by untrusted clients.

---

## Available Example Drivers (`services/`)

| File | Driver | For | Requires |
|------|--------|-----|----------|
| `services/mail_resend.py` | `resend` | Email via Resend API | `RESEND_API_KEY`, `MAIL_FROM` |
| `services/storage_s3.py` | `s3` | S3/R2/Spaces/MinIO | `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| `services/storage_gcs.py` | `gcs` | Google Cloud Storage | `GCS_BUCKET`, `GCS_CREDENTIALS_FILE` (or `GCS_CREDENTIALS_JSON`), plus the `cryptography` package |
| `services/search_meilisearch.py` | `meilisearch` | Meilisearch full-text search | `MEILISEARCH_URL` |

### How to use an example driver

All three follow the same two-step pattern:

**Step 1 — Register at startup** (e.g. in `routes.py`):

```python
from services.storage_s3 import register as register_s3
from services.mail_resend import register as register_resend
from services.search_meilisearch import register as register_meilisearch

register_s3()
register_resend()
register_meilisearch()
```

**Step 2 — Set the env var** in `.env`:

```text
STORAGE_DRIVER=s3
MAIL_DRIVER=resend
SEARCH_DRIVER=meilisearch
```

That's it. The core dispatchers will route calls to your registered drivers. You can also override per-call with `driver='s3'` without changing the env var.

### S3 Driver — Additional Configuration

```text
S3_BUCKET=my-bucket
S3_REGION=us-east-1
S3_ACCESS_KEY=AKIA...
S3_SECRET_KEY=wJal...
S3_ENDPOINT=https://s3.us-east-1.amazonaws.com    # optional, for R2/Spaces/MinIO
S3_URL_PREFIX=https://cdn.example.com              # optional, custom public URL prefix
```

The S3 driver implements AWS Signature V4 in pure Python (no `boto3` dependency). It works with any S3-compatible API: AWS S3, Cloudflare R2, DigitalOcean Spaces, MinIO.

### GCS Driver — Additional Configuration

```text
GCS_BUCKET=my-bucket
GCS_CREDENTIALS_FILE=/path/to/service-account.json
# or, for containerised deployments where secrets are env-injected:
# GCS_CREDENTIALS_JSON={"type":"service_account",...}
GCS_URL_PREFIX=https://cdn.example.com    # optional, defaults to https://storage.googleapis.com/{bucket}
```

The GCS driver authenticates natively via **service account JWT → OAuth2 access token** (no `google-cloud-storage` SDK). It:

1. Loads the service account JSON from `GCS_CREDENTIALS_FILE` (preferred) or `GCS_CREDENTIALS_JSON`.
2. Signs a short-lived JWT with RS256 using the service account's private key.
3. Exchanges the JWT for a 1-hour Bearer access token at `https://oauth2.googleapis.com/token`.
4. Caches the token in-process and refreshes 60 s before expiry (async-safe).
5. Uploads via `PUT https://storage.googleapis.com/{bucket}/{key}`.

**Setup on GCP:**

1. Create a bucket in a GCP project with the Cloud Storage API enabled.
2. Create a service account and grant it **Storage Object Admin** on the bucket.
3. Generate a JSON key for the service account — this is the file you point `GCS_CREDENTIALS_FILE` at.

**Requires the `cryptography` package** for RS256 JWT signing. It is listed as optional in `requirements.txt`; install it when you enable the GCS driver:

```bash
pip install cryptography
```

**Public URLs:** the returned URL assumes the bucket (or object) is publicly readable. Configure bucket-level public access via IAM (`allUsers` → *Storage Object Viewer*) or set a `GCS_URL_PREFIX` pointing at a CDN that handles auth.

### Resend Driver — Additional Configuration

```text
RESEND_API_KEY=re_...
MAIL_FROM=Nori <hello@your-domain.com>
```

### Meilisearch Driver — Additional Configuration

```text
MEILISEARCH_URL=http://localhost:7700
MEILISEARCH_API_KEY=your-master-key    # optional in development
```

Install Meilisearch locally with Docker:

```bash
docker run -d -p 7700:7700 getmeili/meilisearch:latest
```

### Writing Your Own Driver

Copy any example driver as a starting point. The pattern is always:

```python
# services/mail_my_provider.py

from core.conf import config
from core.mail import register_mail_driver

async def _send(to, subject, body_html, body_text):
    api_key = config.MY_PROVIDER_API_KEY
    # Your implementation here
    ...

def register():
    register_mail_driver('my_provider', _send)
```

The core never knows your driver exists — it only sees the registered function at runtime. This keeps Nori's core dependency-free while letting you integrate with any external service.
