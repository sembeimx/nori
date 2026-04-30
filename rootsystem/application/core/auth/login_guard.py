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

from core.cache import cache_delete, cache_get, cache_incr, cache_set
from core.logger import get_logger

_log = get_logger('auth')

_PREFIX = 'login_guard:'
_MAX_ATTEMPTS = 5
_LOCKOUT_SCHEDULE = [60, 300, 900, 1800, 3600]  # 1m, 5m, 15m, 30m, 1h
_TRACKING_TTL = 3600  # Keep attempt data for 1 hour


def _attempts_key(identifier: str) -> str:
    return f'{_PREFIX}{identifier}:attempts'


def _lockouts_key(identifier: str) -> str:
    return f'{_PREFIX}{identifier}:lockouts'


def _locked_until_key(identifier: str) -> str:
    return f'{_PREFIX}{identifier}:locked_until'


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
    locked_until = await cache_get(_locked_until_key(identifier)) or 0
    if locked_until and time.time() < locked_until:
        return False, int(locked_until - time.time()) + 1
    return True, 0


async def record_failed_login(identifier: str) -> None:
    """
    Record a failed login attempt. After ``_MAX_ATTEMPTS`` consecutive failures,
    the account is locked with escalating duration.

    State lives in three scalar cache keys (attempts, lockouts, locked_until)
    so the counter can use atomic INCR — see AGENTS.md §6 "Cache atomicity".
    A previous single-dict storage shape was vulnerable to a TOCTOU race
    that let parallel callers all read attempts=0 and clobber each other,
    bypassing the lockout entirely.
    """
    # Fast path: already locked, no work to do.
    locked_until = await cache_get(_locked_until_key(identifier)) or 0
    if locked_until and time.time() < locked_until:
        return

    # Atomic increment — survives 100 concurrent failed logins.
    attempts = await cache_incr(_attempts_key(identifier), ttl=_TRACKING_TTL)

    # Use ``==`` (not ``>=``) so only the request that crosses the threshold
    # escalates the lockout. With ``>=``, a burst of N concurrent failed
    # logins (where N > _MAX_ATTEMPTS) would advance the *lockouts* counter
    # by N - _MAX_ATTEMPTS in milliseconds — skipping every tier of the
    # escalating schedule and pinning the victim to the maximum 1-hour
    # lockout from a single concurrent burst. Subsequent requests that
    # see ``attempts > _MAX_ATTEMPTS`` are no-ops; they would have rejected
    # in the fast-path above had they arrived after locked_until was set.
    if attempts == _MAX_ATTEMPTS:
        lockouts = await cache_incr(_lockouts_key(identifier), ttl=_TRACKING_TTL)
        duration = _lockout_duration(lockouts - 1)  # cache_incr returns the new value (1-indexed)
        new_locked_until = time.time() + duration
        await cache_set(_locked_until_key(identifier), new_locked_until, _TRACKING_TTL)
        # Reset the attempts counter so the next round starts clean.
        await cache_delete(_attempts_key(identifier))
        _log.warning('Account locked: %s (lockout #%d, %ds)', identifier, lockouts, duration)


async def clear_failed_logins(identifier: str) -> None:
    """Clear all failed login tracking for the given identifier (call on successful login)."""
    await cache_delete(_attempts_key(identifier))
    await cache_delete(_lockouts_key(identifier))
    await cache_delete(_locked_until_key(identifier))
