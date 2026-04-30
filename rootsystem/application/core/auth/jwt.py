"""
JWT (JSON Web Tokens) with HMAC-SHA256.

Manual implementation consistent with the framework's stdlib-first philosophy.

    from core.auth.jwt import create_token, verify_token

    token = create_token({'user_id': 42}, expires_in=3600)
    payload = await verify_token(token)  # dict or None

``verify_token`` is async because the revocation check goes through the
configured cache backend (memory or Redis). All Nori controllers and
middleware are async, so callers naturally have an await context.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from core.conf import config
from core.logger import get_logger

_log = get_logger('jwt')


def _get_secret() -> str:
    """Return JWT secret, warning if it falls back to SECRET_KEY."""
    secret: str | None = config.get('JWT_SECRET', None)
    fallback: str = config.SECRET_KEY
    if not secret or secret == fallback:
        _log.warning('JWT_SECRET not set; falling back to SECRET_KEY')
        return fallback
    return secret


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _base64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


def _sign(header_payload: str, secret: str) -> str:
    """HMAC-SHA256 signature of header.payload string."""
    sig = hmac.new(
        secret.encode('utf-8'),
        header_payload.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(sig)


def create_token(payload: dict, *, expires_in: int | None = None) -> str:
    """
    Create a JWT token.

    Args:
        payload: Claims dict (e.g. {'user_id': 42}).
        expires_in: Expiration in seconds (default: settings.JWT_EXPIRATION).

    Returns:
        JWT string (header.payload.signature).
    """
    if expires_in is None:
        expires_in = config.get('JWT_EXPIRATION', 3600)

    secret = _get_secret()

    header = _base64url_encode(
        json.dumps(
            {'alg': 'HS256', 'typ': 'JWT'},
            separators=(',', ':'),
        ).encode('utf-8')
    )

    now = int(time.time())
    payload = {**payload, 'iat': now, 'exp': now + expires_in}
    if 'jti' not in payload:
        payload['jti'] = secrets.token_urlsafe(16)

    payload_encoded = _base64url_encode(
        json.dumps(
            payload,
            separators=(',', ':'),
        ).encode('utf-8')
    )

    header_payload = f'{header}.{payload_encoded}'
    signature = _sign(header_payload, secret)

    return f'{header_payload}.{signature}'


async def verify_token(token: str) -> dict[str, Any] | None:
    """
    Verify and decode a JWT token.

    Returns:
        Payload dict if valid, None if invalid/expired/revoked.
    """
    secret = _get_secret()

    parts = token.split('.')
    if len(parts) != 3:
        return None

    # Validate header algorithm (defensive: reject alg != HS256)
    try:
        header = json.loads(_base64url_decode(parts[0]))
    except (json.JSONDecodeError, ValueError):
        _log.debug('Invalid JWT header encoding')
        return None
    if header.get('alg') != 'HS256':
        _log.debug('Unsupported JWT algorithm: %s', header.get('alg'))
        return None

    header_payload = f'{parts[0]}.{parts[1]}'
    expected_sig = _sign(header_payload, secret)

    if not hmac.compare_digest(parts[2], expected_sig):
        return None

    try:
        payload: dict[str, Any] = json.loads(_base64url_decode(parts[1]))
    except (json.JSONDecodeError, ValueError):
        _log.debug('Invalid JWT payload encoding')
        return None

    # Clock skew tolerance (seconds) for distributed systems
    _LEEWAY = 10
    if 'exp' in payload and payload['exp'] < (int(time.time()) - _LEEWAY):
        return None

    # Check blacklist (if jti is present)
    jti = payload.get('jti')
    if jti and await _is_blacklisted(jti):
        _log.debug('JWT rejected: jti %s is blacklisted', jti)
        return None

    return payload


_BLACKLIST_PREFIX = 'jwt_blacklist:'


async def _is_blacklisted(jti: str) -> bool:
    """Check the configured cache backend for a revocation entry.

    Goes through the framework's cache abstraction so it works with
    any backend (memory in dev, Redis in prod). The previous sync
    implementation peeked at ``backend._store`` directly, which only
    existed on ``MemoryCacheBackend`` — Redis deployments silently
    skipped the check and accepted revoked tokens.
    """
    from core.cache import cache_get

    value = await cache_get(f'{_BLACKLIST_PREFIX}{jti}')
    return value is not None


async def revoke_token(token_or_payload: str | dict) -> bool:
    """Revoke a JWT by adding its ``jti`` to the blacklist.

    The blacklist entry expires when the token itself would have expired,
    so the cache doesn't grow indefinitely.

    Tokens issued by ``create_token`` always carry a ``jti``, so revocation
    works out of the box for first-party tokens. ``jti`` is optional in the
    JWT spec, so third-party or legacy tokens without one cannot be
    blacklisted reliably — for those, this function logs a warning and
    returns ``False`` instead of raising. This keeps logout controllers
    crash-free when handling foreign tokens; rely on token expiry alone
    in that case.

    Args:
        token_or_payload: A JWT string or an already-decoded payload dict.

    Returns:
        ``True`` if the token was added to the blacklist, ``False`` if the
        token was already invalid/expired or had no ``jti`` to track.

    Usage::

        from core.auth.jwt import revoke_token

        # Revoke by token string
        await revoke_token(token_string)

        # Revoke by payload (from request.state.token_payload)
        await revoke_token(request.state.token_payload)
    """
    from core.cache import cache_set

    if isinstance(token_or_payload, str):
        payload = await verify_token(token_or_payload)
        if payload is None:
            return False  # Already invalid/expired, nothing to revoke
    else:
        payload = token_or_payload

    jti = payload.get('jti')
    if not jti:
        # `jti` is optional per RFC 7519 — third-party tokens may omit it.
        # Raising here would crash logout controllers that accept foreign
        # tokens; degrade gracefully and rely on natural expiry instead.
        _log.warning('revoke_token: payload has no jti claim, cannot blacklist')
        return False

    # TTL = remaining time until expiry (or 1 hour if no exp)
    exp = payload.get('exp', int(time.time()) + 3600)
    ttl = max(exp - int(time.time()), 1)

    await cache_set(f'{_BLACKLIST_PREFIX}{jti}', True, ttl=ttl)
    return True
