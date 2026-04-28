"""Tests for core.auth.jwt."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

import pytest
from core.auth.jwt import _base64url_decode, _base64url_encode, create_token, verify_token


@pytest.mark.asyncio
async def test_create_and_verify_roundtrip():
    """Token can be created and verified."""
    token = create_token({'user_id': 42}, expires_in=3600)
    payload = await verify_token(token)
    assert payload is not None
    assert payload['user_id'] == 42


@pytest.mark.asyncio
async def test_payload_contains_iat_exp():
    """Token payload includes iat and exp claims."""
    token = create_token({'role': 'admin'}, expires_in=60)
    payload = await verify_token(token)
    assert 'iat' in payload
    assert 'exp' in payload
    assert payload['exp'] - payload['iat'] == 60


@pytest.mark.asyncio
async def test_expired_token():
    """Expired token (beyond leeway) returns None."""
    token = create_token({'user_id': 1}, expires_in=-30)
    assert await verify_token(token) is None


@pytest.mark.asyncio
async def test_tampered_token():
    """Tampered payload invalidates signature."""
    token = create_token({'user_id': 1})
    parts = token.split('.')
    # Tamper with payload
    tampered = parts[0] + '.' + _base64url_encode(b'{"user_id":999,"iat":0,"exp":9999999999}') + '.' + parts[2]
    assert await verify_token(tampered) is None


@pytest.mark.asyncio
async def test_invalid_format():
    """Malformed tokens return None."""
    assert await verify_token('not.a.valid.token') is None
    assert await verify_token('') is None
    assert await verify_token('onlyonepart') is None


def test_base64url_roundtrip():
    """Base64url encode/decode is lossless."""
    data = b'Hello, World! \x00\xff'
    encoded = _base64url_encode(data)
    decoded = _base64url_decode(encoded)
    assert decoded == data


@pytest.mark.asyncio
async def test_token_within_leeway_accepted():
    """Token expired within the 10s leeway is still accepted."""
    token = create_token({'user_id': 1}, expires_in=-5)
    assert await verify_token(token) is not None


@pytest.mark.asyncio
async def test_wrong_algorithm_rejected():
    """Token with alg != HS256 is rejected."""
    import json

    header = _base64url_encode(json.dumps({'alg': 'none', 'typ': 'JWT'}, separators=(',', ':')).encode())
    payload = _base64url_encode(json.dumps({'user_id': 1, 'iat': 0, 'exp': 9999999999}, separators=(',', ':')).encode())
    fake_token = f'{header}.{payload}.fakesig'
    assert await verify_token(fake_token) is None


@pytest.mark.asyncio
async def test_invalid_header_encoding():
    """Token with garbage header returns None."""
    assert await verify_token('!!!.payload.sig') is None


@pytest.mark.asyncio
async def test_empty_bearer_token():
    """Empty string token returns None."""
    assert await verify_token('') is None


@pytest.mark.asyncio
async def test_corrupt_payload_returns_none():
    """A token with valid header+sig shape but garbage payload encoding returns None."""
    # Valid header (HS256), invalid base64url for payload, fake signature.
    import json

    from core.auth.jwt import _sign

    header = _base64url_encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    bad_payload = '!!!not-base64!!!'
    # Forge a real signature so we get past compare_digest and reach the payload-decode try/except
    from core.auth.jwt import _get_secret

    sig = _sign(f'{header}.{bad_payload}', _get_secret())
    assert await verify_token(f'{header}.{bad_payload}.{sig}') is None


def test_get_secret_returns_jwt_secret_when_configured():
    """When JWT_SECRET is set distinct from SECRET_KEY, _get_secret returns it (no fallback)."""
    from unittest.mock import patch

    from core.auth.jwt import _get_secret

    with patch('core.auth.jwt.config') as mock_config:
        mock_config.SECRET_KEY = 'session-key'
        mock_config.get.return_value = 'distinct-jwt-secret'
        assert _get_secret() == 'distinct-jwt-secret'


@pytest.mark.asyncio
async def test_revoke_token_raises_without_jti():
    """revoke_token must reject payloads that have no jti claim."""
    from core.auth.jwt import revoke_token

    with pytest.raises(ValueError, match='jti'):
        await revoke_token({'user_id': 1, 'exp': 9999999999})


@pytest.mark.asyncio
async def test_revoke_token_silently_ignores_invalid_token_string():
    """revoke_token of an invalid/expired token string is a no-op (does not raise)."""
    from core.auth.jwt import revoke_token

    # 'gibberish' is not a valid JWT — verify_token returns None, revoke returns silently
    await revoke_token('gibberish')  # must not raise


@pytest.mark.asyncio
async def test_revoke_token_blocks_verify_under_redis_backend(monkeypatch):
    """Regression for the v1.16.0 security fix.

    Prior to v1.16.0, ``_is_blacklisted`` reached into ``backend._store``
    directly, which only existed on ``MemoryCacheBackend``. With Redis (or
    any non-memory backend), the hasattr check returned False, the read
    returned None, and revoked tokens silently passed verification. This
    test forces a Redis-backed cache and asserts revoke→verify blocks.
    """
    pytest.importorskip('fakeredis')
    from unittest.mock import patch

    import core.cache as cache_module
    import fakeredis.aioredis
    from core.auth.jwt import create_token, revoke_token

    # Force a Redis backend wired to fakeredis. fakeredis has NO _store
    # attribute, so the old sync path would silently miss the blacklist.
    fake = fakeredis.aioredis.FakeRedis()
    with patch('redis.asyncio.from_url', return_value=fake):
        redis_backend = cache_module.RedisCacheBackend('redis://localhost:6379')
    monkeypatch.setattr(cache_module, '_backend', redis_backend)

    # Sanity: the active backend must NOT have _store (otherwise the test
    # would be inadvertently exercising the old buggy path on memory).
    assert not hasattr(redis_backend, '_store')

    token = create_token({'user_id': 7}, expires_in=3600)

    # Before revocation: token verifies fine.
    payload = await verify_token(token)
    assert payload is not None
    assert payload['user_id'] == 7
    assert 'jti' in payload  # create_token stamps a jti by default

    # Revoke and verify again: must now return None.
    await revoke_token(token)
    assert await verify_token(token) is None
