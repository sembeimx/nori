"""Tests for ACL — require_permission decorator and load_permissions."""

import pytest
from core.auth.decorators import load_permissions, require_permission
from starlette.responses import JSONResponse

# -- Fakes -------------------------------------------------------------------


class FakeSession(dict):
    pass


class FakeHeaders(dict):
    def get(self, key, default=''):
        return super().get(key.lower(), default)


class FakeRequest:
    def __init__(self, *, user_id=None, role='user', permissions=None, accept='application/json'):
        self.session = FakeSession()
        if user_id is not None:
            self.session['user_id'] = user_id
        self.session['role'] = role
        if permissions is not None:
            self.session['permissions'] = permissions
        self.headers = FakeHeaders({'accept': accept})


class FakeController:
    @require_permission('articles.edit')
    async def edit(self, request):
        return JSONResponse({'ok': True})

    @require_permission('reports.view')
    async def view_report(self, request):
        return JSONResponse({'ok': True})


# -- require_permission -------------------------------------------------------


@pytest.mark.asyncio
async def test_no_user_returns_401():
    ctrl = FakeController()
    req = FakeRequest()
    resp = await ctrl.edit(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_no_user_html_redirects():
    ctrl = FakeController()
    req = FakeRequest(accept='text/html')
    resp = await ctrl.edit(req)
    assert resp.status_code == 302


@pytest.mark.asyncio
async def test_missing_permission_returns_403():
    ctrl = FakeController()
    req = FakeRequest(user_id=1, permissions=['articles.view'])
    resp = await ctrl.edit(req)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_has_permission_passes():
    ctrl = FakeController()
    req = FakeRequest(user_id=1, permissions=['articles.edit', 'articles.view'])
    resp = await ctrl.edit(req)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_bypasses_permission():
    ctrl = FakeController()
    req = FakeRequest(user_id=1, role='admin', permissions=[])
    resp = await ctrl.edit(req)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_empty_permissions_returns_403():
    ctrl = FakeController()
    req = FakeRequest(user_id=1, permissions=[])
    resp = await ctrl.view_report(req)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_no_permissions_key_returns_403():
    """If permissions were never loaded in session, deny access."""
    ctrl = FakeController()
    req = FakeRequest(user_id=1)
    # Explicitly remove permissions key
    req.session.pop('permissions', None)
    resp = await ctrl.edit(req)
    assert resp.status_code == 403


# -- load_permissions (DB integration) ----------------------------------------


@pytest.mark.asyncio
async def test_load_permissions_from_db():
    from models.framework.permission import Permission
    from models.framework.role import Role

    perm1, _ = await Permission.get_or_create(name='test.read', defaults={'description': 'Read test'})
    perm2, _ = await Permission.get_or_create(name='test.write', defaults={'description': 'Write test'})
    role, _ = await Role.get_or_create(name='test_role')
    await role.permissions.add(perm1, perm2)

    session = FakeSession()
    session['role_ids'] = [role.id]

    perms = await load_permissions(session, user_id=1)
    assert 'test.read' in perms
    assert 'test.write' in perms
    assert session['permissions'] == perms


@pytest.mark.asyncio
async def test_load_permissions_empty_roles():
    session = FakeSession()
    session['role_ids'] = []

    perms = await load_permissions(session, user_id=1)
    assert perms == []
    assert session['permissions'] == []


@pytest.mark.asyncio
async def test_load_permissions_sets_ttl_marker_even_with_empty_role_ids():
    """The TTL marker must be set in every branch, including the empty-
    role_ids early return. Otherwise the require_permission fail-safe
    re-triggers load_permissions on every request — at minimum a noisy
    warning storm, at worst repeated DB hits in projects that override
    load_permissions."""
    from core.auth.decorators import _PERMISSIONS_TTL_KEY

    session = FakeSession()
    session['role_ids'] = []

    await load_permissions(session, user_id=1)
    assert _PERMISSIONS_TTL_KEY in session


@pytest.mark.asyncio
async def test_require_permission_fail_safe_loads_when_session_lacks_ttl(monkeypatch):
    """If the project's login flow forgot to call load_permissions(),
    require_permission must trigger a load itself rather than leaving
    the user locked out of every permission-gated route. Marker for
    the fix: load_permissions() is called even though the session has
    no TTL key.
    """
    import core.auth.decorators as dec_mod

    calls = []

    async def fake_loader(session, user_id):
        calls.append(user_id)
        # Simulate the loader populating the session
        session['permissions'] = ['articles.edit']
        session[dec_mod._PERMISSIONS_TTL_KEY] = 9999999999.0

    monkeypatch.setattr(dec_mod, 'load_permissions', fake_loader)

    ctrl = FakeController()
    req = FakeRequest(user_id=42)
    # Important: do NOT pre-set permissions — that's the bug case.
    req.session.pop('permissions', None)

    resp = await ctrl.edit(req)
    assert calls == [42], 'fail-safe load_permissions was never invoked'
    assert resp.status_code == 200  # newly loaded perms unlocked the route


@pytest.mark.asyncio
async def test_require_permission_does_not_overwrite_manually_set_permissions(monkeypatch):
    """If the session has permissions but no TTL marker, those came from
    a manual write (OAuth callback, tests, etc.). The fail-safe must NOT
    overwrite them — doing so would silently break flows that don't go
    through load_permissions()."""
    import core.auth.decorators as dec_mod

    calls = []

    async def fake_loader(session, user_id):
        calls.append(user_id)
        session['permissions'] = []  # would clobber if invoked

    monkeypatch.setattr(dec_mod, 'load_permissions', fake_loader)

    ctrl = FakeController()
    req = FakeRequest(user_id=42, permissions=['articles.edit'])
    # No TTL marker — emulates manual session write
    assert dec_mod._PERMISSIONS_TTL_KEY not in req.session

    resp = await ctrl.edit(req)
    assert calls == [], 'fail-safe must not run when permissions are already set'
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_load_permissions_uses_role_resolver_when_role_ids_missing(monkeypatch):
    """If the project's login flow forgot to set role_ids, ROLE_RESOLVER
    (a project-supplied async callable) bridges the gap by deriving
    role_ids from the User model. Without this hook the fail-safe load
    returns [] and the user is locked for the TTL window."""
    from types import SimpleNamespace

    from core.auth.decorators import _PERMISSIONS_TTL_KEY, load_permissions
    from core.conf import config
    from models.framework.permission import Permission
    from models.framework.role import Role

    perm, _ = await Permission.get_or_create(name='articles.publish')
    role, _ = await Role.get_or_create(name='editor_role_v201')
    await role.permissions.add(perm)

    resolver_calls = []

    async def resolver(user_id):
        resolver_calls.append(user_id)
        return [role.id]

    monkeypatch.setattr(config, '_settings', SimpleNamespace(ROLE_RESOLVER=resolver))

    session = FakeSession()
    # Note: NO role_ids — emulates the bug case
    perms = await load_permissions(session, user_id=99)

    assert resolver_calls == [99]
    assert 'articles.publish' in perms
    assert session['role_ids'] == [role.id]
    assert _PERMISSIONS_TTL_KEY in session


@pytest.mark.asyncio
async def test_load_permissions_resolver_failure_does_not_crash(monkeypatch, caplog):
    """A buggy ROLE_RESOLVER must NOT take down the request — log the
    error, fall back to empty perms, set the TTL marker."""
    import logging
    from types import SimpleNamespace

    from core.auth.decorators import _PERMISSIONS_TTL_KEY, load_permissions
    from core.conf import config

    async def broken_resolver(user_id):
        raise RuntimeError('database is on fire')

    monkeypatch.setattr(config, '_settings', SimpleNamespace(ROLE_RESOLVER=broken_resolver))
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    session = FakeSession()
    with caplog.at_level(logging.ERROR, logger='nori.auth'):
        perms = await load_permissions(session, user_id=99)

    assert perms == []
    assert _PERMISSIONS_TTL_KEY in session
    assert any('ROLE_RESOLVER failed' in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_load_permissions_no_resolver_keeps_warning_path(monkeypatch):
    """When role_ids missing, ROLE_RESOLVER unset, and User model not
    registered, behavior is the pre-v1.20.1 fallback: warn + empty
    perms + TTL marker. Confirms the hybrid resolution is purely
    additive — projects with no User registered keep the v1.20.0
    fallback."""
    from types import SimpleNamespace

    from core.auth.decorators import _PERMISSIONS_TTL_KEY, load_permissions
    from core.conf import config

    monkeypatch.setattr(config, '_settings', SimpleNamespace())

    session = FakeSession()
    perms = await load_permissions(session, user_id=99)
    assert perms == []
    assert _PERMISSIONS_TTL_KEY in session


# ---------------------------------------------------------------------------
# v1.20.2 — User.roles convention fallback (zero-config)
# ---------------------------------------------------------------------------


class _FakeAwaitable:
    """Mimics a Tortoise lazy QuerySet that becomes the result on await."""

    def __init__(self, result):
        self._result = result

    def prefetch_related(self, *args):
        return self

    def __await__(self):
        async def _coro():
            return self._result

        return _coro().__await__()


@pytest.mark.asyncio
async def test_load_permissions_uses_user_roles_convention(monkeypatch):
    """Zero-config path: when role_ids missing AND ROLE_RESOLVER not
    configured, Nori falls back to ``get_model('User')`` and reads
    ``.roles`` on the user. This unblocks projects that follow the
    convention without forcing them to wire a resolver."""
    import core.auth.decorators as dec_mod
    from models.framework.permission import Permission
    from models.framework.role import Role

    perm, _ = await Permission.get_or_create(name='convention.publish')
    role, _ = await Role.get_or_create(name='convention_role_v1202')
    await role.permissions.add(perm)

    class FakeUser:
        def __init__(self, id):
            self.id = id
            self.roles = [role]

    class FakeUserClass:
        @staticmethod
        def get(*, id):
            return _FakeAwaitable(FakeUser(id))

        @staticmethod
        def get_or_none(*, id):
            # v1.31 active-user gate calls this before role resolution.
            return _FakeAwaitable(FakeUser(id))

    real_get_model = dec_mod.get_model

    def fake_get_model(name):
        if name == 'User':
            return FakeUserClass
        return real_get_model(name)

    monkeypatch.setattr(dec_mod, 'get_model', fake_get_model)

    session = FakeSession()
    perms = await load_permissions(session, user_id=99)
    assert role.id in session['role_ids']
    assert 'convention.publish' in perms


@pytest.mark.asyncio
async def test_load_permissions_resolver_takes_priority_over_convention(monkeypatch):
    """When both ROLE_RESOLVER and the User convention are available,
    the explicit resolver wins. That keeps the override semantics —
    projects that opt out of the convention shouldn't accidentally
    trigger the User lookup."""
    from types import SimpleNamespace

    import core.auth.decorators as dec_mod
    from core.conf import config
    from models.framework.permission import Permission
    from models.framework.role import Role

    resolver_perm, _ = await Permission.get_or_create(name='from.resolver')
    convention_perm, _ = await Permission.get_or_create(name='from.convention')
    resolver_role, _ = await Role.get_or_create(name='resolver_role_v1202')
    convention_role, _ = await Role.get_or_create(name='convention_role_p2')
    await resolver_role.permissions.add(resolver_perm)
    await convention_role.permissions.add(convention_perm)

    async def resolver(user_id):
        return [resolver_role.id]

    monkeypatch.setattr(config, '_settings', SimpleNamespace(ROLE_RESOLVER=resolver))

    # Convention path also wired up — must NOT win
    class FakeUser:
        def __init__(self, id):
            self.id = id
            self.roles = [convention_role]

    class FakeUserClass:
        @staticmethod
        def get(*, id):
            return _FakeAwaitable(FakeUser(id))

        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(FakeUser(id))

    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )

    session = FakeSession()
    perms = await load_permissions(session, user_id=99)
    assert 'from.resolver' in perms
    assert 'from.convention' not in perms


@pytest.mark.asyncio
async def test_load_permissions_convention_falls_through_when_user_lacks_roles(monkeypatch):
    """If the User model is registered but doesn't expose ``.roles``
    (single-role User, custom relation name, token-only auth), the
    fallback gracefully lands at warn + empty perms instead of
    crashing the request."""
    import core.auth.decorators as dec_mod
    from core.auth.decorators import _PERMISSIONS_TTL_KEY

    class UserWithoutRolesAttr:
        def __init__(self, id):
            self.id = id
            self.role_id = 5  # singular, no M2M

    class FakeUserClass:
        @staticmethod
        def get(*, id):
            return _FakeAwaitable(UserWithoutRolesAttr(id))

        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(UserWithoutRolesAttr(id))

    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )

    session = FakeSession()
    perms = await load_permissions(session, user_id=99)
    assert perms == []
    assert _PERMISSIONS_TTL_KEY in session


