"""Tests for services.oauth_google — Google OAuth2/OpenID Connect driver."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from core.auth.oauth import _PKCE_SESSION_KEY, _STATE_SESSION_KEY

# -- Fixtures ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def _google_settings(monkeypatch):
    """Set required Google OAuth settings."""
    import settings
    monkeypatch.setattr(settings, 'GOOGLE_CLIENT_ID', 'test-client-id')
    monkeypatch.setattr(settings, 'GOOGLE_CLIENT_SECRET', 'test-client-secret')


def _make_session() -> dict:
    return {}


# -- get_auth_url ------------------------------------------------------------

def test_get_auth_url_contains_required_params():
    from services.oauth_google import get_auth_url

    session = _make_session()
    url = get_auth_url(session, redirect_uri='https://example.com/callback')

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == 'https'
    assert 'accounts.google.com' in parsed.netloc
    assert params['client_id'] == ['test-client-id']
    assert params['redirect_uri'] == ['https://example.com/callback']
    assert params['response_type'] == ['code']
    assert 'openid' in params['scope'][0]
    assert 'email' in params['scope'][0]
    assert params['code_challenge_method'] == ['S256']
    assert 'code_challenge' in params
    assert 'state' in params


def test_get_auth_url_custom_scopes():
    from services.oauth_google import get_auth_url

    session = _make_session()
    url = get_auth_url(session, redirect_uri='https://example.com/cb', scopes='openid email')

    params = parse_qs(urlparse(url).query)
    assert params['scope'] == ['openid email']


def test_get_auth_url_stores_state_and_pkce():
    from services.oauth_google import get_auth_url

    session = _make_session()
    get_auth_url(session, redirect_uri='https://example.com/cb')

    assert _STATE_SESSION_KEY in session
    assert _PKCE_SESSION_KEY in session


# -- handle_callback ---------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_callback_invalid_state():
    from services.oauth_google import handle_callback

    session = _make_session()
    session[_STATE_SESSION_KEY] = 'expected-state'

    with pytest.raises(ValueError, match='Invalid OAuth state'):
        await handle_callback(session, code='abc', redirect_uri='https://x.com/cb', state='wrong')


@pytest.mark.asyncio
async def test_handle_callback_exchanges_code():
    from core.auth.oauth import generate_pkce_verifier, generate_state
    from services.oauth_google import _TOKEN_URL, handle_callback

    session = _make_session()
    state = generate_state(session)
    _verifier, _challenge = generate_pkce_verifier(session)

    token_response = MagicMock()
    token_response.json.return_value = {'access_token': 'google-token-123'}
    token_response.raise_for_status = MagicMock()

    userinfo_response = MagicMock()
    userinfo_response.json.return_value = {
        'sub': '12345',
        'email': 'alice@gmail.com',
        'name': 'Alice',
        'picture': 'https://photo.url/alice.jpg',
        'email_verified': True,
    }
    userinfo_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = token_response
    mock_client.get.return_value = userinfo_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.oauth_google.httpx.AsyncClient', return_value=mock_client):
        profile = await handle_callback(
            session, code='auth-code-xyz',
            redirect_uri='https://example.com/cb', state=state,
        )

    # Verify token exchange was called correctly
    post_call = mock_client.post.call_args
    assert post_call[0][0] == _TOKEN_URL
    post_data = post_call[1]['data']
    assert post_data['code'] == 'auth-code-xyz'
    assert post_data['client_id'] == 'test-client-id'
    assert post_data['client_secret'] == 'test-client-secret'
    assert post_data['grant_type'] == 'authorization_code'
    assert post_data['code_verifier'] is not None

    # Verify profile
    assert profile['id'] == '12345'
    assert profile['email'] == 'alice@gmail.com'
    assert profile['name'] == 'Alice'
    assert profile['email_verified'] is True
    assert profile['raw']['sub'] == '12345'


# -- get_user_profile --------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_profile_returns_normalized_dict():
    from services.oauth_google import get_user_profile

    userinfo_response = MagicMock()
    userinfo_response.json.return_value = {
        'sub': '99',
        'email': 'bob@gmail.com',
        'name': 'Bob',
        'picture': 'https://photo.url/bob.jpg',
        'email_verified': True,
    }
    userinfo_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = userinfo_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch('services.oauth_google.httpx.AsyncClient', return_value=mock_client):
        profile = await get_user_profile('some-token')

    assert profile == {
        'id': '99',
        'email': 'bob@gmail.com',
        'name': 'Bob',
        'picture': 'https://photo.url/bob.jpg',
        'email_verified': True,
        'raw': userinfo_response.json.return_value,
    }

    # Verify Authorization header was sent
    get_call = mock_client.get.call_args
    assert get_call[1]['headers']['Authorization'] == 'Bearer some-token'
