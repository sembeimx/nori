"""Tests for core.auth.session_guard — session revocation via version counter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

# -- Fakes -------------------------------------------------------------------


class FakeSession(dict):
    pass


class FakeHeaders(dict):
    def get(self, key, default=''):
        return super().get(key.lower(), default)


class FakeState:
    pass


class FakeURL:
    path = '/test'


class FakeRequest:
    def __init__(self, *, user_id: int | None = None, session_version: int | None = None):
        self.session = FakeSession()
        if user_id is not None:
            self.session['user_id'] = user_id
        if session_version is not None:
            self.session['session_version'] = session_version
        self.headers = FakeHeaders({'accept': 'application/json'})
        self.state = FakeState()
        self.url = FakeURL()
        # Audit reads request.client.host as a fallback for IP resolution.
        self.client = SimpleNamespace(host='127.0.0.1')


class _FakeAwaitable:
    """Mimics a Tortoise query that becomes its result on await."""

    def __init__(self, result: Any):
        self._result = result

    def __await__(self):
        async def _coro():
            return self._result

        return _coro().__await__()


# -- Common fixtures ---------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """Each test starts with a clean breaker so prior test failures don't
    leak into the breaker state. The function is exposed via the module
    for this purpose; callers must not use it in production code."""
    import core.auth.session_guard as sg

    sg._reset_circuit()
    yield
    sg._reset_circuit()


@pytest.fixture
def enable_check(monkeypatch):
    """Turn the feature on for tests that exercise the gate."""
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CHECK=True),
    )


@pytest.fixture
def stub_audit(monkeypatch):
    """Replace ``audit`` with a recorder so tests can inspect what
    events fired and what payload they carried. The real audit writes
    to the DB asynchronously via a fire-and-forget Task — checking
    that here would be flaky."""
    import core.auth.session_guard as sg

    events: list[dict] = []

    def fake_audit(request, action, *, model_name=None, record_id=None, changes=None, user_id=None):
        events.append(
            {
                'action': action,
                'model_name': model_name,
                'record_id': record_id,
                'changes': changes,
            }
        )
        return None

    monkeypatch.setattr(sg, 'audit', fake_audit)
    return events


# ---------------------------------------------------------------------------
# Feature-flag and bypass paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_when_setting_unset(monkeypatch):
    """With SESSION_VERSION_CHECK unset, the gate is a no-op (always True)
    so existing projects upgrading to v1.33 see no behavior change."""
    from core.auth.session_guard import check_session_version
    from core.conf import config

    monkeypatch.setattr(config, '_settings', SimpleNamespace())

    req = FakeRequest(user_id=1, session_version=5)
    assert await check_session_version(req) is True


@pytest.mark.asyncio
async def test_no_user_id_passes_through(enable_check):
    """Anonymous request — gate has nothing to validate. Allow.
    Defence-in-depth alongside the existing user_id checks in the
    decorators; if a controller used the gate directly with no user, we
    must not crash."""
    from core.auth.session_guard import check_session_version

    req = FakeRequest()
    assert await check_session_version(req) is True


@pytest.mark.asyncio
async def test_session_without_version_key_passes_through(enable_check):
    """Sessions created before the project enabled the feature do NOT
    have a session_version key. Gate must allow them — the project
    populates the field at next login. Without this carve-out every
    user would be force-logged-out the moment SESSION_VERSION_CHECK
    flips from False to True."""
    from core.auth.session_guard import check_session_version

    req = FakeRequest(user_id=1)
    assert 'session_version' not in req.session
    assert await check_session_version(req) is True


# ---------------------------------------------------------------------------
# Cache hit paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_version_matches(enable_check, stub_audit, monkeypatch):
    """Happy path: cache returns the live version, session matches → allow.
    No audit events on a successful match (audit is for denial paths)."""
    import core.auth.session_guard as sg

    async def fake_cache_get(key):
        return 5

    async def fake_cache_set(key, value, ttl=0):
        return None

    monkeypatch.setattr(sg, 'cache_get', fake_cache_get)
    monkeypatch.setattr(sg, 'cache_set', fake_cache_set)

    req = FakeRequest(user_id=1, session_version=5)
    assert await sg.check_session_version(req) is True
    assert stub_audit == [], 'happy path must not write audit events'


@pytest.mark.asyncio
async def test_cache_hit_version_mismatch_denies_and_audits(enable_check, stub_audit, monkeypatch):
    """Cache returns 6, session has 5 → admin revoked between login and
    now. Deny + audit the revocation with both versions in changes for
    forensic trail."""
    import core.auth.session_guard as sg

    async def fake_cache_get(key):
        return 6

    monkeypatch.setattr(sg, 'cache_get', fake_cache_get)

    req = FakeRequest(user_id=1, session_version=5)
    assert await sg.check_session_version(req) is False
    assert any(e['action'] == 'session_guard.revoked' for e in stub_audit)
    revoked = next(e for e in stub_audit if e['action'] == 'session_guard.revoked')
    assert revoked['changes'] == {'session_v': 5, 'live_v': 6}, (
        'audit must capture both versions so the forensic trail can '
        'distinguish "session predates revocation" from "version corruption"'
    )


# ---------------------------------------------------------------------------
# Cache miss → DB read-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_falls_through_to_db_and_repopulates(enable_check, stub_audit, monkeypatch):
    """Cache returns None (key evicted, never written, etc.). DB is the
    authoritative source — read from there, populate the cache, then
    use the DB value for the comparison. Without the read-through, a
    cache eviction would silently disable revocation for the user
    until the next admin bump."""
    import core.auth.session_guard as sg

    cache_writes: list[tuple[str, int, int]] = []

    async def fake_cache_get(key):
        return None

    async def fake_cache_set(key, value, ttl=0):
        cache_writes.append((key, value, ttl))

    class FakeUser:
        def __init__(self, id, version):
            self.id = id
            self.session_version = version

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(FakeUser(id, version=7))

    monkeypatch.setattr(sg, 'cache_get', fake_cache_get)
    monkeypatch.setattr(sg, 'cache_set', fake_cache_set)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    req = FakeRequest(user_id=1, session_version=7)
    assert await sg.check_session_version(req) is True
    assert len(cache_writes) == 1
    assert cache_writes[0][0] == sg._version_key(1)
    assert cache_writes[0][1] == 7, (
        'cache must be repopulated from the DB read; otherwise every '
        'request would re-hit the DB until the admin bumps the version'
    )
    assert cache_writes[0][2] > 0, (
        'cache_set MUST pass a positive TTL — entries with TTL=0 never '
        'expire on the memory backend, which leaks the multi-worker '
        'staleness window indefinitely until LRU eviction'
    )


@pytest.mark.asyncio
async def test_cache_error_falls_through_to_db(enable_check, stub_audit, monkeypatch):
    """Cache raises (Redis down). DB still works — the framework should
    NOT degrade to fail-mode just because the cache hiccupped. The
    revocation channel is preserved as long as ANY storage tier
    answers."""
    import core.auth.session_guard as sg

    async def boom_cache_get(key):
        raise RuntimeError('redis: connection refused')

    async def fake_cache_set(key, value, ttl=0):
        return None

    class FakeUser:
        def __init__(self, id, version):
            self.id = id
            self.session_version = version

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(FakeUser(id, version=3))

    monkeypatch.setattr(sg, 'cache_get', boom_cache_get)
    monkeypatch.setattr(sg, 'cache_set', fake_cache_set)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    req = FakeRequest(user_id=1, session_version=3)
    assert await sg.check_session_version(req) is True
    assert all(e['action'] != 'session_guard.fail_open' for e in stub_audit), (
        'cache failure alone must not trigger fail-mode; only when DB also fails'
    )


@pytest.mark.asyncio
async def test_user_deleted_denies_and_audits(enable_check, stub_audit, monkeypatch):
    """User row no longer exists in DB. Stale session for a purged user
    must be rejected. This is distinct from "storage failed" — DB
    answered cleanly that the user is gone."""
    import core.auth.session_guard as sg

    async def fake_cache_get(key):
        return None

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(None)

    monkeypatch.setattr(sg, 'cache_get', fake_cache_get)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    req = FakeRequest(user_id=1, session_version=5)
    assert await sg.check_session_version(req) is False
    assert any(e['action'] == 'session_guard.user_deleted' for e in stub_audit)


# ---------------------------------------------------------------------------
# Both-stores-down: configurable fail mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_stores_fail_open_by_default(stub_audit, monkeypatch):
    """Default fail mode is ``open``: when both cache and DB fail, allow
    the request and audit ``session_guard.fail_open``. Pragmatic
    default for SaaS / blogs — a brief storage hiccup should not 401
    every authenticated request."""
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CHECK=True),
    )

    async def boom_cache_get(key):
        raise RuntimeError('cache down')

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            raise RuntimeError('db down')

    monkeypatch.setattr(sg, 'cache_get', boom_cache_get)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    req = FakeRequest(user_id=1, session_version=5)
    assert await sg.check_session_version(req) is True
    assert any(e['action'] == 'session_guard.fail_open' for e in stub_audit), (
        'fail-open path must emit an audit event so the security team has '
        'a forensic trail of when the gate was bypassed'
    )


@pytest.mark.asyncio
async def test_both_stores_fail_closed_when_configured(stub_audit, monkeypatch):
    """``SESSION_VERSION_FAIL_MODE = 'closed'`` denies on storage failure.
    Right for finance / healthcare — a brief DoS is acceptable; a
    brief auth bypass is not."""
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(
            SESSION_VERSION_CHECK=True,
            SESSION_VERSION_FAIL_MODE='closed',
        ),
    )

    async def boom_cache_get(key):
        raise RuntimeError('cache down')

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            raise RuntimeError('db down')

    monkeypatch.setattr(sg, 'cache_get', boom_cache_get)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    req = FakeRequest(user_id=1, session_version=5)
    assert await sg.check_session_version(req) is False
    assert any(e['action'] == 'session_guard.fail_closed' for e in stub_audit)


# ---------------------------------------------------------------------------
# Circuit breaker — process-local, no cache I/O in the decision path
# ---------------------------------------------------------------------------


def test_circuit_does_not_use_cache_in_decision(monkeypatch):
    """Sanity check on the design constraint: the breaker functions must
    not invoke any of the cache primitives. If they did, a cache outage
    would also break the breaker — the very condition the breaker exists
    to handle. This is enforced by the breaker living entirely in
    process-local globals."""
    import core.auth.session_guard as sg

    # Replace the cache primitives with sentinels that raise if called.
    def boom(*a, **kw):
        raise AssertionError('breaker must not touch the cache')

    monkeypatch.setattr(sg, 'cache_get', boom)
    monkeypatch.setattr(sg, 'cache_set', boom)

    # All breaker operations succeed without touching the sentinels.
    assert sg._is_circuit_open() is False
    sg._record_fail()
    sg._record_success()
    sg._record_fail()
    assert isinstance(sg._is_circuit_open(), bool)


def test_circuit_opens_after_threshold(monkeypatch):
    """After SESSION_VERSION_CIRCUIT_THRESHOLD consecutive failures
    within the window, the breaker opens. With a low test threshold
    we can exercise this without spinning 50 iterations."""
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(
            SESSION_VERSION_CIRCUIT_THRESHOLD=3,
            SESSION_VERSION_CIRCUIT_WINDOW=60,
            SESSION_VERSION_CIRCUIT_OPEN_DURATION=30,
        ),
    )

    assert sg._is_circuit_open() is False
    sg._record_fail()
    sg._record_fail()
    assert sg._is_circuit_open() is False, '2 fails of 3 — must NOT open yet'
    opened = sg._record_fail()
    assert opened is True
    assert sg._is_circuit_open() is True


def test_circuit_resets_on_success():
    """A successful read resets the failure counter. Transient hiccups
    don't accumulate toward the threshold — a flickering cache that
    succeeds 99% of the time should never trip the breaker."""
    import core.auth.session_guard as sg

    sg._record_fail()
    sg._record_fail()
    sg._record_success()
    # Counter back at 0 — a single new fail must not flip an artificially
    # close-to-threshold state into "open".
    assert sg._is_circuit_open() is False
    assert int(sg._circuit_state['consecutive_fails']) == 0


def test_circuit_window_resets_stale_failures(monkeypatch):
    """Failures older than SESSION_VERSION_CIRCUIT_WINDOW do NOT count.
    A cache that fails once a minute should never trip a breaker with a
    60s window and a 50-failure threshold."""
    import core.auth.session_guard as sg

    sg._record_fail()
    sg._circuit_state['last_fail_at'] = 0  # simulate old failure
    sg._record_fail()
    assert int(sg._circuit_state['consecutive_fails']) == 1, (
        'stale failure must have reset the counter; the new failure starts a fresh window'
    )


@pytest.mark.asyncio
async def test_open_circuit_forces_fail_closed(stub_audit, monkeypatch):
    """When the breaker is open, the gate denies regardless of the
    configured fail mode. ``SESSION_VERSION_FAIL_MODE = 'open'`` is the
    happy-path bypass; a sustained outage flipped to fail-closed says
    "we've been failing too long, security takes priority"."""
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(
            SESSION_VERSION_CHECK=True,
            SESSION_VERSION_FAIL_MODE='open',  # would normally allow
            SESSION_VERSION_CIRCUIT_THRESHOLD=2,
        ),
    )

    # Trip the breaker manually
    sg._record_fail()
    sg._record_fail()
    assert sg._is_circuit_open() is True

    req = FakeRequest(user_id=1, session_version=5)
    assert await sg.check_session_version(req) is False, (
        'open circuit must deny even with fail-mode=open — the breaker overrides the configured mode'
    )
    assert any(e['action'] == 'session_guard.circuit_open' for e in stub_audit)


# ---------------------------------------------------------------------------
# bump_session_version / invalidate_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bump_session_version_increments_db_and_cache(monkeypatch):
    """Happy path: bump increments the user's column and writes the new
    version to the cache so the next gated request hits cache, not DB."""
    import core.auth.session_guard as sg

    cache_writes: list[tuple[str, int, int]] = []

    async def fake_cache_set(key, value, ttl=0):
        cache_writes.append((key, value, ttl))

    class FakeUser:
        def __init__(self):
            self.session_version = 4
            self.saved_with: list[Any] = []

        async def save(self, **kw):
            self.saved_with.append(kw)

    fake_user = FakeUser()

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(fake_user)

    monkeypatch.setattr(sg, 'cache_set', fake_cache_set)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    new_v = await sg.bump_session_version(7)
    assert new_v == 5
    assert fake_user.session_version == 5
    assert fake_user.saved_with == [{'update_fields': ['session_version']}], (
        'bump must use update_fields to avoid touching unrelated columns '
        '(updated_at, etc.) — important for projects whose User has '
        'cascading post_save hooks'
    )
    assert len(cache_writes) == 1
    assert cache_writes[0][:2] == (sg._version_key(7), 5)
    assert cache_writes[0][2] > 0, 'bump must pass a positive TTL on the cache write'


@pytest.mark.asyncio
async def test_bump_session_version_raises_on_missing_user(monkeypatch):
    """A bump for a user_id that does not exist must raise — silently
    no-oping would let an admin tool think the revocation succeeded."""
    import core.auth.session_guard as sg

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(None)

    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    with pytest.raises(ValueError, match='user 999 does not exist'):
        await sg.bump_session_version(999)


@pytest.mark.asyncio
async def test_invalidate_session_audits_with_request(stub_audit, monkeypatch):
    """``invalidate_session`` is the public revocation entry point — when
    called from a request handler, an audit event must be written so the
    forensic trail captures who initiated the revocation."""
    import core.auth.session_guard as sg

    class FakeUser:
        def __init__(self):
            self.session_version = 0

        async def save(self, **kw):
            pass

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(FakeUser())

    async def fake_cache_set(key, value, ttl=0):
        return None

    monkeypatch.setattr(sg, 'cache_set', fake_cache_set)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    req = FakeRequest(user_id=42, session_version=3)
    new_v = await sg.invalidate_session(7, request=req)
    assert new_v == 1
    assert any(e['action'] == 'session.invalidated' for e in stub_audit)
    inv = next(e for e in stub_audit if e['action'] == 'session.invalidated')
    assert inv['record_id'] == '7'
    assert inv['changes'] == {'new_version': 1}


@pytest.mark.asyncio
async def test_invalidate_session_no_request_skips_audit(stub_audit, monkeypatch):
    """Background callers (CLI, scheduled cleanup) pass ``request=None``
    to opt out of the audit event — those callers are responsible for
    their own trail. The bump still happens."""
    import core.auth.session_guard as sg

    class FakeUser:
        def __init__(self):
            self.session_version = 0

        async def save(self, **kw):
            pass

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(FakeUser())

    async def fake_cache_set(key, value, ttl=0):
        return None

    monkeypatch.setattr(sg, 'cache_set', fake_cache_set)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    new_v = await sg.invalidate_session(7, request=None)
    assert new_v == 1
    assert all(e['action'] != 'session.invalidated' for e in stub_audit)


# ---------------------------------------------------------------------------
# Boot-time validation
# ---------------------------------------------------------------------------


def test_configure_no_op_when_feature_disabled(monkeypatch):
    """If SESSION_VERSION_CHECK is False/unset, the boot check is a
    pure no-op — projects that don't enable the feature should not
    have to add the field to their User model."""
    from core.auth.session_guard import configure_session_guard
    from core.conf import config

    monkeypatch.setattr(config, '_settings', SimpleNamespace())
    configure_session_guard()  # must not raise


def test_configure_raises_when_user_model_missing(monkeypatch):
    """If the feature is enabled but no User model is registered, fail
    loudly at boot — the gate cannot work without a User model and the
    project should know immediately, not at first authenticated
    request."""
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CHECK=True),
    )

    def fake_get_model(name):
        raise LookupError(f'{name} not registered')

    monkeypatch.setattr(sg, 'get_model', fake_get_model)

    with pytest.raises(RuntimeError, match='no User model is registered'):
        sg.configure_session_guard()


def test_configure_raises_when_session_version_field_missing(monkeypatch):
    """If the User model exists but lacks the session_version column,
    raise with the exact migration to apply. Loud failure is the only
    safe behavior — silently degrading would let the project ship with
    revocation broken and no signal that something is wrong."""
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CHECK=True),
    )

    class UserNoVersionField:
        _meta = SimpleNamespace(fields_map={'id': object(), 'email': object()})

    monkeypatch.setattr(sg, 'get_model', lambda name: UserNoVersionField)

    with pytest.raises(RuntimeError, match='session_version'):
        sg.configure_session_guard()


@pytest.mark.asyncio
async def test_cache_writes_respect_configurable_ttl(monkeypatch):
    """``SESSION_VERSION_CACHE_TTL`` overrides the default 60s. Lower
    values tighten the multi-worker memory staleness window at the cost
    of more DB hits; higher values trade consistency for performance on
    Redis. The default is 60s; an explicit override must reach the
    backend's ``set(key, value, ttl)`` call unchanged.
    """
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CACHE_TTL=15),
    )

    cache_writes: list[tuple[str, int, int]] = []

    async def fake_cache_set(key, value, ttl=0):
        cache_writes.append((key, value, ttl))

    class FakeUser:
        def __init__(self):
            self.session_version = 0

        async def save(self, **kw):
            pass

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(FakeUser())

    monkeypatch.setattr(sg, 'cache_set', fake_cache_set)
    monkeypatch.setattr(sg, 'get_model', lambda name: FakeUserClass)

    await sg.bump_session_version(99)
    assert cache_writes == [(sg._version_key(99), 1, 15)], (
        f'configured TTL did not propagate to cache_set; got {cache_writes}'
    )


def test_configure_passes_when_session_version_field_present(monkeypatch):
    """Feature enabled + field present → boot check passes silently."""
    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CHECK=True),
    )

    class UserWithVersion:
        _meta = SimpleNamespace(fields_map={'id': object(), 'session_version': object()})

    monkeypatch.setattr(sg, 'get_model', lambda name: UserWithVersion)

    sg.configure_session_guard()  # must not raise
