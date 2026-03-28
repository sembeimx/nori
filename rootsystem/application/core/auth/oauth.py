from __future__ import annotations

"""
OAuth2 security helpers — state parameter management and PKCE utilities.

These are pure-stdlib helpers used by OAuth service drivers in ``services/``.
They handle the security-critical parts of the OAuth flow (CSRF state tokens
and PKCE code challenges) so that individual providers don't reimplement them.

Usage from a service driver::

    from core.auth.oauth import generate_state, validate_state
    from core.auth.oauth import generate_pkce_verifier, get_pkce_verifier

    # In get_auth_url():
    state = generate_state(session)
    verifier, challenge = generate_pkce_verifier(session)

    # In handle_callback():
    if not validate_state(session, incoming_state):
        raise ValueError('Invalid OAuth state')
    code_verifier = get_pkce_verifier(session)
"""

import base64
import hashlib
import hmac
import secrets

_STATE_SESSION_KEY = '_oauth_state'
_PKCE_SESSION_KEY = '_oauth_pkce_verifier'


def generate_state(session: dict) -> str:
    """Generate a cryptographic OAuth state token and store it in the session.

    The state parameter prevents CSRF attacks during the OAuth flow.
    Each call overwrites any previous state in the session.

    Args:
        session: The Starlette session dict (``request.session``).

    Returns:
        A URL-safe random string (43 characters, 256 bits of entropy).
    """
    state = secrets.token_urlsafe(32)
    session[_STATE_SESSION_KEY] = state
    return state


def validate_state(session: dict, state: str) -> bool:
    """Validate the OAuth state parameter and consume it (single-use).

    Uses constant-time comparison to prevent timing attacks. The stored
    state is removed from the session regardless of the result to prevent
    replay attacks.

    Args:
        session: The Starlette session dict.
        state: The state parameter from the provider callback.

    Returns:
        ``True`` if valid, ``False`` otherwise.
    """
    expected = session.pop(_STATE_SESSION_KEY, None)
    if not expected or not state:
        return False
    return hmac.compare_digest(expected, state)


def generate_pkce_verifier(session: dict) -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256).

    The verifier is stored in the session for retrieval during the token
    exchange step.  Per RFC 7636, the verifier is a random string of
    43--128 characters and the challenge is ``BASE64URL(SHA256(verifier))``.

    Args:
        session: The Starlette session dict.

    Returns:
        Tuple of ``(code_verifier, code_challenge)``.
    """
    verifier = secrets.token_urlsafe(32)  # 43 chars
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    session[_PKCE_SESSION_KEY] = verifier
    return verifier, challenge


def get_pkce_verifier(session: dict) -> str | None:
    """Retrieve and consume the PKCE code_verifier from the session.

    Returns ``None`` if no verifier was stored (e.g. the provider does
    not use PKCE).  The verifier is removed from the session after
    retrieval to prevent reuse.

    Args:
        session: The Starlette session dict.

    Returns:
        The code_verifier string, or ``None``.
    """
    return session.pop(_PKCE_SESSION_KEY, None)
