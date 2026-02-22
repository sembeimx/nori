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
