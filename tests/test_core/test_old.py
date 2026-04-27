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
