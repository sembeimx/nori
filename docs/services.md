# Services and Core Utilities

Nori abstracts the most common backend operations that usually require third-party libraries (sending emails, upload management) into clean, secure, and native methods ready to use in your Controllers.

## Static File Uploading (Uploads)

Forget about parsing multipart byte streams manually. The pre-built `save_upload` directive centralizes strict validations and asynchronous disk writes. It maintains strict default configurations to avoid harmful file uploads (XSS/PHP Shells or Executables).

### Base Implementation

In a POST flow formatted as an HTML form `<form enctype="multipart/form-data">`, use `await request.form()` thus obtaining the `UploadFile` instance.

```python
from core.http.upload import save_upload

async def update_avatar(self, request):
    form = await request.form()
    uploaded_file = form.get('avatar_file') # Upload object
    
    if not uploaded_file.filename:
         return Error("File required")

    response = await save_upload(
        uploaded_file,                 
        destination='avatars',           # Will save in: /rootsystem/static/avatars/
        allowed=['jpg','png','jpeg'],    # Validates strict mime-types + extension
        max_size=2048576                 # Max Capacity: 2 MB
    )

    if not response['success']:
        # Failed size filter, or the ending / MiME-Type does not match.
        return Error(response['error']) 
        
    # Saved successfully. You get the public read absolute URL.
    print("Saved at:", response['filepath']) # E.g.: '/static/avatars/1A2bC.jpg'
```

### Global Configuration (.env)
You can passively delimit maximum upload caps for the entire server by overwriting the configuration with `UPLOAD_MAX_SIZE` and altering the base path with `UPLOAD_DIR`.

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

### Basic Use (Plain Text)

Ideal for quick logs, password recoveries via API, or crash notices to the administrator.
```python
from core.mail import send_mail

async def post(self, request):
    # General logic ...

    # Non-Blocking Dispatch
    await send_mail(
        to='client_1@gmail.com',
        subject='Welcome to our platform',
        body='Thank you for registering on the App!'
    )
```

### Advanced HTML / Jinja2 Styled Mails

Nori will connect to your framework directories automatically; this way a Designer can code the look of the mail based on visual tables in a classic template `/rootsystem/templates/mails/welcome.html` and you in the backend simply dictate pure Python variables.

```python
async def notify_payment(self, request):

    result = await send_mail(
        to='ceo@myapp.com',
        subject='💰 New sale registered',
        template='mails/sale_html.html',   # Relative visual path
        context={
            'name': 'Acme Corp',
            'amount': 150000.50
        }
    )

    if result:
        print("Sent successfully via Mailgun SMTP!")
    else:
        print("The TLS dispatcher failed, check logs")
```