@pytest.mark.asyncio
async def test_load_permissions_convention_swallows_query_errors(monkeypatch):
    """Tortoise raising DoesNotExist or any other shape-dependent error
    must NOT take down the request. Log + fall through to empty perms."""
    import logging
    from types import SimpleNamespace

    import core.auth.decorators as dec_mod
    from core.auth.decorators import _PERMISSIONS_TTL_KEY
    from core.conf import config

    class FakeAwaitableExploding:
        def prefetch_related(self, *args):
            return self

        def __await__(self):
            async def _coro():
                raise RuntimeError('user 99 does not exist')

            return _coro().__await__()

    class FakeUserClass:
        @staticmethod
        def get(*, id):
            return FakeAwaitableExploding()

        @staticmethod
        def get_or_none(*, id):
            # Active-user gate (v1.31) hits the same query crash; both
            # paths must log + fall through, never propagate the
            # RuntimeError up the request.
            return FakeAwaitableExploding()

    monkeypatch.setattr(config, '_settings', SimpleNamespace())
    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    session = FakeSession()
    perms = await load_permissions(session, user_id=99)
    assert perms == []
    assert _PERMISSIONS_TTL_KEY in session


# ---------------------------------------------------------------------------
# v1.31 — active-user gate in load_permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_permissions_refuses_inactive_user(monkeypatch):
    """If ``User.is_active`` is False, the gate denies permissions
    *immediately* — no role resolution, no DB roundtrip for permissions.

    The previous behavior (pre-1.31) was that ``is_active`` lived
    entirely in the project's login flow: at login time, the project
    refused inactive users and never created the session. But once the
    session existed, deactivating the user in the DB had no effect on
    in-flight requests UNTIL the next ``PERMISSIONS_TTL`` window
    elapsed and ``load_permissions`` ran again — at which point Nori
    happily reloaded role-based permissions for the now-inactive user
    because the function never consulted ``is_active``. This gate
    closes the **refresh** path; truly revoking a logged-in user's
    access still requires invalidating their session, since the cached
    perms on the session itself are not consulted by this gate.
    """
    import core.auth.decorators as dec_mod
    from core.auth.decorators import _PERMISSIONS_TTL_KEY

    class InactiveUser:
        def __init__(self, id):
            self.id = id
            self.is_active = False
            self.roles = []  # would otherwise resolve to perms — must NOT

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(InactiveUser(id))

    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )

    session = FakeSession()
    session['role_ids'] = [1, 2]  # would normally yield perms
    perms = await load_permissions(session, user_id=99)

    assert perms == []
    assert session['permissions'] == []
    assert _PERMISSIONS_TTL_KEY in session


