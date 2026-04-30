"""
Google OAuth2 / OpenID Connect driver for Nori.

Implements the Authorization Code flow with PKCE (S256) as recommended
by Google for server-side applications.

Setup
-----

1. Create OAuth credentials at https://console.cloud.google.com/apis/credentials
2. Add your callback URL to **Authorized redirect URIs**
3. Set environment variables in ``.env``::

       GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
       GOOGLE_CLIENT_SECRET=your-client-secret

Usage in a controller::

    from services.oauth_google import get_auth_url, handle_callback

    class SocialAuthController:
        async def google_login(self, request):
            url = get_auth_url(request.session,
                               redirect_uri=str(request.url_for('auth.google.callback')))
            return RedirectResponse(url)

        async def google_callback(self, request):
            profile = await handle_callback(
                request.session,
                code=request.query_params['code'],
                redirect_uri=str(request.url_for('auth.google.callback')),
                state=request.query_params.get('state', ''),
            )
            # profile = {id, email, name, picture, email_verified, raw}
            # Create or link user, populate session, redirect...
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from core.auth.oauth import generate_pkce_verifier, generate_state, get_pkce_verifier, validate_state
from core.conf import config

_AUTHORIZE_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
_TOKEN_URL = 'https://oauth2.googleapis.com/token'  # noqa: S105 — public OAuth endpoint, not a secret
_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
_DEFAULT_SCOPES = 'openid email profile'

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the module-level httpx client, creating it on first use.

    A single persistent client pools TCP/TLS connections to
    ``oauth2.googleapis.com`` and ``openidconnect.googleapis.com`` across
    OAuth callbacks.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def shutdown() -> None:
    """Close the shared httpx client. Call from your ASGI lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_auth_url(
    session: dict,
    redirect_uri: str,
    scopes: str | None = None,
) -> str:
    """Build the Google authorization URL with state and PKCE.

    Args:
        session: The Starlette session dict (``request.session``).
        redirect_uri: The callback URL registered with Google.
        scopes: Space-separated scopes (default: ``'openid email profile'``).

    Returns:
        The full Google authorization URL to redirect the user to.
    """
    state = generate_state(session)
    _verifier, challenge = generate_pkce_verifier(session)

    params = {
        'client_id': config.GOOGLE_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': scopes or _DEFAULT_SCOPES,
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'access_type': 'offline',
        'prompt': 'consent',
    }
    return f'{_AUTHORIZE_URL}?{urlencode(params)}'


async def handle_callback(
    session: dict,
    code: str,
    redirect_uri: str,
    state: str,
) -> dict:
    """Exchange the authorization code for tokens and return the user profile.

    Validates the OAuth state parameter, exchanges the code using PKCE,
    then fetches the user profile from Google's userinfo endpoint.

    Args:
        session: The Starlette session dict.
        code: The authorization code from Google's callback.
        redirect_uri: Must match the ``redirect_uri`` used in :func:`get_auth_url`.
        state: The state parameter from the callback query string.

    Returns:
        Dict with keys: ``id``, ``email``, ``name``, ``picture``,
        ``email_verified``, ``raw`` (full Google response).

    Raises:
        ValueError: If state validation fails.
        httpx.HTTPStatusError: If the token exchange or userinfo request fails.
    """
    if not validate_state(session, state):
        raise ValueError('Invalid OAuth state parameter')

    code_verifier = get_pkce_verifier(session)

    client = _get_client()
    token_resp = await client.post(
        _TOKEN_URL,
        data={
            'client_id': config.GOOGLE_CLIENT_ID,
            'client_secret': config.GOOGLE_CLIENT_SECRET,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
            'code_verifier': code_verifier,
        },
    )
    token_resp.raise_for_status()
    tokens = token_resp.json()

    return await get_user_profile(tokens['access_token'])


async def get_user_profile(access_token: str) -> dict:
    """Fetch the Google user profile using an access token.

    The returned ``email`` is empty unless Google reports the address as
    verified. Google can issue an OIDC userinfo response with
    ``email_verified=False`` when the account was created against an email
    the user does not control (custom domains, third-party signups). Trusting
    that address as identity would let an attacker take over the account of
    the address's real owner, so we fail closed at the driver. Consumers
    needing the unverified value can still read ``raw['email']``.

    Args:
        access_token: A valid Google OAuth2 access token.

    Returns:
        Dict with keys: ``id``, ``email`` (empty if unverified), ``name``,
        ``picture``, ``email_verified``, ``raw``.

    Raises:
        httpx.HTTPStatusError: If the request fails.
    """
    client = _get_client()
    resp = await client.get(
        _USERINFO_URL,
        headers={'Authorization': f'Bearer {access_token}'},
    )
    resp.raise_for_status()
    data = resp.json()

    email_verified = bool(data.get('email_verified', False))
    email = data.get('email', '') if email_verified else ''

    return {
        'id': data.get('sub', ''),
        'email': email,
        'name': data.get('name', ''),
        'picture': data.get('picture', ''),
        'email_verified': email_verified,
        'raw': data,
    }
