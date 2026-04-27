"""Tests for @inject() dependency injection decorator."""

from core.http.inject import inject
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Controller stubs
# ---------------------------------------------------------------------------


class _Controller:
    """Fake controller for testing @inject()."""

    @inject()
    async def with_form(self, request: Request, form: dict):
        return JSONResponse({'form': form})

    @inject()
    async def with_path_int(self, request: Request, item_id: int):
        return JSONResponse({'item_id': item_id, 'type': type(item_id).__name__})

    @inject()
    async def with_query(self, request: Request, q: str = 'default'):
        return JSONResponse({'q': q})

    @inject()
    async def with_defaults(self, request: Request, page: int = 1, limit: int = 20):
        return JSONResponse({'page': page, 'limit': limit})

    @inject()
    async def with_invalid_type(self, request: Request, num: int = 0):
        return JSONResponse({'num': num, 'type': type(num).__name__})

    @inject()
    async def with_generic_type(self, request: Request, items: list[int] = None):
        # Generic types like list[int] should NOT be coerced (passed as raw string from path/query)
        return JSONResponse({'items': items, 'type': type(items).__name__})


ctrl = _Controller()

app = Starlette(
    routes=[
        Route('/form', endpoint=ctrl.with_form, methods=['POST']),
        Route('/items/{item_id}', endpoint=ctrl.with_path_int, methods=['GET']),
        Route('/search', endpoint=ctrl.with_query, methods=['GET']),
        Route('/defaults', endpoint=ctrl.with_defaults, methods=['GET']),
        Route('/invalid/{num}', endpoint=ctrl.with_invalid_type, methods=['GET']),
        Route('/generic/{items}', endpoint=ctrl.with_generic_type, methods=['GET']),
    ]
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Form data injection
# ---------------------------------------------------------------------------


def test_inject_form_data():
    resp = client.post('/form', data={'name': 'Alice', 'age': '30'})
    assert resp.status_code == 200
    body = resp.json()
    assert body['form']['name'] == 'Alice'
    assert body['form']['age'] == '30'


def test_inject_json_body():
    resp = client.post('/form', json={'name': 'Bob', 'items': [1, 2]})
    assert resp.status_code == 200
    body = resp.json()
    assert body['form']['name'] == 'Bob'
    assert body['form']['items'] == [1, 2]


# ---------------------------------------------------------------------------
# Path params with type coercion
# ---------------------------------------------------------------------------


def test_inject_path_param_int():
    resp = client.get('/items/42')
    assert resp.status_code == 200
    body = resp.json()
    assert body['item_id'] == 42
    assert body['type'] == 'int'


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


def test_inject_query_param():
    resp = client.get('/search?q=hello')
    assert resp.status_code == 200
    assert resp.json()['q'] == 'hello'


def test_inject_query_param_missing_uses_default():
    resp = client.get('/search')
    assert resp.status_code == 200
    assert resp.json()['q'] == 'default'


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_inject_defaults_when_no_params():
    resp = client.get('/defaults')
    assert resp.status_code == 200
    body = resp.json()
    assert body['page'] == 1
    assert body['limit'] == 20


def test_inject_query_overrides_defaults():
    resp = client.get('/defaults?page=3')
    assert resp.status_code == 200
    assert resp.json()['page'] == 3


# ---------------------------------------------------------------------------
# Invalid type coercion falls back to default
# ---------------------------------------------------------------------------


def test_inject_invalid_type_falls_back_to_default():
    resp = client.get('/invalid/abc')
    assert resp.status_code == 200
    body = resp.json()
    # Should fall back to default (0) since int('abc') fails
    assert body['num'] == 0


# ---------------------------------------------------------------------------
# Malformed body returns 400
# ---------------------------------------------------------------------------


def test_inject_malformed_json_returns_400():
    """Invalid JSON body returns 400 instead of silently proceeding."""
    resp = client.post('/form', content=b'{not valid json}', headers={'Content-Type': 'application/json'})
    assert resp.status_code == 400
    assert 'error' in resp.json()


# ---------------------------------------------------------------------------
# Whitelist and Generic types
# ---------------------------------------------------------------------------


def test_inject_generic_type_not_coerced():
    """Generic types like list[int] are not coerced; raw value is passed."""
    # If coerced, it would try list[int]('1,2,3') and fail (assigning None or default)
    # Our fix ensures it stays as '1,2,3' (str)
    resp = client.get('/generic/1,2,3')
    assert resp.status_code == 200
    body = resp.json()
    assert body['items'] == '1,2,3'
    assert body['type'] == 'str'


def test_inject_non_whitelisted_primitive_not_coerced():
    """Complex or non-whitelisted types are not coerced."""

    class Custom:
        def __init__(self, val):
            self.val = val

    class DummyController:
        @inject()
        async def custom_ctrl(self, request, val: Custom):
            # type hint is Custom class, not in whitelist
            return JSONResponse({'val': str(val), 'type': type(val).__name__})

    d_ctrl = DummyController()
    app_custom = Starlette(routes=[Route('/{val}', endpoint=d_ctrl.custom_ctrl)])
    client_custom = TestClient(app_custom)

    resp = client_custom.get('/hello')
    assert resp.status_code == 200
    # Should be 'hello' (str), not a Custom object
    assert resp.json()['val'] == 'hello'
    assert resp.json()['type'] == 'str'
