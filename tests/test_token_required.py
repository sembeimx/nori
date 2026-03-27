"""Tests for @token_required decorator."""
import pytest

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


@pytest.mark.asyncio
async def test_no_token_returns_401():
    """Missing Authorization header returns 401."""
    ctrl = FakeController()
    req = FakeRequest(auth_header='')
    resp = await ctrl.protected(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401():
    """Invalid JWT returns 401."""
    ctrl = FakeController()
    req = FakeRequest(auth_header='Bearer invalid.token.here')
    resp = await ctrl.protected(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_passes():
    """Valid JWT allows access and stores payload."""
    ctrl = FakeController()
    token = create_token({'user_id': 7}, expires_in=3600)
    req = FakeRequest(auth_header=f'Bearer {token}')
    resp = await ctrl.protected(req)
    assert resp.status_code == 200
    assert req.state.token_payload['user_id'] == 7


@pytest.mark.asyncio
async def test_expired_token_returns_401():
    """Expired JWT returns 401."""
    ctrl = FakeController()
    token = create_token({'user_id': 1}, expires_in=-30)
    req = FakeRequest(auth_header=f'Bearer {token}')
    resp = await ctrl.protected(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bearer_with_extra_spaces():
    """Bearer token with extra whitespace is handled correctly."""
    ctrl = FakeController()
    token = create_token({'user_id': 7}, expires_in=3600)
    req = FakeRequest(auth_header=f'  Bearer   {token}  ')
    resp = await ctrl.protected(req)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bearer_case_insensitive():
    """'BEARER' (uppercase) is accepted."""
    ctrl = FakeController()
    token = create_token({'user_id': 7}, expires_in=3600)
    req = FakeRequest(auth_header=f'BEARER {token}')
    resp = await ctrl.protected(req)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_oversized_token_rejected():
    """Token exceeding 4096 characters is rejected."""
    ctrl = FakeController()
    req = FakeRequest(auth_header='Bearer ' + 'x' * 5000)
    resp = await ctrl.protected(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bearer_only_no_token():
    """'Bearer ' with no actual token is rejected."""
    ctrl = FakeController()
    req = FakeRequest(auth_header='Bearer ')
    resp = await ctrl.protected(req)
    assert resp.status_code == 401
