"""Password hashing (PBKDF2-HMAC-SHA256) and secure token generation."""

from __future__ import annotations

import hashlib
import hmac
import secrets

DEFAULT_ITERATIONS = 100_000


class Security:
    """Password hashing and token generation."""

    @staticmethod
    def hash_password(password: str, iterations: int | None = None) -> str:
        """
        Hash with PBKDF2-HMAC-SHA256.
        Returns: 'pbkdf2_sha256$iterations$salt$hash'
        """
        iterations = iterations or DEFAULT_ITERATIONS
        salt = secrets.token_hex(16)
        hash_bytes = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
        hash_hex = hash_bytes.hex()
        return f'pbkdf2_sha256${iterations}${salt}${hash_hex}'

    @staticmethod
    def verify_password(plain_password: str, password_hash: str) -> bool:
        """
        Verify password against stored hash.
        Supports old format (method$salt$hash) and new (method$iterations$salt$hash).
        """
        parts = password_hash.split('$')

        if len(parts) == 4:
            method, iterations_str, salt, stored_hash = parts
            try:
                iterations = int(iterations_str)
            except ValueError:
                return False
        elif len(parts) == 3:
            method, salt, stored_hash = parts
            iterations = DEFAULT_ITERATIONS
        else:
            return False

        if method != 'pbkdf2_sha256':
            return False

        hash_bytes = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt.encode('utf-8'), iterations)
        return hmac.compare_digest(hash_bytes.hex(), stored_hash)

    @staticmethod
    def generate_token(length: int = 32) -> str:
        """Cryptographic random token (hex)."""
        return secrets.token_hex(length)

    @staticmethod
    def generate_csrf_token() -> str:
        """CSRF token (32 bytes / 64 hex chars)."""
        return secrets.token_hex(32)
