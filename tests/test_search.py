"""Tests for core.search — multi-driver search dispatcher.

Covers:
- Driver registration (valid, missing keys)
- Driver introspection (get_search_drivers)
- search() dispatch, filters, pagination, settings fallback, override
- index_document() dispatch
- remove_document() dispatch
- Error handling (unknown driver, no driver configured)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

import importlib
import pytest
from unittest.mock import AsyncMock, patch

# Import the module object (not the function) so we can patch settings on it.
_search_mod = importlib.import_module('core.search')

from core.search import (
    search,
    index_document,
    remove_document,
    register_search_driver,
    get_search_drivers,
    _DRIVERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_driver(search_fn=None, index_fn=None, remove_fn=None):
    """Create a mock search driver dict with AsyncMock callables.

    Any callable not provided defaults to a fresh AsyncMock.
    """
    return {
        'search': search_fn or AsyncMock(return_value=[{'id': 1, 'title': 'Hit'}]),
        'index_document': index_fn or AsyncMock(),
        'remove_document': remove_fn or AsyncMock(),
    }


@pytest.fixture(autouse=True)
def _cleanup_drivers():
    """Remove any test drivers registered during a test."""
    yield
    _DRIVERS.pop('test_drv', None)
    _DRIVERS.pop('alt_drv', None)


# ---------------------------------------------------------------------------
# register_search_driver
# ---------------------------------------------------------------------------

def test_register_search_driver():
    """A valid driver with all required keys registers successfully."""
    drv = _make_driver()
    register_search_driver('test_drv', drv)
    assert 'test_drv' in _DRIVERS


def test_register_search_driver_missing_keys():
    """A driver missing some required keys raises ValueError."""
    with pytest.raises(ValueError, match="missing required keys"):
        register_search_driver('bad', {'search': AsyncMock()})


def test_register_search_driver_empty_dict():
    """An empty dict raises ValueError listing the missing keys."""
    with pytest.raises(ValueError, match="index_document"):
        register_search_driver('bad', {})


# ---------------------------------------------------------------------------
# get_search_drivers
# ---------------------------------------------------------------------------

def test_get_search_drivers_returns_set():
    """get_search_drivers() always returns a set."""
    assert isinstance(get_search_drivers(), set)


def test_get_search_drivers_after_register():
    """A registered driver appears in the returned set."""
    register_search_driver('test_drv', _make_driver())
    assert 'test_drv' in get_search_drivers()


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_search_dispatches_to_driver():
    """search() calls the driver's search callable with correct arguments."""
    mock_search = AsyncMock(return_value=[{'id': 1}])
    register_search_driver('test_drv', _make_driver(search_fn=mock_search))

    results = await search('articles', 'python', driver='test_drv')

    mock_search.assert_called_once_with('articles', 'python', {}, 20, 0)
    assert results == [{'id': 1}]


@pytest.mark.anyio
async def test_search_passes_filters_and_pagination():
    """search() forwards filters, limit, and offset to the driver."""
    mock_search = AsyncMock(return_value=[])
    register_search_driver('test_drv', _make_driver(search_fn=mock_search))

    await search(
        'products', 'laptop',
        filters={'brand': 'Nori'},
        limit=5,
        offset=10,
        driver='test_drv',
    )

    mock_search.assert_called_once_with('products', 'laptop', {'brand': 'Nori'}, 5, 10)


@pytest.mark.anyio
async def test_search_uses_settings_driver():
    """search() reads SEARCH_DRIVER from settings when driver= is omitted."""
    mock_search = AsyncMock(return_value=[])
    register_search_driver('test_drv', _make_driver(search_fn=mock_search))

    with patch.object(_search_mod, 'config') as mock_config:
        mock_config.get = lambda k, d=None: 'test_drv' if k == 'SEARCH_DRIVER' else d
        await search('idx', 'q')

    mock_search.assert_called_once()


@pytest.mark.anyio
async def test_search_driver_override():
    """Per-call driver= overrides settings.SEARCH_DRIVER."""
    mock_a = AsyncMock(return_value=[{'src': 'a'}])
    mock_b = AsyncMock(return_value=[{'src': 'b'}])
    register_search_driver('test_drv', _make_driver(search_fn=mock_a))
    register_search_driver('alt_drv', _make_driver(search_fn=mock_b))

    with patch.object(_search_mod, 'config') as mock_config:
        mock_config.get = lambda k, d=None: 'test_drv' if k == 'SEARCH_DRIVER' else d
        results = await search('idx', 'q', driver='alt_drv')

    mock_a.assert_not_called()
    mock_b.assert_called_once()
    assert results == [{'src': 'b'}]


@pytest.mark.anyio
async def test_search_unknown_driver():
    """An unknown driver raises ValueError with the driver name."""
    with pytest.raises(ValueError, match="Unknown search driver 'nope'"):
        await search('idx', 'q', driver='nope')


@pytest.mark.anyio
async def test_search_no_driver_configured():
    """Empty SEARCH_DRIVER in settings raises ValueError."""
    with patch.object(_search_mod, 'config') as mock_config:
        mock_config.get = lambda k, d=None: '' if k == 'SEARCH_DRIVER' else d
        with pytest.raises(ValueError, match="No search driver configured"):
            await search('idx', 'q')


# ---------------------------------------------------------------------------
# index_document()
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_index_document_dispatches():
    """index_document() calls the driver's index_document callable."""
    mock_index = AsyncMock()
    register_search_driver('test_drv', _make_driver(index_fn=mock_index))

    await index_document('articles', 42, {'title': 'Hello'}, driver='test_drv')

    mock_index.assert_called_once_with('articles', 42, {'title': 'Hello'})


@pytest.mark.anyio
async def test_index_document_unknown_driver():
    """An unknown driver raises ValueError."""
    with pytest.raises(ValueError, match="Unknown search driver"):
        await index_document('idx', 1, {}, driver='nope')


# ---------------------------------------------------------------------------
# remove_document()
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_remove_document_dispatches():
    """remove_document() calls the driver's remove_document callable."""
    mock_remove = AsyncMock()
    register_search_driver('test_drv', _make_driver(remove_fn=mock_remove))

    await remove_document('articles', 42, driver='test_drv')

    mock_remove.assert_called_once_with('articles', 42)


@pytest.mark.anyio
async def test_remove_document_unknown_driver():
    """An unknown driver raises ValueError."""
    with pytest.raises(ValueError, match="Unknown search driver"):
        await remove_document('idx', 1, driver='nope')
