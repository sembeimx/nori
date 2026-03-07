# Services and Core Utilities

Nori abstracts the most common backend operations that usually require third-party libraries (sending emails, upload management) into clean, secure, and native methods ready to use in your Controllers.

## Static File Uploading (Uploads)

Forget about parsing multipart byte streams manually. The pre-built `save_upload` directive centralizes strict validations and asynchronous disk writes. It maintains strict default configurations to avoid harmful file uploads (XSS/PHP Shells or Executables).

### Base Implementation

In a POST flow formatted as an HTML form `<form enctype="multipart/form-data">`, use `await request.form()` thus obtaining the `UploadFile` instance.

```python
from core.http.upload import save_upload, UploadError

async def update_avatar(self, request):
    form = await request.form()
    uploaded_file = form.get('avatar_file')  # UploadFile object

    if not uploaded_file.filename:
         return Error("File required")

    try:
        result = await save_upload(
            uploaded_file,
            allowed_types=['jpg', 'png', 'jpeg'],  # Validates strict MIME types + extension
            max_size=2048576,                       # Max capacity: 2 MB
            upload_dir='/path/to/uploads/avatars',  # Destination directory
        )
    except UploadError as e:
        return Error(str(e))

    # Saved successfully. result is an UploadResult object.
    print("Saved at:", result.path)           # Absolute path on disk
    print("Filename:", result.filename)       # UUID-based filename (e.g. 'a1b2c3.jpg')
    print("Original:", result.original_name)  # Original filename
    print("Size:", result.size)               # File size in bytes
```

### Global Configuration (.env)
You can set maximum upload caps for the entire server by overwriting the configuration with `UPLOAD_MAX_SIZE` and altering the base path with `UPLOAD_DIR`.

---

## Email Dispatch (SMTP)

Usually, it would require heavy blocking synchronous libraries. Nori provides a native email utility (`send_mail`) backed by a fully asynchronous `aiosmtplib` dispatcher to keep your main thread intact.

Furthermore, it supports direct rendering of Jinja2 (HTML) templates behind the scenes!

### .env Configuration (Required)

```text
MAIL_HOST=smtp.mailgun.org
MAIL_PORT=587
MAIL_USER=postmaster@your-domain.com
MAIL_PASSWORD=secret
MAIL_FROM=Nori Notifications <hello@your-domain.com>
MAIL_TLS=true
```

### Basic Use (HTML body)

Ideal for quick logs, password recoveries via API, or crash notices to the administrator.
```python
from core.mail import send_mail

async def post(self, request):
    # General logic ...

    # Non-Blocking Dispatch
    await send_mail(
        to='client_1@gmail.com',
        subject='Welcome to our platform',
        body_html='<p>Thank you for registering on the App!</p>',
        body_text='Thank you for registering on the App!',  # optional plain text fallback
    )
```

### Advanced HTML / Jinja2 Styled Mails

Nori will connect to your framework directories automatically; this way a Designer can code the look of the mail based on visual tables in a classic template `/rootsystem/templates/mails/welcome.html` and you in the backend simply dictate pure Python variables.

```python
async def notify_payment(self, request):

    await send_mail(
        to='ceo@myapp.com',
        subject='New sale registered',
        template='mails/sale_html.html',   # Relative template path
        context={
            'name': 'Acme Corp',
            'amount': 150000.50
        }
    )
```

> **Note**: `send_mail()` is a void async function. It raises an exception on failure rather than returning a result.

---

## Audit Logging

Nori includes a native audit logging system that records who did what and when, running as a non-blocking background task.

### Basic Usage

```python
from core.audit import audit

class ArticleController:
    async def create(self, request):
        article = await Article.create(title='New Post', body='...')

        task = audit(
            request, 'create',
            model_name='Article',
            record_id=article.id,
        )
        return JSONResponse({'ok': True}, background=task)
```

The `audit()` function returns a `BackgroundTask` (via `core.tasks.background()`). Pass it to any Starlette response's `background=` parameter — the log entry is written to the database after the response is sent.

### Tracking Changes

For update operations, pass a `changes` dictionary with before/after values:

```python
task = audit(
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

- **user_id**: Resolved from `request.session['user_id']` (can be overridden with the `user_id=` parameter)
- **ip_address**: Extracted via `get_client_ip(request)`, which respects `X-Forwarded-For` behind reverse proxies
- **request_id**: From `request.state.request_id` (set by `RequestIdMiddleware`)
- **Structured log**: Every audit call also emits a log line via `nori.audit` logger

### Helper: get_client_ip

```python
from core.audit import get_client_ip

ip = get_client_ip(request)  # Respects X-Forwarded-For
```
