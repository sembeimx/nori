"""Tests for core.jinja template globals."""
from core.jinja import templates


def test_csrf_field_registered_as_global():
    """csrf_field should be available in Jinja2 templates."""
    assert 'csrf_field' in templates.env.globals


def test_get_flashed_messages_registered_as_global():
    """get_flashed_messages should be available in Jinja2 templates."""
    assert 'get_flashed_messages' in templates.env.globals


def test_csrf_field_callable():
    """The registered csrf_field should be callable."""
    assert callable(templates.env.globals['csrf_field'])


def test_get_flashed_messages_callable():
    """The registered get_flashed_messages should be callable."""
    assert callable(templates.env.globals['get_flashed_messages'])
