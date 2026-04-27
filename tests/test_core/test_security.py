"""Tests for core.auth.security."""

from core.auth.security import Security

# --- hash_password / verify_password ---


def test_hash_and_verify():
    hashed = Security.hash_password('mypassword')
    assert Security.verify_password('mypassword', hashed) is True


def test_verify_wrong_password():
    hashed = Security.hash_password('correct')
    assert Security.verify_password('wrong', hashed) is False


def test_hash_format():
    hashed = Security.hash_password('test')
    parts = hashed.split('$')
    assert len(parts) == 4
    assert parts[0] == 'pbkdf2_sha256'
    assert parts[1].isdigit()  # iterations


def test_hash_unique_salt():
    """Two hashes of the same password should differ (different salt)."""
    h1 = Security.hash_password('same')
    h2 = Security.hash_password('same')
    assert h1 != h2


def test_custom_iterations():
    hashed = Security.hash_password('test', iterations=1000)
    assert '$1000$' in hashed
    assert Security.verify_password('test', hashed) is True


def test_verify_invalid_format():
    assert Security.verify_password('x', 'invalid') is False


def test_verify_wrong_method():
    assert Security.verify_password('x', 'bcrypt$100$salt$hash') is False


def test_verify_non_integer_iterations_returns_false():
    """If the iterations field of a 4-part hash is not an int, verify returns False (not crash)."""
    # Same shape as hash_password output, but iterations field is garbage
    bogus = 'pbkdf2_sha256$NOT_AN_INT$abcdef$0123456789abcdef'
    assert Security.verify_password('whatever', bogus) is False


def test_verify_legacy_three_part_hash():
    """Hashes from the pre-iterations-in-format era still verify correctly.

    The legacy format method$salt$hash is treated as DEFAULT_ITERATIONS,
    matching the historical default before we wrote iterations into the
    hash string. Existing user records hashed under the old code must
    keep working.
    """
    import hashlib

    from core.auth.security import DEFAULT_ITERATIONS

    salt = 'abc123'
    hash_bytes = hashlib.pbkdf2_hmac('sha256', b'secret', salt.encode('utf-8'), DEFAULT_ITERATIONS)
    legacy = f'pbkdf2_sha256${salt}${hash_bytes.hex()}'
    assert Security.verify_password('secret', legacy) is True
    assert Security.verify_password('wrong', legacy) is False


# --- generate_token ---


def test_generate_token_length():
    token = Security.generate_token(16)
    assert len(token) == 32  # hex = 2x bytes


def test_generate_token_unique():
    t1 = Security.generate_token()
    t2 = Security.generate_token()
    assert t1 != t2


# --- generate_csrf_token ---


def test_csrf_token_length():
    token = Security.generate_csrf_token()
    assert len(token) == 64  # 32 bytes = 64 hex chars


def test_csrf_token_unique():
    t1 = Security.generate_csrf_token()
    t2 = Security.generate_csrf_token()
    assert t1 != t2
