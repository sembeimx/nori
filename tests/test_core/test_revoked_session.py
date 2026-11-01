"""Revoked cookies must stop looking authenticated on the login page."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.auth import decorators, session_guard
from core.conf import config
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route


@pytest.mark.parametrize('gate', ['login_required', 'require_role', 'require_any_role', 'require_permission'])
@pytest.mark.parametrize('accept', ['text/html', 'application/json'])
@pytest.mark.asyncio
async def test_revoked_session_is_cleared_before_login(monkeypatch: pytest.MonkeyPatch, gate: str, accept: str) -> None:
    monkeypatch.setattr(config, '_settings', SimpleNamespace(SESSION_VERSION_CHECK=True, LOGIN_URL='/sign-in'))
    session_guard._reset_circuit()

    async def live_version(key: str) -> int:
        return 2

    monkeypatch.setattr(session_guard, 'cache_get', live_version)
    monkeypatch.setattr(session_guard, 'audit', lambda *args, **kwargs: None)
    decorate = {
        'login_required': decorators.login_required,
        'require_role': decorators.require_role('editor'),
        'require_any_role': decorators.require_any_role('editor', 'admin'),
        'require_permission': decorators.require_permission('articles.edit'),
    }[gate]

    class Controller:
        @decorate
        async def dashboard(self, request: Request) -> Response:
            return JSONResponse({'private': True})

    async def seed(request: Request) -> Response:
        request.session.update(user_id=1, session_version=1, role='editor', permissions=['articles.edit'])
        return Response()

    async def sign_in(request: Request) -> Response:
        if request.session.get('user_id'):
            return RedirectResponse('/dashboard', status_code=302)
        return JSONResponse({'session': dict(request.session)})

    app = Starlette(
        routes=[
            Route('/seed', seed, methods=['POST']),
            Route('/dashboard', Controller().dashboard),
            Route('/sign-in', sign_in),
        ],
        middleware=[Middleware(SessionMiddleware, secret_key='test-only-session-key')],
    )
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        await client.post('/seed')
        rejected = await client.get('/dashboard', headers={'accept': accept})
        assert rejected.status_code == (401 if accept == 'application/json' else 302)
        if accept == 'application/json':
            assert rejected.json() == {'error': 'Session revoked'}
        else:
            assert rejected.headers['location'] == '/sign-in'
        login = await client.get('/sign-in')
        assert login.status_code == 200
        assert login.json() == {'session': {}}
