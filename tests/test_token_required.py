"""Tests for @token_required decorator."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from starlette.responses import JSONResponse
from core.auth.jwt import create_token
from core.auth.decorators import token_required


class FakeState:
    pass


class FakeHeaders:
    def __init__(self, auth=''):
        self._auth = auth

    def get(self, key, default=''):
        if key.lower() == 'authorization':
            return self._auth
        return default


class FakeRequest:
    def __init__(self, auth_header=''):
        self.headers = FakeHeaders(auth_header)
        self.state = FakeState()


class FakeController:
    @token_required
    async def protected(self, request):
        return JSONResponse({'ok': True, 'user': request.state.token_payload.get('user_id')})


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_no_token_returns_401():
    """Missing Authorization header returns 401."""
    ctrl = FakeController()
    req = FakeRequest(auth_header='')
    resp = _run(ctrl.protected(req))
    assert resp.status_code == 401


def test_invalid_token_returns_401():
    """Invalid JWT returns 401."""
    ctrl = FakeController()
    req = FakeRequest(auth_header='Bearer invalid.token.here')
    resp = _run(ctrl.protected(req))
    assert resp.status_code == 401


def test_valid_token_passes():
    """Valid JWT allows access and stores payload."""
    ctrl = FakeController()
    token = create_token({'user_id': 7}, expires_in=3600)
    req = FakeRequest(auth_header=f'Bearer {token}')
    resp = _run(ctrl.protected(req))
    assert resp.status_code == 200
    assert req.state.token_payload['user_id'] == 7


def test_expired_token_returns_401():
    """Expired JWT returns 401."""
    ctrl = FakeController()
    token = create_token({'user_id': 1}, expires_in=-1)
    req = FakeRequest(auth_header=f'Bearer {token}')
    resp = _run(ctrl.protected(req))
    assert resp.status_code == 401
