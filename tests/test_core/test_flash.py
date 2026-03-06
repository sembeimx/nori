"""Tests for flash message helpers."""
from core.http.flash import flash, get_flashed_messages


class FakeRequest:
    """Minimal request stub with session dict."""
    def __init__(self):
        self.session = {}


def test_flash_adds_message():
    req = FakeRequest()
    flash(req, 'Created')
    assert len(req.session['_flash_messages']) == 1
    assert req.session['_flash_messages'][0]['message'] == 'Created'
    assert req.session['_flash_messages'][0]['category'] == 'success'


def test_flash_custom_category():
    req = FakeRequest()
    flash(req, 'Oops', 'error')
    assert req.session['_flash_messages'][0]['category'] == 'error'


def test_flash_multiple_messages():
    req = FakeRequest()
    flash(req, 'First')
    flash(req, 'Second', 'warning')
    flash(req, 'Third', 'error')
    assert len(req.session['_flash_messages']) == 3


def test_get_flashed_messages_returns_all():
    session = {'_flash_messages': [
        {'message': 'A', 'category': 'success'},
        {'message': 'B', 'category': 'error'},
    ]}
    msgs = get_flashed_messages(session)
    assert len(msgs) == 2
    assert msgs[0]['message'] == 'A'
    assert msgs[1]['message'] == 'B'


def test_get_flashed_messages_clears_after_read():
    session = {'_flash_messages': [{'message': 'A', 'category': 'success'}]}
    get_flashed_messages(session)
    # Second read should return empty
    assert get_flashed_messages(session) == []


def test_get_flashed_messages_empty_session():
    assert get_flashed_messages({}) == []


def test_flash_then_read_roundtrip():
    req = FakeRequest()
    flash(req, 'Hello')
    flash(req, 'Error', 'error')
    msgs = get_flashed_messages(req.session)
    assert len(msgs) == 2
    assert msgs[0]['message'] == 'Hello'
    assert msgs[1]['category'] == 'error'
    # Gone after read
    assert get_flashed_messages(req.session) == []