@pytest.mark.asyncio
async def test_load_permissions_refuses_missing_user(monkeypatch):
    """If ``User.get_or_none(id=user_id)`` returns ``None`` (the row
    no longer exists — hard-deleted user, foreign session id), deny
    permissions immediately. Without this, a stale session for a
    purged user would keep rehydrating perms via ``role_ids`` from
    the session itself.
    """
    import core.auth.decorators as dec_mod
    from core.auth.decorators import _PERMISSIONS_TTL_KEY

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(None)

    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )

    session = FakeSession()
    session['role_ids'] = [1, 2]
    perms = await load_permissions(session, user_id=99)

    assert perms == []
    assert _PERMISSIONS_TTL_KEY in session


@pytest.mark.asyncio
async def test_load_permissions_active_user_passes_through_gate(monkeypatch):
    """The gate is a denial channel — an active user must pass
    through unchanged, with role resolution and permission load
    proceeding as in v1.30.x.
    """
    import core.auth.decorators as dec_mod
    from models.framework.permission import Permission
    from models.framework.role import Role

    perm, _ = await Permission.get_or_create(name='gate.passthrough')
    role, _ = await Role.get_or_create(name='gate_role_v131')
    await role.permissions.add(perm)

    class ActiveUser:
        def __init__(self, id):
            self.id = id
            self.is_active = True

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(ActiveUser(id))

    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )

    session = FakeSession()
    session['role_ids'] = [role.id]
    perms = await load_permissions(session, user_id=99)
    assert 'gate.passthrough' in perms


