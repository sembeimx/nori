# Getting Started

Build a simple blog with Nori in 5 minutes. By the end you'll have a working app with a database, controller, templates, and routes.

---

## 1. Install

```bash
git clone https://github.com/sembeimx/nori.git my-blog
cd my-blog
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Configure the environment:

```bash
cp .env.example rootsystem/application/.env
```

Edit `rootsystem/application/.env`:

```env
DEBUG=true
SECRET_KEY=change-me-in-production
DB_ENGINE=sqlite
DB_NAME=db.sqlite3
```

Start the server to confirm everything works:

```bash
python3 nori.py serve
```

Visit `http://localhost:8000`. You should see the welcome page. Stop the server with `Ctrl+C`.

---

## 2. Create the Model

Generate the Article model:

```bash
python3 nori.py make:model Article
```

This creates `rootsystem/application/models/article.py`. Open it and replace the contents:

```python
from __future__ import annotations

from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin


class Article(NoriModelMixin, Model):
    id = fields.IntField(primary_key=True)
    title = fields.CharField(max_length=200)
    slug = fields.CharField(max_length=200, unique=True)
    content = fields.TextField()
    published_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'articles'
        ordering = ['-published_at']

    def __str__(self) -> str:
        return self.title
```

### Register the model

Open `rootsystem/application/models/__init__.py` and add the import and registration:

```python
from models.article import Article
from core.registry import register_model

register_model('Article', Article)
```

!!! note
    Every model must be imported here **and** registered with `register_model()`. The CLI reminds you of this when you run `make:model`.

---

## 3. Run Migrations

If this is the first time you run migrations in the project, initialize Aerich:

```bash
python3 nori.py migrate:init
```

This generates the framework + user migrations against your current DB engine and creates the initial tables. It only needs to be run once per project.

Then, every time you change a model:

```bash
python3 nori.py migrate:make create_articles
python3 nori.py migrate:upgrade
```

This creates the `articles` table in your database.

---

## 4. Create the Controller

```bash
python3 nori.py make:controller Article
```

This creates `rootsystem/application/modules/article.py`. Replace the contents:

```python
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.exceptions import HTTPException
from core.jinja import templates


class ArticleController:

    async def index(self, request: Request):
        """List all published articles."""
        from models.article import Article

        articles = await Article.filter(
            published_at__isnull=False
        ).order_by('-published_at')

        return templates.TemplateResponse(request, 'blog/index.html', {
            'articles': articles,
        })

    async def show(self, request: Request):
        """Show a single article by slug."""
        from models.article import Article

        slug = request.path_params['slug']
        article = await Article.filter(
            slug=slug, published_at__isnull=False
        ).first()

        if not article:
            raise HTTPException(status_code=404)

        return templates.TemplateResponse(request, 'blog/show.html', {
            'article': article,
        })
```

**What's happening here:**

- `index` queries all published articles ordered by date
- `show` looks up an article by its slug and returns 404 if not found
- Both methods return a Jinja2 template response

---

## 5. Define Routes

Open `rootsystem/application/routes.py` and add the blog routes:

```python
from starlette.routing import Route, Mount
from modules.article import ArticleController

article = ArticleController()

routes = [
    # ... existing routes ...
    Mount('/blog', routes=[
        Route('/', endpoint=article.index, methods=['GET'], name='blog.index'),
        Route('/{slug:path}', endpoint=article.show, methods=['GET'], name='blog.show'),
    ]),
]
```

!!! tip
    Every route needs an explicit `methods=` list and a unique `name` in dot-notation. The name lets you generate URLs with `request.url_for('blog.show', slug='my-article')`.

---

## 6. Create Templates

### Base layout

If you haven't modified the base layout yet, Nori ships with one at `rootsystem/templates/base.html`. Your blog templates will extend it.

### Blog list

Create `rootsystem/templates/blog/index.html`:

```html
{% extends "base.html" %}

{% block content %}
<h1>Blog</h1>

{% if articles %}
    {% for article in articles %}
    <article style="margin-bottom: 2rem; padding-bottom: 2rem; border-bottom: 1px solid #eee;">
        <h2>
            <a href="{{ request.url_for('blog.show', slug=article.slug) }}">
                {{ article.title }}
            </a>
        </h2>
        <time>{{ article.published_at.strftime('%B %d, %Y') }}</time>
        <p>{{ article.content[:200] }}...</p>
    </article>
    {% endfor %}
{% else %}
    <p>No articles published yet.</p>
{% endif %}
{% endblock %}
```

### Article detail

Create `rootsystem/templates/blog/show.html`:

```html
{% extends "base.html" %}

{% block content %}
<article>
    <h1>{{ article.title }}</h1>
    <time>{{ article.published_at.strftime('%B %d, %Y') }}</time>
    <div style="margin-top: 2rem;">
        {{ article.content|safe }}
    </div>
</article>

<p style="margin-top: 3rem;">
    <a href="{{ request.url_for('blog.index') }}">&larr; Back to blog</a>
</p>
{% endblock %}
```

---

## 7. Seed Some Data

Generate a seeder:

```bash
python3 nori.py make:seeder Article
```

Open `rootsystem/application/seeders/article_seeder.py` and replace it:

```python
"""Seeder for Article."""
from tortoise.timezone import now
from models.article import Article


async def run() -> None:
    """Create sample blog posts."""
    await Article.create(
        title='Hello World',
        slug='hello-world',
        content='<p>Welcome to my blog built with Nori. This is the first post.</p>',
        published_at=now(),
    )
    await Article.create(
        title='Getting Started with Nori',
        slug='getting-started-with-nori',
        content='<p>Nori is an async Python web framework that makes building web apps straightforward.</p>',
        published_at=now(),
    )
```

Register the seeder in `rootsystem/application/seeders/database_seeder.py`:

```python
from seeders.article_seeder import run as seed_articles


async def run() -> None:
    await seed_articles()
```

Run it:

```bash
python3 nori.py db:seed
```

---

## 8. See It Live

Start the server:

```bash
python3 nori.py serve
```

Visit:

- **Blog list:** `http://localhost:8000/blog`
- **Article detail:** `http://localhost:8000/blog/hello-world`

You now have a working blog with a database, controller, templates, routes, and seed data.

---

Notice how every feature follows the same cycle: model, migration, controller, route, template. This is the Nori workflow. Once you've done it once, every new feature feels familiar.

## What's Next?

Now that you understand the basic flow, explore the framework further:

- **[Validation](forms_validation.md)** — Add a contact form with `validate(form, {'email': 'required|email|url|date'})`
- **[Authentication](authentication.md)** — Protect routes with `@login_required`
- **[Database](database.md)** — Add relationships, soft deletes, and tree structures
- **[Services](services.md)** — Send emails, upload files, index for search
- **[Testing](testing.md)** — Write tests with `create_test_client()`, factories, and auth helpers
- **[CLI](cli.md)** — Add custom commands in `commands/` that survive framework updates
- **[Deployment](deployment.md)** — Ship to production with Gunicorn and Nginx
