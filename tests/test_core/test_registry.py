"""Tests for core.registry — model registry."""

from __future__ import annotations

import pytest
from core.registry import _models, get_model, get_registered_models, register_model


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot and restore the registry around each test."""
    snapshot = dict(_models)
    yield
    _models.clear()
    _models.update(snapshot)


class FakeModel:
    pass


class AnotherModel:
    pass


def test_register_and_get():
    register_model('Fake', FakeModel)
    assert get_model('Fake') is FakeModel


def test_get_unregistered_raises():
    with pytest.raises(LookupError, match="'Nope' not registered"):
        get_model('Nope')


def test_register_overwrites():
    register_model('Thing', FakeModel)
    register_model('Thing', AnotherModel)
    assert get_model('Thing') is AnotherModel


def test_get_registered_models_returns_copy():
    register_model('A', FakeModel)
    result = get_registered_models()
    assert 'A' in result
    result.pop('A')
    # Original registry should be unaffected
    assert get_model('A') is FakeModel


def test_builtin_models_registered():
    """Framework models are registered at startup via models/__init__.py."""
    assert get_model('AuditLog') is not None
    assert get_model('Job') is not None
    assert get_model('Permission') is not None
    assert get_model('Role') is not None
