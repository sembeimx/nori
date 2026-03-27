# Background Tasks

Nori wraps Starlette's `BackgroundTask` with automatic error logging, so a failing background task never crashes the response — errors are logged and the user is unaffected.

---

## Creating a Task

```python
from core.tasks import background

# Create a background task
task = background(send_welcome_email, user.email, user.name)

# Pass it to a response — the task runs after the response is sent
return JSONResponse({'ok': True}, background=task)
```

`background(func, *args, **kwargs)` accepts both sync and async callables.

---

## Attaching to an Existing Response

If you already have a response object and want to add a background task to it:

```python
from core.tasks import run_in_background

response = JSONResponse({'ok': True})
run_in_background(response, send_welcome_email, user.email)
return response
```

---

## Multiple Tasks

To run multiple background tasks on a single response:

```python
from core.tasks import background_tasks

tasks = background_tasks(
    (send_welcome_email, user.email),
    (index_document, 'users', user.id, user.to_dict()),
    (audit_login, request, user.id),
)
return JSONResponse({'ok': True}, background=tasks)
```

Each tuple is `(func, *args)`. Tasks execute sequentially in order.

---

## Error Handling

If a background callable raises an exception:

- The error is **logged** with full traceback via `nori.tasks` logger.
- The exception is **not re-raised** — the HTTP response has already been sent.
- Other tasks in the chain continue to execute.

This makes background tasks safe for non-critical operations like email sending, indexing, and audit logging.

---

## Common Patterns

### Audit logging

```python
from core.audit import audit

task = audit(request, 'create', model_name='Article', record_id=article.id)
return JSONResponse({'id': article.id}, background=task)
```

### Search indexing

```python
from core.tasks import background
from core.search import index_document

task = background(index_document, 'articles', article.id, article.to_dict())
return JSONResponse({'id': article.id}, background=task)
```

### Email after registration

```python
from core.tasks import background
from core.mail import send_mail

task = background(send_mail, to=user.email, subject='Welcome', template='mails/welcome.html', context={'name': user.name})
return RedirectResponse(url='/dashboard', status_code=302, background=task)
```

---

## Limitations

Background tasks run **in-process** — if the server restarts or crashes, pending tasks are lost. For reliable async work that must survive restarts (bulk emails, PDF generation, image processing), a persistent job queue is needed. See the [Roadmap](roadmap.md) for the planned queue system.
