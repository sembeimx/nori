"""Tests for core.auth.jwt."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from core.auth.jwt import _base64url_decode, _base64url_encode, create_token, verify_token


def test_create_and_verify_roundtrip():
    """Token can be created and verified."""
    token = create_token({'user_id': 42}, expires_in=3600)
    payload = verify_token(token)
    assert payload is not None
    assert payload['user_id'] == 42


def test_payload_contains_iat_exp():
    """Token payload includes iat and exp claims."""
    token = create_token({'role': 'admin'}, expires_in=60)
    payload = verify_token(token)
    assert 'iat' in payload
    assert 'exp' in payload
    assert payload['exp'] - payload['iat'] == 60


def test_expired_token():
    """Expired token (beyond leeway) returns None."""
    token = create_token({'user_id': 1}, expires_in=-30)
    assert verify_token(token) is None


def test_tampered_token():
    """Tampered payload invalidates signature."""
    token = create_token({'user_id': 1})
    parts = token.split('.')
    # Tamper with payload
    tampered = parts[0] + '.' + _base64url_encode(b'{"user_id":999,"iat":0,"exp":9999999999}') + '.' + parts[2]
    assert verify_token(tampered) is None


def test_invalid_format():
    """Malformed tokens return None."""
    assert verify_token('not.a.valid.token') is None
    assert verify_token('') is None
    assert verify_token('onlyonepart') is None


def test_base64url_roundtrip():
    """Base64url encode/decode is lossless."""
    data = b'Hello, World! \x00\xff'
    encoded = _base64url_encode(data)
    decoded = _base64url_decode(encoded)
    assert decoded == data


def test_token_within_leeway_accepted():
    """Token expired within the 10s leeway is still accepted."""
    token = create_token({'user_id': 1}, expires_in=-5)
    assert verify_token(token) is not None


def test_wrong_algorithm_rejected():
    """Token with alg != HS256 is rejected."""
    import json

    header = _base64url_encode(json.dumps({'alg': 'none', 'typ': 'JWT'}, separators=(',', ':')).encode())
    payload = _base64url_encode(json.dumps({'user_id': 1, 'iat': 0, 'exp': 9999999999}, separators=(',', ':')).encode())
    fake_token = f'{header}.{payload}.fakesig'
    assert verify_token(fake_token) is None


def test_invalid_header_encoding():
    """Token with garbage header returns None."""
    assert verify_token('!!!.payload.sig') is None


def test_empty_bearer_token():
    """Empty string token returns None."""
    assert verify_token('') is None
