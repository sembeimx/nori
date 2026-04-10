# Testing

Nori provides testing utilities in `core.testing` to help you write tests for your application. These complement `pytest` and `pytest-asyncio` — install them via `pip install -r requirements-dev.txt`.

Testing should not be an afterthought. If you don't test it, you don't know if it works. `core.testing` removes the boilerplate so you can focus on what matters: verifying your logic.

---

## Setup

Create a `tests/conftest.py` in your project root:

```python
import os
import sys

# Force test database before any app import
os.environ['DB_ENGINE'] = 'sqlite'
os.environ['DB_NAME'] = ':memory:'

# Add application to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../rootsystem/application'))

import pytest_asyncio
from core.testing import create_test_client, setup_test_db, teardown_test_db


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def db():
    await setup_test_db()
    yield
    await teardown_test_db()


@pytest_asyncio.fixture
async def client():
    async with create_test_client() as c:
        yield c
```

And a `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

---

## Test Client

The `create_test_client()` context manager wraps `httpx.AsyncClient` with the ASGI app pre-wired:

```python
async def test_health_endpoint(client):
    resp = await client.get('/health')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'ok'


async def test_create_article(client):
    resp = await client.post('/articles', data={
        'title': 'Test Article',
        'body': 'Content here',
    })
    assert resp.status_code == 302  # Redirect after creation
```

---

## Authentication Helpers

### Session Auth

Use `authenticate()` to set a signed session cookie on the test client. This works with `@login_required`, `@require_role`, `@require_any_role`, and `@require_permission`:

```python
from core.testing import authenticate, clear_authentication

async def test_dashboard_requires_login(client):
    resp = await client.get('/dashboard')
    assert resp.status_code == 302  # Redirect to /login

    authenticate(client, user_id='42', role='admin')
    resp = await client.get('/dashboard')
    assert resp.status_code == 200

    # Remove authentication
    clear_authentication(client)
```

With permissions:

```python
authenticate(client, user_id='1', role='editor', permissions=['articles.edit'])
```

The function creates a real Starlette session cookie signed with `SECRET_KEY`. No mocking required — your auth decorators receive a fully populated `request.session`.

### JWT Auth

Use `authenticate_api()` for API endpoints protected by `@token_required`:

```python
from core.testing import authenticate_api

async def test_api_profile(client):
    authenticate_api(client, payload={'user_id': 1, 'role': 'admin'})
    resp = await client.get('/api/profile')
    assert resp.status_code == 200
```

Or with a pre-generated token:

```python
from core.auth.jwt import create_token

token = create_token({'user_id': 1}, expires_in=3600)
authenticate_api(client, token=token)
```

---

## Model Factories

`ModelFactory` provides a base class for generating test data with sensible defaults:

```python
from core.testing import ModelFactory
from models.article import Article
from models.user import User


class ArticleFactory(ModelFactory):
    model = Article

    @classmethod
    def defaults(cls) -> dict:
        n = cls.next_id()
        return {
            'title': f'Article {n}',
            'body': f'Body for article {n}',
            'status': 'draft',
        }


class UserFactory(ModelFactory):
    model = User

    @classmethod
    def defaults(cls) -> dict:
        n = cls.next_id()
        return {
            'username': f'user{n}',
            'email': f'user{n}@test.com',
            'password_hash': 'hashed_for_testing',
        }
```

### Usage in tests

```python
async def test_article_creation():
    # Create with defaults
    article = await ArticleFactory.create()
    assert article.title == 'Article 1'

    # Override specific fields
    article = await ArticleFactory.create(title='Custom', status='published')
    assert article.title == 'Custom'

    # Create multiple
    articles = await ArticleFactory.create_batch(5)
    assert len(articles) == 5

    # Build without persisting (for request payloads)
    data = ArticleFactory.build(title='Draft')
    assert data['title'] == 'Draft'
    assert 'body' in data  # defaults are included
```

### Counter management

Each factory has an auto-incrementing counter via `next_id()`. Reset between tests if needed:

```python
@pytest.fixture(autouse=True)
def reset_factories():
    ModelFactory.reset_all()
    yield
```

---

## Assertion Helpers

### `assert_redirects(response, path)`

```python
from core.testing import assert_redirects

async def test_logout_redirects(client):
    resp = await client.post('/logout')
    assert_redirects(resp, '/login')
    assert_redirects(resp, '/login', status_code=302)
```

### `assert_json_error(response, status_code, message)`

```python
from core.testing import assert_json_error

async def test_unauthorized_api(client):
    resp = await client.get('/api/profile')
    assert_json_error(resp, 401, 'Unauthorized')

async def test_validation_error(client):
    resp = await client.post('/api/articles', json={})
    assert_json_error(resp, 422)  # Just check status, any error message
```

---

## Database Helpers

### `setup_test_db(extra_models=)`

Initializes Tortoise with an in-memory SQLite database and generates schemas. If you have test-only models, pass them as `extra_models`:

```python
await setup_test_db(extra_models=['tests.test_models'])
```

### `teardown_test_db()`

Closes all Tortoise connections. Call in the teardown phase of your session fixture.

### Cleaning up between tests

For tests that modify the database, use a cleanup fixture:

```python
@pytest.fixture(autouse=True)
async def clean_articles():
    yield
    await Article.all().delete()
```

---

## Full Example

```python
# tests/test_articles.py
from core.testing import authenticate, assert_redirects, assert_json_error


class TestArticleController:

    async def test_index_returns_articles(self, client):
        await ArticleFactory.create_batch(3)
        resp = await client.get('/articles')
        assert resp.status_code == 200

    async def test_store_requires_auth(self, client):
        resp = await client.post('/articles', data={'title': 'Test'})
        assert_redirects(resp, '/login')

    async def test_store_validates_input(self, client):
        authenticate(client, user_id='1')
        resp = await client.post('/articles', data={'title': ''})
        assert resp.status_code == 200  # Re-renders form with errors

    async def test_store_creates_article(self, client):
        authenticate(client, user_id='1')
        resp = await client.post('/articles', data={
            'title': 'My Article',
            'body': 'Content',
        })
        assert_redirects(resp, '/articles')
```
