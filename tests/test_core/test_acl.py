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
