"""
GitHub OAuth2 driver for Nori.

Implements the Authorization Code flow (without PKCE — GitHub does not
support it).  Fetches the primary verified email separately since
GitHub's ``/user`` endpoint may return ``null`` for users with private
email settings.

Setup
-----

1. Create an OAuth App at https://github.com/settings/developers
2. Set the **Authorization callback URL** to your callback route
3. Add to ``.env``::

       GITHUB_CLIENT_ID=your-client-id
       GITHUB_CLIENT_SECRET=your-client-secret

Usage in a controller::

    from services.oauth_github import get_auth_url, handle_callback

    class SocialAuthController:
        async def github_login(self, request):
            url = get_auth_url(request.session,
                               redirect_uri=str(request.url_for('auth.github.callback')))
            return RedirectResponse(url)

        async def github_callback(self, request):
            profile = await handle_callback(
                request.session,
                code=request.query_params['code'],
                redirect_uri=str(request.url_for('auth.github.callback')),
                state=request.query_params.get('state', ''),
            )
            # profile = {id, email, name, avatar_url, login, raw}
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from core.auth.oauth import generate_state, validate_state
from core.conf import config

_AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
_TOKEN_URL = 'https://github.com/login/oauth/access_token'
_USER_URL = 'https://api.github.com/user'
_EMAILS_URL = 'https://api.github.com/user/emails'
_DEFAULT_SCOPES = 'read:user,user:email'


def get_auth_url(
    session: dict,
    redirect_uri: str,
    scopes: str | None = None,
) -> str:
    """Build the GitHub authorization URL with state parameter.

    Args:
        session: The Starlette session dict (``request.session``).
        redirect_uri: The callback URL registered with GitHub.
        scopes: Comma-separated scopes (default: ``'read:user,user:email'``).

    Returns:
        The full GitHub authorization URL to redirect the user to.
    """
    state = generate_state(session)

    params = {
        'client_id': config.GITHUB_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'scope': scopes or _DEFAULT_SCOPES,
        'state': state,
    }
    return f'{_AUTHORIZE_URL}?{urlencode(params)}'


async def handle_callback(
    session: dict,
    code: str,
    redirect_uri: str,
    state: str,
) -> dict:
    """Exchange the authorization code for a token and return the user profile.

    Validates the OAuth state parameter, exchanges the code for an access
    token, then fetches the user profile (including private email).

    Args:
        session: The Starlette session dict.
        code: The authorization code from GitHub's callback.
        redirect_uri: Must match the ``redirect_uri`` used in :func:`get_auth_url`.
        state: The state parameter from the callback query string.

    Returns:
        Dict with keys: ``id``, ``email``, ``name``, ``avatar_url``,
        ``login``, ``raw`` (full GitHub ``/user`` response).

    Raises:
        ValueError: If state validation fails.
        httpx.HTTPStatusError: If the token exchange or profile request fails.
    """
    if not validate_state(session, state):
        raise ValueError('Invalid OAuth state parameter')

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            _TOKEN_URL,
            data={
                'client_id': config.GITHUB_CLIENT_ID,
                'client_secret': config.GITHUB_CLIENT_SECRET,
                'code': code,
                'redirect_uri': redirect_uri,
            },
            headers={'Accept': 'application/json'},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()['access_token']

    return await get_user_profile(access_token)


async def get_user_profile(access_token: str) -> dict:
    """Fetch the GitHub user profile using an access token.

    Also fetches ``/user/emails`` to resolve the primary verified email,
    since GitHub's ``/user`` endpoint returns ``null`` for ``email`` when
    the user has email privacy enabled.

    Args:
        access_token: A valid GitHub OAuth2 access token.

    Returns:
        Dict with keys: ``id``, ``email``, ``name``, ``avatar_url``,
        ``login``, ``raw``.

    Raises:
        httpx.HTTPStatusError: If the request fails.
    """
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
    }

    async with httpx.AsyncClient() as client:
        user_resp = await client.get(_USER_URL, headers=headers)
        user_resp.raise_for_status()
        user = user_resp.json()

        # Resolve email: use /user endpoint first, fall back to /user/emails
        email = user.get('email') or ''
        if not email:
            emails_resp = await client.get(_EMAILS_URL, headers=headers)
            emails_resp.raise_for_status()
            for entry in emails_resp.json():
                if entry.get('primary') and entry.get('verified'):
                    email = entry['email']
                    break

    return {
        'id': str(user.get('id', '')),
        'email': email,
        'name': user.get('name') or '',
        'avatar_url': user.get('avatar_url') or '',
        'login': user.get('login', ''),
        'raw': user,
    }