@pytest.mark.asyncio
async def test_load_permissions_user_without_is_active_attr_passes(monkeypatch):
    """Backward compatibility: small internal apps without an
    ``is_active`` deactivation column on the User must continue to
    work. ``getattr(user_obj, 'is_active', True)`` defaults to True
    when the field is absent, so the gate becomes a no-op for those
    project shapes.
    """
    import core.auth.decorators as dec_mod
    from models.framework.permission import Permission
    from models.framework.role import Role

    perm, _ = await Permission.get_or_create(name='no_is_active.publish')
    role, _ = await Role.get_or_create(name='no_is_active_role_v131')
    await role.permissions.add(perm)

    class UserNoIsActive:
        def __init__(self, id):
            self.id = id
            # No ``is_active`` attribute at all.

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            return _FakeAwaitable(UserNoIsActive(id))

    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )

    session = FakeSession()
    session['role_ids'] = [role.id]
    perms = await load_permissions(session, user_id=99)
    assert 'no_is_active.publish' in perms


@pytest.mark.asyncio
async def test_load_permissions_skips_gate_when_user_model_unregistered(monkeypatch):
    """Token-only auth and projects that haven't registered ``User``
    must pass through the gate silently. ``LookupError`` from
    ``get_model('User')`` is the documented "no User registered"
    signal — the gate must not turn it into a 500 or block the rest
    of the function.
    """
    import core.auth.decorators as dec_mod
    from core.auth.decorators import _PERMISSIONS_TTL_KEY

    real_get_model = dec_mod.get_model

    def fake_get_model(name):
        if name == 'User':
            raise LookupError('User model not registered')
        return real_get_model(name)

    monkeypatch.setattr(dec_mod, 'get_model', fake_get_model)

    session = FakeSession()
    session['role_ids'] = []  # nothing to resolve; lands at empty perms
    perms = await load_permissions(session, user_id=99)
    assert perms == []
    assert _PERMISSIONS_TTL_KEY in session


