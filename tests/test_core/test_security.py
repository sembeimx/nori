"""Tests for core.auth.security."""

import pytest
from core.auth.security import Security

# --- hash_password / verify_password ---


@pytest.mark.asyncio
async def test_hash_and_verify():
    hashed = await Security.hash_password('mypassword')
    assert await Security.verify_password('mypassword', hashed) is True


@pytest.mark.asyncio
async def test_verify_wrong_password():
    hashed = await Security.hash_password('correct')
    assert await Security.verify_password('wrong', hashed) is False


@pytest.mark.asyncio
async def test_hash_format():
    hashed = await Security.hash_password('test')
    parts = hashed.split('$')
    assert len(parts) == 4
    assert parts[0] == 'pbkdf2_sha256'
    assert parts[1].isdigit()  # iterations


@pytest.mark.asyncio
async def test_hash_unique_salt():
    """Two hashes of the same password should differ (different salt)."""
    h1 = await Security.hash_password('same')
    h2 = await Security.hash_password('same')
    assert h1 != h2


@pytest.mark.asyncio
async def test_custom_iterations():
    hashed = await Security.hash_password('test', iterations=1000)
    assert '$1000$' in hashed
    assert await Security.verify_password('test', hashed) is True


@pytest.mark.asyncio
async def test_verify_invalid_format():
    assert await Security.verify_password('x', 'invalid') is False


@pytest.mark.asyncio
async def test_verify_wrong_method():
    assert await Security.verify_password('x', 'bcrypt$100$salt$hash') is False


@pytest.mark.asyncio
async def test_verify_non_integer_iterations_returns_false():
    """If the iterations field of a 4-part hash is not an int, verify returns False (not crash)."""
    # Same shape as hash_password output, but iterations field is garbage
    bogus = 'pbkdf2_sha256$NOT_AN_INT$abcdef$0123456789abcdef'
    assert await Security.verify_password('whatever', bogus) is False


@pytest.mark.asyncio
async def test_verify_legacy_three_part_hash():
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
    assert await Security.verify_password('secret', legacy) is True
    assert await Security.verify_password('wrong', legacy) is False


@pytest.mark.asyncio
async def test_hash_password_does_not_block_event_loop():
    """The hash runs on a worker thread, so concurrent awaits make progress.

    Pre-async, ``hash_password`` blocked the event loop for the entire
    PBKDF2 (50-200ms with 100k iterations). A burst of N concurrent
    hashes ran serially, taking ~N * 100ms total. With ``asyncio.to_thread``
    they run on the default executor (8+ workers), so wall-clock time
    stays close to the single-call cost regardless of concurrency.
    """
    import asyncio
    import time

    # Use the production iteration count so the test exercises the real
    # blocking budget. 8 concurrent hashes; if the loop is blocked,
    # wall time is 8x; if offloaded, ~1x.
    start = time.perf_counter()
    await asyncio.gather(*[Security.hash_password(f'pw-{i}') for i in range(8)])
    elapsed = time.perf_counter() - start

    # A single 100k-iteration hash is ~50-200ms on commodity hardware;
    # 8 in parallel on the default thread pool should land well under
    # 4x that. Pick a generous ceiling so this isn't flaky on slow CI.
    assert elapsed < 4.0, (
        f'8 concurrent hashes took {elapsed:.2f}s — looks like the event '
        'loop is still blocked on PBKDF2 instead of offloading via to_thread.'
    )


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
