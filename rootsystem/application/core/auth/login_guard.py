"""
Per-account brute-force protection using the cache backend.

Usage::

    from core.auth import check_login_allowed, record_failed_login, clear_failed_logins

    async def login(self, request):
        email = form['email']

        allowed, retry_after = await check_login_allowed(email)
        if not allowed:
            return JSONResponse({'error': f'Too many attempts. Try again in {retry_after}s.'}, 429)

        user = await User.get_or_none(email=email)
        if not user or not Security.verify_password(form['password'], user.password_hash):
            await record_failed_login(email)
            return JSONResponse({'error': 'Invalid credentials'}, 401)

        await clear_failed_logins(email)
        # ... start session ...
"""
from __future__ import annotations

import time

from core.cache import cache_delete, cache_get, cache_set
from core.logger import get_logger

_log = get_logger('auth')

_PREFIX = 'login_guard:'
_MAX_ATTEMPTS = 5
_LOCKOUT_SCHEDULE = [60, 300, 900, 1800, 3600]  # 1m, 5m, 15m, 30m, 1h
_TRACKING_TTL = 3600  # Keep attempt data for 1 hour


def _lockout_duration(lockout_count: int) -> int:
    """Return lockout duration in seconds based on how many times the account has been locked."""
    idx = min(lockout_count, len(_LOCKOUT_SCHEDULE) - 1)
    return _LOCKOUT_SCHEDULE[idx]


async def check_login_allowed(identifier: str) -> tuple[bool, int]:
    """
    Check if a login attempt is allowed for the given identifier (email, username, etc.).

    Returns (allowed, retry_after_seconds).
    When allowed is True, retry_after is 0.
    When allowed is False, retry_after is the seconds remaining until the lockout expires.
    """
    data = await cache_get(f"{_PREFIX}{identifier}")
    if data is None:
        return True, 0

    locked_until = data.get('locked_until', 0)
    if locked_until and time.time() < locked_until:
        return False, int(locked_until - time.time()) + 1

    return True, 0


async def record_failed_login(identifier: str) -> None:
    """
    Record a failed login attempt. After ``_MAX_ATTEMPTS`` consecutive failures,
    the account is locked with escalating duration.
    """
    key = f"{_PREFIX}{identifier}"
    data = await cache_get(key) or {'attempts': 0, 'lockouts': 0, 'locked_until': 0}

    # If currently locked, don't count additional attempts
    if data.get('locked_until', 0) and time.time() < data['locked_until']:
        return

    data['attempts'] = data.get('attempts', 0) + 1

    if data['attempts'] >= _MAX_ATTEMPTS:
        lockouts = data.get('lockouts', 0)
        duration = _lockout_duration(lockouts)
        data['locked_until'] = time.time() + duration
        data['lockouts'] = lockouts + 1
        data['attempts'] = 0
        _log.warning("Account locked: %s (lockout #%d, %ds)", identifier, data['lockouts'], duration)

    await cache_set(key, data, _TRACKING_TTL)


async def clear_failed_logins(identifier: str) -> None:
    """Clear all failed login tracking for the given identifier (call on successful login)."""
    await cache_delete(f"{_PREFIX}{identifier}")
