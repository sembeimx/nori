"""
Testing utilities for Nori applications.

Provides helpers that simplify writing tests for apps built on Nori.
These are meant for **app developers** — the framework's own test suite
lives in ``tests/``.

Quick start in your ``conftest.py``::

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
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise

__all__ = [
    'create_test_client',
    'setup_test_db',
    'teardown_test_db',
    'authenticate',
    'authenticate_api',
    'ModelFactory',
    'assert_redirects',
    'assert_json_error',
]


# ---------------------------------------------------------------------------
# Test client
# ---------------------------------------------------------------------------

@asynccontextmanager
async def create_test_client(app=None, base_url: str = 'http://test'):
    """Create an ``httpx.AsyncClient`` wired to the Nori ASGI app.

    Usage::

        async with create_test_client() as client:
            resp = await client.get('/health')
            assert resp.status_code == 200

    Args:
        app: ASGI application. Defaults to ``asgi.app``.
        base_url: Base URL for requests.
    """
    if app is None:
        from asgi import app as _app
        app = _app
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base_url) as client:
        yield client


# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------

async def setup_test_db(extra_models: list[str] | None = None) -> None:
    """Initialize Tortoise ORM with an in-memory SQLite database.

    Call this once per test session (``scope="session"``). Generates all
    schemas automatically.

    Args:
        extra_models: Additional model module paths to include
                      (e.g., ``['tests.test_models']``).
    """
    import settings

    model_modules = list(settings.TORTOISE_ORM.get('apps', {}).get('models', {}).get('models', ['models']))
    if extra_models:
        model_modules.extend(extra_models)

    config = {
        'connections': {'default': 'sqlite://:memory:'},
        'apps': {
            'framework': {
                'models': ['models.framework'],
                'default_connection': 'default',
            },
            'models': {
                'models': model_modules,
                'default_connection': 'default',
            },
        },
    }
    await Tortoise.init(config=config)
    await Tortoise.generate_schemas()


async def teardown_test_db() -> None:
    """Close Tortoise connections. Call in the teardown of your session fixture."""
    await Tortoise.close_connections()


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------

def authenticate(
    client: AsyncClient,
    user_id: str | int = '1',
    role: str = 'user',
    permissions: list[str] | None = None,
    secret_key: str | None = None,
) -> None:
    """Set session-based authentication on a test client.

    Creates a signed session cookie that Starlette's ``SessionMiddleware``
    will accept, populating ``request.session`` with the given identity.
    This works with ``@login_required``, ``@require_role``, and
    ``@require_permission`` decorators.

    Usage::

        authenticate(client, user_id='42', role='admin')
        resp = await client.get('/dashboard')
        assert resp.status_code == 200

    Args:
        client: The ``httpx.AsyncClient`` from ``create_test_client``.
        user_id: User ID to store in ``session['user_id']``.
        role: Role string for ``session['role']``.
        permissions: Optional list of permission strings.
        secret_key: Secret key for signing the cookie. Defaults to
                    ``settings.SECRET_KEY``.
    """
    session_data: dict[str, Any] = {
        'user_id': str(user_id),
        'role': role,
    }
    if permissions:
        session_data['permissions'] = permissions

    _set_session_cookie(client, session_data, secret_key)


def clear_authentication(client: AsyncClient) -> None:
    """Remove session authentication from a test client."""
    client.cookies.delete('session')


def _set_session_cookie(
    client: AsyncClient,
    session_data: dict,
    secret_key: str | None = None,
) -> None:
    """Sign and set a Starlette session cookie on the client.

    Replicates Starlette's SessionMiddleware cookie format:
    ``json.dumps → base64 → itsdangerous.TimestampSigner.sign()``.
    """
    import json
    from base64 import b64encode

    import itsdangerous

    if secret_key is None:
        from core.conf import config
        secret_key = config.SECRET_KEY

    payload = b64encode(json.dumps(session_data).encode('utf-8'))
    signer = itsdangerous.TimestampSigner(str(secret_key))
    signed = signer.sign(payload).decode('utf-8')
    client.cookies.set('session', signed)


def authenticate_api(
    client: AsyncClient,
    token: str | None = None,
    payload: dict | None = None,
) -> None:
    """Set JWT authentication on a test client.

    Either provide an existing ``token`` string or a ``payload`` dict
    (a token will be generated automatically).

    Usage::

        authenticate_api(client, payload={'user_id': 1})
        resp = await client.get('/api/profile')

    Args:
        client: The ``httpx.AsyncClient``.
        token: A pre-generated JWT string.
        payload: Dict to encode as JWT (generates a token).
    """
    if token is None and payload is not None:
        from core.auth.jwt import create_token
        token = create_token(payload, expires_in=3600)
    if token:
        client.headers['Authorization'] = f'Bearer {token}'


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------

class ModelFactory:
    """Base class for test data factories.

    Subclass and define ``model`` and ``defaults()``::

        from core.testing import ModelFactory
        from models.article import Article

        class ArticleFactory(ModelFactory):
            model = Article

            @classmethod
            def defaults(cls) -> dict:
                n = cls.next_id()
                return {
                    'title': f'Article {n}',
                    'body': f'Body for article {n}',
                }

    Then in tests::

        article = await ArticleFactory.create(title='Custom')
        articles = await ArticleFactory.create_batch(5)
    """

    model = None
    _counters: dict[str, int] = {}

    @classmethod
    def next_id(cls) -> int:
        """Return an auto-incrementing counter for this factory."""
        key = cls.__name__
        cls._counters[key] = cls._counters.get(key, 0) + 1
        return cls._counters[key]

    @classmethod
    def defaults(cls) -> dict:
        """Override to return default field values."""
        return {}

    @classmethod
    async def create(cls, **overrides: Any) -> Any:
        """Create and persist a model instance.

        Args:
            **overrides: Field values that override the defaults.

        Returns:
            The created model instance.
        """
        if cls.model is None:
            raise ValueError(f'{cls.__name__}.model is not set')
        data = {**cls.defaults(), **overrides}
        return await cls.model.create(**data)

    @classmethod
    async def create_batch(cls, count: int, **overrides: Any) -> list[Any]:
        """Create multiple model instances.

        Args:
            count: Number of instances to create.
            **overrides: Shared field overrides for all instances.

        Returns:
            List of created model instances.
        """
        return [await cls.create(**overrides) for _ in range(count)]

    @classmethod
    def build(cls, **overrides: Any) -> dict:
        """Return a dict of field values without persisting.

        Useful for testing validation or building request payloads.
        """
        return {**cls.defaults(), **overrides}

    @classmethod
    def reset(cls) -> None:
        """Reset the counter for this factory."""
        cls._counters.pop(cls.__name__, None)

    @classmethod
    def reset_all(cls) -> None:
        """Reset all factory counters."""
        cls._counters.clear()


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_redirects(response, expected_path: str, status_code: int = 302) -> None:
    """Assert that a response is a redirect to the expected path.

    Args:
        response: The ``httpx.Response``.
        expected_path: The path (or full URL) expected in the ``Location`` header.
        status_code: Expected HTTP status (default: 302).
    """
    assert response.status_code == status_code, (
        f'Expected {status_code}, got {response.status_code}'
    )
    location = response.headers.get('location', '')
    assert expected_path in location, (
        f'Expected redirect to {expected_path!r}, got {location!r}'
    )


def assert_json_error(response, status_code: int, message: str | None = None) -> None:
    """Assert a JSON error response.

    Args:
        response: The ``httpx.Response``.
        status_code: Expected HTTP status code.
        message: Optional substring to check in the ``error`` field.
    """
    assert response.status_code == status_code, (
        f'Expected {status_code}, got {response.status_code}'
    )
    body = response.json()
    assert 'error' in body, f'Response body has no "error" key: {body}'
    if message:
        assert message in body['error'], (
            f'Expected {message!r} in error, got {body["error"]!r}'
        )
