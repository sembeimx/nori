"""Tests for services.oauth_github — GitHub OAuth2 driver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from core.auth.oauth import _PKCE_SESSION_KEY, _STATE_SESSION_KEY

# -- Fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _github_settings(monkeypatch):
    """Set required GitHub OAuth settings."""
    import settings

    monkeypatch.setattr(settings, 'GITHUB_CLIENT_ID', 'gh-test-id')
    monkeypatch.setattr(settings, 'GITHUB_CLIENT_SECRET', 'gh-test-secret')


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the module-level httpx client between tests."""
    import services.oauth_github as gh_mod

    gh_mod._client = None
    yield
    gh_mod._client = None


def _make_session() -> dict:
    return {}


# -- get_auth_url ------------------------------------------------------------


def test_get_auth_url_contains_required_params():
    from services.oauth_github import get_auth_url

    session = _make_session()
    url = get_auth_url(session, redirect_uri='https://example.com/callback')

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert 'github.com' in parsed.netloc
    assert params['client_id'] == ['gh-test-id']
    assert params['redirect_uri'] == ['https://example.com/callback']
    assert 'read:user' in params['scope'][0]
    assert 'user:email' in params['scope'][0]
    assert 'state' in params


def test_get_auth_url_no_pkce():
    """GitHub does not support PKCE — URL must not include code_challenge."""
    from services.oauth_github import get_auth_url

    session = _make_session()
    url = get_auth_url(session, redirect_uri='https://example.com/cb')

    params = parse_qs(urlparse(url).query)
    assert 'code_challenge' not in params
    assert 'code_challenge_method' not in params
    assert _PKCE_SESSION_KEY not in session


def test_get_auth_url_custom_scopes():
    from services.oauth_github import get_auth_url

    session = _make_session()
    url = get_auth_url(session, redirect_uri='https://example.com/cb', scopes='repo')

    params = parse_qs(urlparse(url).query)
    assert params['scope'] == ['repo']


def test_get_auth_url_stores_state():
    from services.oauth_github import get_auth_url

    session = _make_session()
    get_auth_url(session, redirect_uri='https://example.com/cb')
    assert _STATE_SESSION_KEY in session


# -- handle_callback ---------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_callback_invalid_state():
    from services.oauth_github import handle_callback

    session = _make_session()
    session[_STATE_SESSION_KEY] = 'expected-state'

    with pytest.raises(ValueError, match='Invalid OAuth state'):
        await handle_callback(session, code='abc', redirect_uri='https://x.com/cb', state='wrong')


@pytest.mark.asyncio
async def test_handle_callback_exchanges_code():
    from core.auth.oauth import generate_state
    from services.oauth_github import _TOKEN_URL, handle_callback

    session = _make_session()
    state = generate_state(session)

    token_response = MagicMock()
    token_response.json.return_value = {'access_token': 'gh-token-123'}
    token_response.raise_for_status = MagicMock()

    user_response = MagicMock()
    user_response.json.return_value = {
        'id': 42,
        'login': 'octocat',
        'name': 'Octocat',
        'email': 'octocat@github.com',
        'avatar_url': 'https://avatars.githubusercontent.com/u/42',
    }
    user_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = token_response
    mock_client.get.return_value = user_response

    with patch('services.oauth_github._get_client', return_value=mock_client):
        profile = await handle_callback(
            session,
            code='gh-code',
            redirect_uri='https://example.com/cb',
            state=state,
        )

    # Verify token request used Accept: application/json
    post_call = mock_client.post.call_args
    assert post_call[0][0] == _TOKEN_URL
    assert post_call[1]['headers']['Accept'] == 'application/json'
    assert post_call[1]['data']['code'] == 'gh-code'

    assert profile['id'] == '42'
    assert profile['login'] == 'octocat'
    assert profile['email'] == 'octocat@github.com'


# -- get_user_profile --------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_profile_uses_public_email():
    """When /user returns a non-null email, use it directly."""
    from services.oauth_github import get_user_profile

    user_response = MagicMock()
    user_response.json.return_value = {
        'id': 1,
        'login': 'alice',
        'name': 'Alice',
        'email': 'alice@example.com',
        'avatar_url': 'https://avatars.githubusercontent.com/u/1',
    }
    user_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = user_response

    with patch('services.oauth_github._get_client', return_value=mock_client):
        profile = await get_user_profile('token')

    assert profile['email'] == 'alice@example.com'
    # Should NOT have fetched /user/emails since email was present
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_get_user_profile_fetches_private_email():
    """When /user returns null email, fetch from /user/emails."""
    from services.oauth_github import _EMAILS_URL, _USER_URL, get_user_profile

    user_response = MagicMock()
    user_response.json.return_value = {
        'id': 2,
        'login': 'bob',
        'name': 'Bob',
        'email': None,
        'avatar_url': 'https://avatars.githubusercontent.com/u/2',
    }
    user_response.raise_for_status = MagicMock()

    emails_response = MagicMock()
    emails_response.json.return_value = [
        {'email': 'bob-noreply@users.noreply.github.com', 'primary': False, 'verified': True},
        {'email': 'bob@real.com', 'primary': True, 'verified': True},
        {'email': 'old@example.com', 'primary': False, 'verified': False},
    ]
    emails_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.side_effect = [user_response, emails_response]

    with patch('services.oauth_github._get_client', return_value=mock_client):
        profile = await get_user_profile('token')

    assert profile['email'] == 'bob@real.com'
    assert profile['id'] == '2'
    assert profile['name'] == 'Bob'

    # Verify both endpoints were called
    calls = [c[0][0] for c in mock_client.get.call_args_list]
    assert _USER_URL in calls
    assert _EMAILS_URL in calls


@pytest.mark.asyncio
async def test_get_user_profile_no_primary_verified_email_leaves_email_blank():
    """When neither /user nor /user/emails yield a primary+verified address,
    `email` stays empty rather than picking an unverified or non-primary one."""
    from services.oauth_github import get_user_profile

    user_response = MagicMock()
    user_response.json.return_value = {
        'id': 7,
        'login': 'noemail',
        'name': 'No Email',
        'email': None,
        'avatar_url': '',
    }
    user_response.raise_for_status = MagicMock()

    emails_response = MagicMock()
    emails_response.json.return_value = [
        {'email': 'unverified-primary@x.com', 'primary': True, 'verified': False},
        {'email': 'verified-secondary@x.com', 'primary': False, 'verified': True},
    ]
    emails_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.side_effect = [user_response, emails_response]

    with patch('services.oauth_github._get_client', return_value=mock_client):
        profile = await get_user_profile('token')

    assert profile['email'] == ''
    assert profile['id'] == '7'
    assert profile['login'] == 'noemail'


@pytest.mark.asyncio
async def test_get_user_profile_normalized_dict():
    from services.oauth_github import get_user_profile

    raw = {
        'id': 99,
        'login': 'charlie',
        'name': 'Charlie',
        'email': 'charlie@test.com',
        'avatar_url': 'https://example.com/avatar.jpg',
        'bio': 'Developer',
    }

    user_response = MagicMock()
    user_response.json.return_value = raw
    user_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = user_response

    with patch('services.oauth_github._get_client', return_value=mock_client):
        profile = await get_user_profile('token')

    assert profile['id'] == '99'
    assert profile['email'] == 'charlie@test.com'
    assert profile['name'] == 'Charlie'
    assert profile['avatar_url'] == 'https://example.com/avatar.jpg'
    assert profile['login'] == 'charlie'
    assert profile['raw'] == raw
