"""Tests for the form-value re-population helper (core.http.old)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.http.old import _old_value, flash_old


class _Session(dict):
    pass


@pytest.fixture
def request_obj():
    req = MagicMock()
    req.session = _Session()
    return req


# ---------------------------------------------------------------------------
# flash_old
# ---------------------------------------------------------------------------


def test_flash_old_stores_form_values_in_session(request_obj):
    flash_old(request_obj, {'email': 'ada@example.com', 'name': 'Ada'})

    assert request_obj.session['_old'] == {
        'email': 'ada@example.com',
        'name': 'Ada',
    }


def test_flash_old_excludes_password_fields_by_default(request_obj):
    flash_old(
        request_obj,
        {
            'email': 'ada@example.com',
            'password': 'secret123',
            'password_confirmation': 'secret123',
            'current_password': 'oldpass',
        },
    )

    stored = request_obj.session['_old']
    assert 'email' in stored
    assert 'password' not in stored
    assert 'password_confirmation' not in stored
    assert 'current_password' not in stored


def test_flash_old_custom_exclude_replaces_default(request_obj):
    flash_old(
        request_obj,
        {'email': 'ada@example.com', 'password': 'secret', 'token': 'abc'},
        exclude=('token',),
    )

    stored = request_obj.session['_old']
    # custom exclude — password is no longer hidden because we replaced the list
    assert stored == {'email': 'ada@example.com', 'password': 'secret'}


def test_flash_old_empty_exclude_keeps_everything(request_obj):
    flash_old(
        request_obj,
        {'email': 'ada@example.com', 'password': 'secret'},
        exclude=(),
    )

    stored = request_obj.session['_old']
    assert stored == {'email': 'ada@example.com', 'password': 'secret'}


def test_flash_old_overwrites_previous_flash(request_obj):
    flash_old(request_obj, {'email': 'first@example.com'})
    flash_old(request_obj, {'email': 'second@example.com'})

    assert request_obj.session['_old'] == {'email': 'second@example.com'}


# ---------------------------------------------------------------------------
# Multipart / UploadFile — JSON serialization regression (HIGH)
# ---------------------------------------------------------------------------


class _FakeUploadFile:
    """Mimics Starlette's ``UploadFile`` shape: ``filename`` + ``read``."""

    def __init__(self, filename: str = 'avatar.png') -> None:
        self.filename = filename

    async def read(self, _size: int = -1) -> bytes:  # pragma: no cover — never called
        return b''


def test_flash_old_drops_uploaded_files_before_session_write(request_obj):
    """Form has a file input + a text input + validation fails → flash_old
    must not put the UploadFile into ``request.session``.

    Pre-1.25 the helper kept the UploadFile and the cookie-backed
    SessionMiddleware then crashed the response with
    ``TypeError: Object of type UploadFile is not JSON serializable``
    on the next ``json.dumps(session)``. Every multipart form with a
    failing validation became a 500 after this function ran.
    """
    form = {
        'title': 'My article',
        'avatar': _FakeUploadFile('avatar.png'),
    }

    flash_old(request_obj, form)

    stored = request_obj.session['_old']
    assert stored == {'title': 'My article'}, (
        'flash_old leaked an UploadFile into the session — cookie-backed '
        'SessionMiddleware will crash json.dumps on the next response.'
    )


def test_flash_old_session_payload_is_json_serializable(request_obj):
    """End-to-end guard: whatever ``flash_old`` writes must round-trip
    through ``json.dumps`` so the cookie-backed SessionMiddleware can
    serialise the session on response. This is the actual failure mode
    the fix addresses, and asserting it directly keeps the regression
    test honest even if the duck-typing heuristic above ever needs to
    change.
    """
    import json

    form = {
        'title': 'My article',
        'avatar': _FakeUploadFile('avatar.png'),
        'tags': 'python,web',
    }

    flash_old(request_obj, form)

    json.dumps(request_obj.session['_old'])


# ---------------------------------------------------------------------------
# _old_value (the read path)
# ---------------------------------------------------------------------------


def test_old_value_returns_stored_field():
    session = {'_old': {'email': 'ada@example.com'}}
    assert _old_value(session, 'email') == 'ada@example.com'


def test_old_value_returns_default_when_field_missing():
    session = {'_old': {'email': 'ada@example.com'}}
    assert _old_value(session, 'name', default='Anonymous') == 'Anonymous'


def test_old_value_returns_default_when_session_has_no_flash():
    session = {}
    assert _old_value(session, 'email', default='') == ''


def test_old_value_default_is_empty_string():
    assert _old_value({}, 'anything') == ''


# ---------------------------------------------------------------------------
# Jinja global integration
# ---------------------------------------------------------------------------


def test_old_jinja_global_reads_from_request_in_context():
    """The @pass_context-decorated `old` reads request.session via ctx."""
    from core.http.old import old

    request = MagicMock()
    request.session = {'_old': {'email': 'ada@example.com'}}
    ctx = {'request': request}

    # Call the wrapped function via its Jinja context interface
    assert old(ctx, 'email') == 'ada@example.com'
    assert old(ctx, 'missing', 'fallback') == 'fallback'


def test_old_jinja_global_returns_default_when_no_request_in_context():
    from core.http.old import old

    assert old({}, 'email', 'fallback') == 'fallback'
