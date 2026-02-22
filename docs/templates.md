# Templates and Frontend (Jinja2)

Nori uses the industry-standard **Jinja2** template system. Each route can respond by rendering an HTML file with variable contextual dictionaries served from the controller.

The base hierarchy resides in the general framework folder `/rootsystem/templates/`.

## Inheritance and Blocks 

Like Blade (Laravel) or Twig (Symfony), Jinja2 files recommend operating on `base.html` inheritance and iterating child variables `{% extends %}`.

**`base.html` (Base Layout)**:
Builds the portal wrapper, with titled *placeholders* called `{% block %}`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <title>{% block title %}Nori App{% endblock %}</title>
    <!-- Your Custom CSS Injections here -->
    {% block head %}{% endblock %} 
</head>
<body>
    <nav>...</nav>

    <main>
        <!-- Your Child Content is rendered here -->
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

**Child / HTML View (`home.html`)**:
Starts by injecting the `extends` directive on line one and saturates its own context overrides at will:

```html
{% extends "base.html" %}

{% block title %}Main Dashboard{% endblock %}

{% block content %}
    <h1>Client List</h1>
    <!-- More HTML... -->
{% endblock %}
```

## Variables, Loops, and Conditionals

Jinja2 provides minimal logic for rendering dynamic variables transferred by your controller, using double braces `{{ variable }}` and enclosed blocks for if/for `{% instruction %}`.

### If / Else
```html
{% if request.session.get('user_id') %}
    <p>Welcome Administrator!</p>
{% else %}
    <a href="/login">Log In</a>
{% endif %}
```

*(Important: You might notice that the global Starlette Request variable always travels pre-injected by Nori. It is not necessary to re-export it from the controller and can be used immediately, e.g. `request.url.path` or `request.session`).*

### For Loops (Collection Cycles or Querysets)
```html
<ul>
    {% for user in total_users %}
        <li><a href="/user/{{ user.id }}">{{ user.name }}</a></li>
    {% else %}
        <li>The list is empty — no registered users.</li>
    {% endfor %}
</ul>
```

### URLs and Dynamic Links
Calling `url_for` on the Request component.

```html
<a href="{{ request.url_for('edit_client', client_id=123) }}">Click to Edit</a>
```

## Native Static Files (StaticFiles)

Any css, javascript file, svg logo, or mp4 multimedia that does not need compilation should be copied purely into `rootsystem/static/`.

```
rootsystem/
    static/
        css/style.css
        js/app.js
        images/logo_nori.png
```

Nori exposes the static tag positionally without unnecessary abstract routes:
```html
<!-- In base.html, inside <head> -->
<link rel="stylesheet" href="/static/css/style.css">

<!-- Image Rendering -->
<img src="/static/images/logo_nori.png" alt="Startup Logo">
```

## Custom Error Pages

By switching Nori's `.env` configuration to `DEBUG=false` on a Production server, your site will hide Interactive Exception Tracebacks, instantly throwing and compiling the templates from the Root Templates folder (`404.html` for a "Not Found" or fake URLs, and `500.html` protecting unexpected database crashes from hackers).

Their implementation does not differ from a normal base-extended HTML in order to keep the look of your native application intact and neat while protecting its crash state (Hiding it from the end user and rendering your own intact emergency dashboard).
