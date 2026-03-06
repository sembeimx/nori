"""Tests for auth decorators: login_required, require_role, require_any_role."""
import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from core.auth.decorators import login_required, require_role, require_any_role


# ---------------------------------------------------------------------------
# Controller stubs
# ---------------------------------------------------------------------------

class _Controller:

    @login_required
    async def protected(self, request: Request):
        return JSONResponse({'user_id': request.session.get('user_id')})

    @require_role('editor')
    async def editor_only(self, request: Request):
        return JSONResponse({'role': request.session.get('role')})

    @require_any_role('editor', 'moderator')
    async def multi_role(self, request: Request):
        return JSONResponse({'ok': True})


ctrl = _Controller()

app = Starlette(
    routes=[
        Route('/protected', endpoint=ctrl.protected, methods=['GET']),
        Route('/editor', endpoint=ctrl.editor_only, methods=['GET']),
        Route('/multi', endpoint=ctrl.multi_role, methods=['GET']),
    ],
    middleware=[
        Middleware(SessionMiddleware, secret_key='test-secret'),
    ],
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_session(resp_or_client, data: dict):
    """Inject session data by exploiting Starlette's signed cookie."""
    # Use the app's session middleware to set values via a helper route
    pass


# Since we can't easily inject session data externally, we test via
# the Accept header behavior (JSON returns 401, HTML returns redirect)

# ---------------------------------------------------------------------------
# @login_required
# ---------------------------------------------------------------------------

def test_login_required_json_returns_401():
    resp = client.get('/protected', headers={'accept': 'application/json'})
    assert resp.status_code == 401
    assert resp.json()['error'] == 'Unauthorized'


def test_login_required_html_redirects_to_login():
    resp = client.get('/protected', headers={'accept': 'text/html'},
                      follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['location']


# ---------------------------------------------------------------------------
# @require_role
# ---------------------------------------------------------------------------

def test_require_role_json_returns_401_without_session():
    resp = client.get('/editor', headers={'accept': 'application/json'})
    assert resp.status_code == 401


def test_require_role_html_redirects_without_session():
    resp = client.get('/editor', headers={'accept': 'text/html'},
                      follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['location']


# ---------------------------------------------------------------------------
# @require_any_role
# ---------------------------------------------------------------------------

def test_require_any_role_json_returns_401_without_session():
    resp = client.get('/multi', headers={'accept': 'application/json'})
    assert resp.status_code == 401


def test_require_any_role_html_redirects_without_session():
    resp = client.get('/multi', headers={'accept': 'text/html'},
                      follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['location']


# ---------------------------------------------------------------------------
# E2E with session: use internal Starlette test helpers
# ---------------------------------------------------------------------------

def test_login_required_passes_with_session():
    """Simulate setting session by adding a route that sets it."""
    from starlette.routing import Route as R

    async def set_session(request: Request):
        request.session['user_id'] = 42
        return JSONResponse({'ok': True})

    test_app = Starlette(
        routes=[
            R('/set', endpoint=set_session, methods=['GET']),
            R('/protected', endpoint=ctrl.protected, methods=['GET']),
        ],
        middleware=[Middleware(SessionMiddleware, secret_key='test-secret')],
    )
    tc = TestClient(test_app)
    # Set session
    tc.get('/set')
    # Now access protected route (session cookie carried)
    resp = tc.get('/protected', headers={'accept': 'application/json'})
    assert resp.status_code == 200
    assert resp.json()['user_id'] == 42


def test_require_role_passes_for_matching_role():
    async def set_session(request: Request):
        request.session['user_id'] = 1
        request.session['role'] = 'editor'
        return JSONResponse({'ok': True})

    test_app = Starlette(
        routes=[
            Route('/set', endpoint=set_session, methods=['GET']),
            Route('/editor', endpoint=ctrl.editor_only, methods=['GET']),
        ],
        middleware=[Middleware(SessionMiddleware, secret_key='test-secret')],
    )
    tc = TestClient(test_app)
    tc.get('/set')
    resp = tc.get('/editor', headers={'accept': 'application/json'})
    assert resp.status_code == 200
    assert resp.json()['role'] == 'editor'


def test_require_role_passes_for_admin():
    async def set_session(request: Request):
        request.session['user_id'] = 1
        request.session['role'] = 'admin'
        return JSONResponse({'ok': True})

    test_app = Starlette(
        routes=[
            Route('/set', endpoint=set_session, methods=['GET']),
            Route('/editor', endpoint=ctrl.editor_only, methods=['GET']),
        ],
        middleware=[Middleware(SessionMiddleware, secret_key='test-secret')],
    )
    tc = TestClient(test_app)
    tc.get('/set')
    resp = tc.get('/editor', headers={'accept': 'application/json'})
    assert resp.status_code == 200


def test_require_role_rejects_wrong_role():
    async def set_session(request: Request):
        request.session['user_id'] = 1
        request.session['role'] = 'viewer'
        return JSONResponse({'ok': True})

    test_app = Starlette(
        routes=[
            Route('/set', endpoint=set_session, methods=['GET']),
            Route('/editor', endpoint=ctrl.editor_only, methods=['GET']),
        ],
        middleware=[Middleware(SessionMiddleware, secret_key='test-secret')],
    )
    tc = TestClient(test_app)
    tc.get('/set')
    resp = tc.get('/editor', headers={'accept': 'application/json'})
    assert resp.status_code == 403


def test_require_any_role_passes_for_moderator():
    async def set_session(request: Request):
        request.session['user_id'] = 1
        request.session['role'] = 'moderator'
        return JSONResponse({'ok': True})

    test_app = Starlette(
        routes=[
            Route('/set', endpoint=set_session, methods=['GET']),
            Route('/multi', endpoint=ctrl.multi_role, methods=['GET']),
        ],
        middleware=[Middleware(SessionMiddleware, secret_key='test-secret')],
    )
    tc = TestClient(test_app)
    tc.get('/set')
    resp = tc.get('/multi', headers={'accept': 'application/json'})
    assert resp.status_code == 200
