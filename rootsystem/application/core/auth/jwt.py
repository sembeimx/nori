"""
JWT (JSON Web Tokens) with HMAC-SHA256.

Manual implementation consistent with the framework's stdlib-first philosophy.

    from core.auth.jwt import create_token, verify_token

    token = create_token({'user_id': 42}, expires_in=3600)
    payload = verify_token(token)  # dict or None
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from core.conf import config
from core.logger import get_logger

_log = get_logger('jwt')


def _get_secret() -> str:
    """Return JWT secret, warning if it falls back to SECRET_KEY."""
    secret = config.get('JWT_SECRET', None)
    if not secret or secret == config.SECRET_KEY:
        _log.warning("JWT_SECRET not set; falling back to SECRET_KEY")
        return config.SECRET_KEY
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

    header = _base64url_encode(json.dumps(
        {'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':'),
    ).encode('utf-8'))

    now = int(time.time())
    payload = {**payload, 'iat': now, 'exp': now + expires_in}

    payload_encoded = _base64url_encode(json.dumps(
        payload, separators=(',', ':'),
    ).encode('utf-8'))

    header_payload = f"{header}.{payload_encoded}"
    signature = _sign(header_payload, secret)

    return f"{header_payload}.{signature}"


def verify_token(token: str) -> dict | None:
    """
    Verify and decode a JWT token.

    Returns:
        Payload dict if valid, None if invalid/expired.
    """
    secret = _get_secret()

    parts = token.split('.')
    if len(parts) != 3:
        return None

    # Validate header algorithm (defensive: reject alg != HS256)
    try:
        header = json.loads(_base64url_decode(parts[0]))
    except (json.JSONDecodeError, ValueError):
        _log.debug("Invalid JWT header encoding")
        return None
    if header.get('alg') != 'HS256':
        _log.debug("Unsupported JWT algorithm: %s", header.get('alg'))
        return None

    header_payload = f"{parts[0]}.{parts[1]}"
    expected_sig = _sign(header_payload, secret)

    if not hmac.compare_digest(parts[2], expected_sig):
        return None

    try:
        payload = json.loads(_base64url_decode(parts[1]))
    except (json.JSONDecodeError, ValueError):
        _log.debug("Invalid JWT payload encoding")
        return None

    # Clock skew tolerance (seconds) for distributed systems
    _LEEWAY = 10
    if 'exp' in payload and payload['exp'] < (int(time.time()) - _LEEWAY):
        return None

    return payload
