"""Tests for core.conf — config provider."""
from __future__ import annotations

import types

import pytest
from core.conf import _Config


def _make_settings(**kwargs) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kwargs)


def test_get_returns_default_when_unconfigured():
    cfg = _Config()
    assert cfg.get('ANYTHING', 'fallback') == 'fallback'


def test_get_returns_value_after_configure():
    cfg = _Config()
    cfg.configure(_make_settings(SECRET_KEY='abc'))
    assert cfg.get('SECRET_KEY') == 'abc'


def test_get_returns_default_for_missing_key():
    cfg = _Config()
    cfg.configure(_make_settings(SECRET_KEY='abc'))
    assert cfg.get('NONEXISTENT', 42) == 42


def test_attribute_access():
    cfg = _Config()
    cfg.configure(_make_settings(DEBUG=True))
    assert cfg.DEBUG is True


def test_attribute_access_raises_when_unconfigured():
    cfg = _Config()
    with pytest.raises(RuntimeError, match='not initialised'):
        _ = cfg.SECRET_KEY


def test_attribute_access_raises_for_missing_key():
    cfg = _Config()
    cfg.configure(_make_settings(DEBUG=True))
    with pytest.raises(AttributeError, match="'NOPE'"):
        _ = cfg.NOPE


def test_is_configured():
    cfg = _Config()
    assert cfg.is_configured is False
    cfg.configure(_make_settings())
    assert cfg.is_configured is True


def test_configure_replaces_previous():
    cfg = _Config()
    cfg.configure(_make_settings(VAL='first'))
    cfg.configure(_make_settings(VAL='second'))
    assert cfg.get('VAL') == 'second'
