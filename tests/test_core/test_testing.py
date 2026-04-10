"""Tests for core.testing utilities."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.testing import (
    ModelFactory,
    assert_json_error,
    assert_redirects,
    authenticate,
    authenticate_api,
    clear_authentication,
    _set_session_cookie,
)


# ---------------------------------------------------------------------------
# ModelFactory
# ---------------------------------------------------------------------------

class DummyModel:
    """Fake model that mimics Tortoise create()."""
    _store: list = []

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    @classmethod
    async def create(cls, **kwargs):
        instance = cls(**kwargs)
        cls._store.append(instance)
        return instance


class DummyFactory(ModelFactory):
    model = DummyModel

    @classmethod
    def defaults(cls) -> dict:
        n = cls.next_id()
        return {'name': f'Item {n}', 'active': True}


@pytest.fixture(autouse=True)
def _reset():
    ModelFactory.reset_all()
    DummyModel._store.clear()
    yield


@pytest.mark.asyncio
async def test_factory_create_with_defaults():
    item = await DummyFactory.create()
    assert item.name == 'Item 1'
    assert item.active is True


@pytest.mark.asyncio
async def test_factory_create_with_overrides():
    item = await DummyFactory.create(name='Custom', active=False)
    assert item.name == 'Custom'
    assert item.active is False


@pytest.mark.asyncio
async def test_factory_create_increments_counter():
    a = await DummyFactory.create()
    b = await DummyFactory.create()
    assert a.name == 'Item 1'
    assert b.name == 'Item 2'


@pytest.mark.asyncio
async def test_factory_create_batch():
    items = await DummyFactory.create_batch(3)
    assert len(items) == 3
    assert items[0].name == 'Item 1'
    assert items[2].name == 'Item 3'


def test_factory_build_returns_dict():
    data = DummyFactory.build()
    assert isinstance(data, dict)
    assert data['name'] == 'Item 1'
    assert data['active'] is True


def test_factory_build_with_overrides():
    data = DummyFactory.build(name='Override')
    assert data['name'] == 'Override'
    assert data['active'] is True  # Default kept


def test_factory_reset():
    DummyFactory.next_id()
    DummyFactory.next_id()
    DummyFactory.reset()
    assert DummyFactory.next_id() == 1


def test_factory_reset_all():
    DummyFactory.next_id()
    ModelFactory.reset_all()
    assert DummyFactory.next_id() == 1


@pytest.mark.asyncio
async def test_factory_no_model_raises():
    class EmptyFactory(ModelFactory):
        pass

    with pytest.raises(ValueError, match='model is not set'):
        await EmptyFactory.create()


# ---------------------------------------------------------------------------
# assert_redirects
# ---------------------------------------------------------------------------

def test_assert_redirects_success():
    resp = MagicMock()
    resp.status_code = 302
    resp.headers = {'location': '/dashboard'}
    assert_redirects(resp, '/dashboard')


def test_assert_redirects_wrong_status():
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {'location': '/dashboard'}
    with pytest.raises(AssertionError, match='Expected 302'):
        assert_redirects(resp, '/dashboard')


def test_assert_redirects_wrong_path():
    resp = MagicMock()
    resp.status_code = 302
    resp.headers = {'location': '/login'}
    with pytest.raises(AssertionError, match='/dashboard'):
        assert_redirects(resp, '/dashboard')


def test_assert_redirects_custom_status():
    resp = MagicMock()
    resp.status_code = 301
    resp.headers = {'location': '/new-url'}
    assert_redirects(resp, '/new-url', status_code=301)


# ---------------------------------------------------------------------------
# assert_json_error
# ---------------------------------------------------------------------------

def test_assert_json_error_success():
    resp = MagicMock()
    resp.status_code = 401
    resp.json.return_value = {'error': 'Unauthorized'}
    assert_json_error(resp, 401, 'Unauthorized')


def test_assert_json_error_wrong_status():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {'error': 'Oops'}
    with pytest.raises(AssertionError, match='Expected 401'):
        assert_json_error(resp, 401)


def test_assert_json_error_no_error_key():
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = {'message': 'Bad'}
    with pytest.raises(AssertionError, match='no "error" key'):
        assert_json_error(resp, 400)


def test_assert_json_error_message_mismatch():
    resp = MagicMock()
    resp.status_code = 403
    resp.json.return_value = {'error': 'Forbidden'}
    with pytest.raises(AssertionError, match='Unauthorized'):
        assert_json_error(resp, 403, 'Unauthorized')


def test_assert_json_error_no_message_check():
    resp = MagicMock()
    resp.status_code = 422
    resp.json.return_value = {'error': 'Validation failed'}
    assert_json_error(resp, 422)  # No message check — should pass


# ---------------------------------------------------------------------------
# authenticate helpers
# ---------------------------------------------------------------------------

def test_authenticate_sets_session_cookie():
    """authenticate() creates a signed session cookie with user data."""
    from httpx import AsyncClient
    client = AsyncClient()
    authenticate(client, user_id='42', role='admin', secret_key='test-secret')
    cookie = client.cookies.get('session')
    assert cookie is not None
    # Verify the cookie can be decoded
    import json
    from base64 import b64decode
    import itsdangerous
    signer = itsdangerous.TimestampSigner('test-secret')
    unsigned = signer.unsign(cookie.encode())
    data = json.loads(b64decode(unsigned))
    assert data['user_id'] == '42'
    assert data['role'] == 'admin'


def test_authenticate_with_permissions():
    from httpx import AsyncClient
    client = AsyncClient()
    authenticate(client, user_id='1', role='editor',
                 permissions=['articles.edit', 'articles.delete'],
                 secret_key='test-secret')
    cookie = client.cookies.get('session')
    import json
    from base64 import b64decode
    import itsdangerous
    signer = itsdangerous.TimestampSigner('test-secret')
    data = json.loads(b64decode(signer.unsign(cookie.encode())))
    assert data['permissions'] == ['articles.edit', 'articles.delete']


def test_clear_authentication():
    from httpx import AsyncClient
    client = AsyncClient()
    authenticate(client, user_id='1', secret_key='test-secret')
    assert client.cookies.get('session') is not None
    clear_authentication(client)
    assert client.cookies.get('session') is None


def test_authenticate_api_with_payload():
    client = MagicMock()
    client.headers = {}
    authenticate_api(client, payload={'user_id': 1})
    assert 'Authorization' in client.headers
    assert client.headers['Authorization'].startswith('Bearer ')


def test_authenticate_api_with_token():
    client = MagicMock()
    client.headers = {}
    authenticate_api(client, token='my.jwt.token')
    assert client.headers['Authorization'] == 'Bearer my.jwt.token'


def test_authenticate_api_no_args():
    client = MagicMock()
    client.headers = {}
    authenticate_api(client)
    assert 'Authorization' not in client.headers


# ---------------------------------------------------------------------------
# Integration: authenticate() with real decorators
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authenticate_works_with_login_required():
    """authenticate() creates a real session that @login_required accepts."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.sessions import SessionMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from core.auth.decorators import login_required
    from core.testing import create_test_client, authenticate

    class Ctrl:
        @login_required
        async def protected(self, request: Request):
            return JSONResponse({'user_id': request.session.get('user_id')})

    ctrl = Ctrl()
    test_app = Starlette(
        routes=[Route('/protected', ctrl.protected, methods=['GET'])],
        middleware=[Middleware(SessionMiddleware, secret_key='integration-test')],
    )

    async with create_test_client(app=test_app) as client:
        # Without auth — should get 401
        resp = await client.get('/protected', headers={'accept': 'application/json'})
        assert resp.status_code == 401

        # With auth — should pass
        authenticate(client, user_id='42', role='admin', secret_key='integration-test')
        resp = await client.get('/protected', headers={'accept': 'application/json'})
        assert resp.status_code == 200
        assert resp.json()['user_id'] == '42'


@pytest.mark.asyncio
async def test_authenticate_works_with_require_role():
    """authenticate() sets the role correctly for @require_role."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.sessions import SessionMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from core.auth.decorators import require_role
    from core.testing import create_test_client, authenticate

    class Ctrl:
        @require_role('admin')
        async def admin_only(self, request: Request):
            return JSONResponse({'ok': True})

    ctrl = Ctrl()
    test_app = Starlette(
        routes=[Route('/admin', ctrl.admin_only, methods=['GET'])],
        middleware=[Middleware(SessionMiddleware, secret_key='role-test')],
    )

    async with create_test_client(app=test_app) as client:
        # Wrong role — should get 403
        authenticate(client, user_id='1', role='user', secret_key='role-test')
        resp = await client.get('/admin', headers={'accept': 'application/json'})
        assert resp.status_code == 403

        # Correct role — should pass
        authenticate(client, user_id='1', role='admin', secret_key='role-test')
        resp = await client.get('/admin', headers={'accept': 'application/json'})
        assert resp.status_code == 200