# ---------------------------------------------------------------------------
# v1.33 — session-version guard integration with auth decorators
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_required_denies_when_session_version_revoked(monkeypatch):
    """End-to-end: with the feature enabled and the cache reporting a
    higher live version than the session carries, ``login_required``
    must return 401 (or redirect for HTML). Pre-1.33 there was no
    revocation channel — a stolen cookie kept full access until
    expiry."""
    from types import SimpleNamespace

    import core.auth.session_guard as sg
    from core.auth.decorators import login_required
    from core.conf import config
    from starlette.responses import JSONResponse

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CHECK=True),
    )
    sg._reset_circuit()

    async def fake_cache_get(key):
        return 99  # admin bumped the version

    monkeypatch.setattr(sg, 'cache_get', fake_cache_get)
    monkeypatch.setattr(sg, 'audit', lambda *a, **kw: None)

    class FakeController:
        @login_required
        async def me(self, request):
            return JSONResponse({'ok': True})

    req = FakeRequest(user_id=1)
    req.session['session_version'] = 5  # stale

    resp = await FakeController().me(req)
    assert resp.status_code == 401, (
        'login_required must deny when session_version is stale; '
        'pre-1.33 it would have returned 200 for the duration of the cookie'
    )


@pytest.mark.asyncio
async def test_require_permission_denies_when_session_revoked(monkeypatch):
    """The session-version gate runs BEFORE the permission check —
    revoking a session yanks access to every gated route, including
    permission-gated ones, in the same request. Without this ordering
    a revoked admin could still hit privileged endpoints between the
    bump and the cookie's expiry."""
    from types import SimpleNamespace

    import core.auth.session_guard as sg
    from core.conf import config

    monkeypatch.setattr(
        config,
        '_settings',
        SimpleNamespace(SESSION_VERSION_CHECK=True, SUPERUSER_ROLE='admin'),
    )
    sg._reset_circuit()

    async def fake_cache_get(key):
        return 99  # admin bumped the version

    monkeypatch.setattr(sg, 'cache_get', fake_cache_get)
    monkeypatch.setattr(sg, 'audit', lambda *a, **kw: None)

    ctrl = FakeController()
    req = FakeRequest(user_id=1, permissions=['articles.edit'])
    req.session['session_version'] = 5  # stale

    resp = await ctrl.edit(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_load_permissions_gate_query_error_falls_through(monkeypatch, caplog):
    """If ``User.get_or_none`` itself raises (transient DB error,
    custom Manager that doesn't expose the method), the gate must
    log and fall through — never propagate the exception up to the
    request handler. Otherwise a brief DB blip in the gate path would
    500 every gated route while the rest of the app served fine.
    """
    import logging

    import core.auth.decorators as dec_mod
    from core.auth.decorators import _PERMISSIONS_TTL_KEY

    class FakeUserClass:
        @staticmethod
        def get_or_none(*, id):
            raise RuntimeError('transient: connection reset')

    real_get_model = dec_mod.get_model
    monkeypatch.setattr(
        dec_mod,
        'get_model',
        lambda name: FakeUserClass if name == 'User' else real_get_model(name),
    )
    monkeypatch.setattr(logging.getLogger('nori'), 'propagate', True)

    session = FakeSession()
    with caplog.at_level(logging.WARNING, logger='nori.auth'):
        perms = await load_permissions(session, user_id=99)
    assert perms == []
    assert _PERMISSIONS_TTL_KEY in session
    assert any('Active-user gate query failed' in r.getMessage() for r in caplog.records)
