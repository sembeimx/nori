"""Password hashing (PBKDF2-HMAC-SHA256) and secure token generation.

PBKDF2 with 100k iterations is CPU-bound — a single call takes 50-200ms.
Running it directly on the asyncio event loop blocks every other request
in the same worker until the hash finishes; a burst of logins is enough
to stall the whole server. The hash / verify methods are therefore
``async`` and offload the work via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets

DEFAULT_ITERATIONS = 100_000


def _pbkdf2(password: str, salt: str, iterations: int) -> bytes:
    """The CPU-bound bit. Runs in a worker thread via ``asyncio.to_thread``."""
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)


class Security:
    """Password hashing and token generation."""

    @staticmethod
    async def hash_password(password: str, iterations: int | None = None) -> str:
        """
        Hash with PBKDF2-HMAC-SHA256.

        Returns: ``'pbkdf2_sha256$iterations$salt$hash'``.

        Async because PBKDF2 is CPU-bound (~50-200ms with 100k iterations).
        Awaiting offloads it to a thread so the event loop keeps serving
        other requests during the hash.
        """
        iterations = iterations or DEFAULT_ITERATIONS
        salt = secrets.token_hex(16)
        hash_bytes = await asyncio.to_thread(_pbkdf2, password, salt, iterations)
        hash_hex = hash_bytes.hex()
        return f'pbkdf2_sha256${iterations}${salt}${hash_hex}'

    @staticmethod
    async def verify_password(plain_password: str, password_hash: str) -> bool:
        """
        Verify password against stored hash.

        Supports old format (``method$salt$hash``) and new
        (``method$iterations$salt$hash``). Async for the same reason as
        :meth:`hash_password`.
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

        hash_bytes = await asyncio.to_thread(_pbkdf2, plain_password, salt, iterations)
        return hmac.compare_digest(hash_bytes.hex(), stored_hash)

    @staticmethod
    def generate_token(length: int = 32) -> str:
        """Cryptographic random token (hex)."""
        return secrets.token_hex(length)

    @staticmethod
    def generate_csrf_token() -> str:
        """CSRF token (32 bytes / 64 hex chars)."""
        return secrets.token_hex(32)
