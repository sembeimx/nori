# Flash Messages

Flash messages are one-time notifications stored in the session. They survive a single redirect and are automatically cleared after being read — ideal for showing "Record saved" or "Login failed" banners after a POST-redirect-GET cycle.

---

## Setting a Flash Message

```python
from core.http.flash import flash

class ArticleController:

    async def store(self, request):
        # ... save article ...
        flash(request, 'Article created successfully!')
        return RedirectResponse(url='/articles', status_code=302)

    async def delete(self, request):
        # ... delete article ...
        flash(request, 'Article deleted.', category='warning')
        return RedirectResponse(url='/articles', status_code=302)
```

`flash(request, message, category='success')` stores the message in `request.session`. The `category` parameter is a free-form string you can use for styling (e.g. `success`, `error`, `warning`, `info`).

---

## Reading Flash Messages in Templates

`get_flashed_messages` is registered as a Jinja2 global, so you can call it directly in any template:

```html
{% set messages = get_flashed_messages(request.session) %}
{% for msg in messages %}
    <div class="alert alert-{{ msg.category }}">
        {{ msg.message }}
    </div>
{% endfor %}
```

Each message is a dict with two keys:
- `message` — the text string
- `category` — the category string (default: `'success'`)

**Important**: `get_flashed_messages()` is a **one-time read**. Calling it clears all messages from the session. If you need to display them in multiple places on the same page, store the result in a Jinja2 variable first (as shown above with `{% set %}`).

---

## Common Pattern: Base Template

Place the flash message block in your `base.html` so all pages display notifications automatically:

```html
<!-- base.html -->
<body>
    {% set messages = get_flashed_messages(request.session) %}
    {% if messages %}
        <div class="flash-container">
            {% for msg in messages %}
                <div class="alert alert-{{ msg.category }}">{{ msg.message }}</div>
            {% endfor %}
        </div>
    {% endif %}

    {% block content %}{% endblock %}
</body>
```
