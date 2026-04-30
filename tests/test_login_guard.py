import time

import pytest
from core.auth.login_guard import (
    _LOCKOUT_SCHEDULE,
    _MAX_ATTEMPTS,
    check_login_allowed,
    clear_failed_logins,
    record_failed_login,
)
from core.cache import reset_backend


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Reset the cache backend between tests."""
    reset_backend()
    yield
    reset_backend()


@pytest.mark.asyncio
async def test_first_attempt_is_allowed():
    allowed, retry_after = await check_login_allowed('user@example.com')
    assert allowed is True
    assert retry_after == 0


@pytest.mark.asyncio
async def test_attempts_below_threshold_are_allowed():
    for _ in range(_MAX_ATTEMPTS - 1):
        await record_failed_login('user@example.com')
    allowed, _ = await check_login_allowed('user@example.com')
    assert allowed is True


@pytest.mark.asyncio
async def test_lockout_after_max_attempts():
    for _ in range(_MAX_ATTEMPTS):
        await record_failed_login('user@example.com')
    allowed, retry_after = await check_login_allowed('user@example.com')
    assert allowed is False
    assert 0 < retry_after <= _LOCKOUT_SCHEDULE[0] + 1


@pytest.mark.asyncio
async def test_lockout_expires(monkeypatch):
    for _ in range(_MAX_ATTEMPTS):
        await record_failed_login('user@example.com')

    # Fast-forward past the lockout
    real_time = time.time
    monkeypatch.setattr(time, 'time', lambda: real_time() + _LOCKOUT_SCHEDULE[0] + 1)

    allowed, _ = await check_login_allowed('user@example.com')
    assert allowed is True


@pytest.mark.asyncio
async def test_escalating_lockout():
    """Second lockout should be longer than the first."""
    # First lockout
    for _ in range(_MAX_ATTEMPTS):
        await record_failed_login('user@example.com')

    allowed, first_retry = await check_login_allowed('user@example.com')
    assert allowed is False

    # Can't monkeypatch easily across modules with just function-level,
    # so we simulate: clear, then preset the lockouts counter directly
    # to put the next round on the second tier of the schedule.
    await clear_failed_logins('user@example.com')

    from core.cache import cache_set

    # Storage shape is per-key scalars (see login_guard.py — this layout is
    # what makes cache_incr atomic against concurrent failed logins).
    await cache_set('login_guard:user@example.com:lockouts', 1, 3600)

    # Trigger second lockout
    for _ in range(_MAX_ATTEMPTS):
        await record_failed_login('user@example.com')

    allowed, second_retry = await check_login_allowed('user@example.com')
    assert allowed is False
    assert second_retry > first_retry


@pytest.mark.asyncio
async def test_clear_resets_everything():
    for _ in range(_MAX_ATTEMPTS):
        await record_failed_login('user@example.com')
    await clear_failed_logins('user@example.com')

    allowed, retry_after = await check_login_allowed('user@example.com')
    assert allowed is True
    assert retry_after == 0


@pytest.mark.asyncio
async def test_different_identifiers_are_independent():
    for _ in range(_MAX_ATTEMPTS):
        await record_failed_login('alice@example.com')

    allowed_alice, _ = await check_login_allowed('alice@example.com')
    allowed_bob, _ = await check_login_allowed('bob@example.com')

    assert allowed_alice is False
    assert allowed_bob is True


@pytest.mark.asyncio
async def test_attempts_during_lockout_are_ignored():
    """Additional failed attempts during lockout should not extend it."""
    for _ in range(_MAX_ATTEMPTS):
        await record_failed_login('user@example.com')

    _, retry_before = await check_login_allowed('user@example.com')

    # Try more attempts while locked
    await record_failed_login('user@example.com')
    await record_failed_login('user@example.com')

    _, retry_after = await check_login_allowed('user@example.com')

    # retry_after should be less or equal (time passed), not greater
    assert retry_after <= retry_before


@pytest.mark.asyncio
async def test_successful_login_after_some_failures():
    """A successful login (clear) should reset attempts even before lockout."""
    for _ in range(_MAX_ATTEMPTS - 1):
        await record_failed_login('user@example.com')

    await clear_failed_logins('user@example.com')

    # Should start fresh — full _MAX_ATTEMPTS available again
    for _ in range(_MAX_ATTEMPTS - 1):
        await record_failed_login('user@example.com')

    allowed, _ = await check_login_allowed('user@example.com')
    assert allowed is True


@pytest.mark.asyncio
async def test_brute_force_concurrent_attempts_trigger_lockout():
    """Regression for the TOCTOU race that allowed concurrent attacks to bypass
    the 5-attempt lockout.

    Before the fix: 100 concurrent failed logins all read attempts=0 and wrote
    attempts=1 — counter never crossed _MAX_ATTEMPTS, lockout never fired.
    After the fix: cache_incr is atomic, so the counter advances reliably
    even under contention and the account locks.
    """
    import asyncio

    # 100 concurrent failed logins for the same identifier
    await asyncio.gather(*[record_failed_login('victim@example.com') for _ in range(100)])

    allowed, retry_after = await check_login_allowed('victim@example.com')
    assert allowed is False, (
        'Concurrent failed logins did not trigger the lockout — '
        'this means the cache update is racy and brute-force attacks bypass it.'
    )
    assert retry_after > 0
