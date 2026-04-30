"""Tests for services.search_meilisearch — Meilisearch driver.

Covers the pure filter-string builder (synchronous) plus the HTTP-call
paths (search, index_document, remove_document) and config getters,
using AsyncMock to stand in for httpx.AsyncClient. Same pattern used
by tests/test_oauth_google.py and tests/test_core/test_service_storage_*.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from services.search_meilisearch import (
    _build_filter_string,
    _get_base_url,
    _get_headers,
    _index_document,
    _remove_document,
    _search,
    register,
)


def test_build_filter_string_empty():
    """Empty filters dict returns None (no filter applied)."""
    assert _build_filter_string({}) is None


def test_build_filter_string_single():
    """A single key-value pair becomes 'key = \"value\"'."""
    assert _build_filter_string({'status': 'published'}) == 'status = "published"'


def test_build_filter_string_multiple():
    """Multiple key-value pairs are joined with AND."""
    result = _build_filter_string({'status': 'published', 'lang': 'en'})
    assert 'status = "published"' in result
    assert 'lang = "en"' in result
    assert ' AND ' in result


def test_build_filter_string_raw():
    """The _raw key passes the value through as-is for advanced expressions."""
    raw = 'price > 10 AND price < 50'
    assert _build_filter_string({'_raw': raw}) == raw


def test_build_filter_string_escapes_double_quote_in_value():
    """A double-quote in a value must be escaped so it cannot close the literal."""
    assert _build_filter_string({'title': 'say "hi"'}) == 'title = "say \\"hi\\""'


def test_build_filter_string_escapes_backslash_in_value():
    """A backslash in a value must be doubled — it is the escape character."""
    assert _build_filter_string({'path': 'a\\b'}) == 'path = "a\\\\b"'


def test_build_filter_string_neutralizes_injection_attempt():
    """An attacker-controlled value attempting to break out of the literal is
    rendered as plain text inside the quoted value, not as filter syntax."""
    payload = 'Electronics" OR status = "private'
    result = _build_filter_string({'category': payload})
    # Both injected double-quotes are escaped, so the entire payload sits
    # inside one quoted literal that Meilisearch will treat as a single string.
    assert result == 'category = "Electronics\\" OR status = \\"private"'


def test_build_filter_string_allows_nested_attribute_keys():
    """Meilisearch supports dot notation for nested fields."""
    assert _build_filter_string({'metadata.author': 'ana'}) == 'metadata.author = "ana"'


def test_build_filter_string_rejects_unsafe_key_with_quote():
    with pytest.raises(ValueError, match='Unsafe filter key'):
        _build_filter_string({'category" OR x': 'evil'})


def test_build_filter_string_rejects_unsafe_key_with_space():
    with pytest.raises(ValueError, match='Unsafe filter key'):
        _build_filter_string({'foo bar': 'x'})


def test_build_filter_string_accepts_numeric_value():
    """Non-string values are str-cast then escaped; behavior unchanged."""
    assert _build_filter_string({'count': 42}) == 'count = "42"'


# ---------------------------------------------------------------------------
# _get_headers
# ---------------------------------------------------------------------------


def test_get_headers_without_api_key():
    """Without MEILISEARCH_API_KEY set, only Content-Type is included."""
    with patch('services.search_meilisearch.config') as mock_config:
        mock_config.get.return_value = ''
        headers = _get_headers()
    assert headers == {'Content-Type': 'application/json'}


def test_get_headers_with_api_key():
    """When MEILISEARCH_API_KEY is set, Authorization: Bearer is added."""
    with patch('services.search_meilisearch.config') as mock_config:
        mock_config.get.return_value = 'secret-key'
        headers = _get_headers()
    assert headers['Content-Type'] == 'application/json'
    assert headers['Authorization'] == 'Bearer secret-key'


# ---------------------------------------------------------------------------
# _get_base_url
# ---------------------------------------------------------------------------


def test_get_base_url_default():
    """Defaults to localhost:7700 when MEILISEARCH_URL is not configured."""
    with patch('services.search_meilisearch.config') as mock_config:
        mock_config.get.return_value = 'http://localhost:7700'
        assert _get_base_url() == 'http://localhost:7700'


def test_get_base_url_strips_trailing_slash():
    """Trailing slashes are stripped to avoid double-slashed paths."""
    with patch('services.search_meilisearch.config') as mock_config:
        mock_config.get.return_value = 'https://search.example.com/'
        assert _get_base_url() == 'https://search.example.com'


# ---------------------------------------------------------------------------
# _search
# ---------------------------------------------------------------------------


def _make_async_client(json_payload):
    """Build an AsyncMock that simulates httpx.AsyncClient as a context manager."""
    response = MagicMock()
    response.json.return_value = json_payload
    response.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post.return_value = response
    client.delete.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client, response


@pytest.mark.asyncio
async def test_search_posts_to_meilisearch_and_returns_hits():
    client, _ = _make_async_client({'hits': [{'id': 1, 'title': 'Hit'}], 'estimatedTotalHits': 1})

    with (
        patch('services.search_meilisearch.config') as mock_config,
        patch('services.search_meilisearch.httpx.AsyncClient', return_value=client),
    ):
        mock_config.get.return_value = 'http://localhost:7700'
        results = await _search('articles', 'async python', filters={}, limit=10, offset=0)

    assert results == [{'id': 1, 'title': 'Hit'}]
    call = client.post.call_args
    assert call[0][0] == 'http://localhost:7700/indexes/articles/search'
    assert call[1]['json']['q'] == 'async python'
    assert call[1]['json']['limit'] == 10
    assert call[1]['json']['offset'] == 0
    assert 'filter' not in call[1]['json']  # no filters → no filter key


@pytest.mark.asyncio
async def test_search_passes_filter_string_when_filters_present():
    client, _ = _make_async_client({'hits': []})

    with (
        patch('services.search_meilisearch.config') as mock_config,
        patch('services.search_meilisearch.httpx.AsyncClient', return_value=client),
    ):
        mock_config.get.return_value = 'http://localhost:7700'
        await _search('articles', 'q', filters={'status': 'published'}, limit=20, offset=5)

    payload = client.post.call_args[1]['json']
    assert payload['filter'] == 'status = "published"'


@pytest.mark.asyncio
async def test_search_returns_empty_list_when_no_hits_key():
    """If Meilisearch's response omits the 'hits' key, return [] (not raise)."""
    client, _ = _make_async_client({'estimatedTotalHits': 0})  # no 'hits'

    with (
        patch('services.search_meilisearch.config') as mock_config,
        patch('services.search_meilisearch.httpx.AsyncClient', return_value=client),
    ):
        mock_config.get.return_value = 'http://localhost:7700'
        results = await _search('articles', 'q', filters={}, limit=10, offset=0)

    assert results == []


# ---------------------------------------------------------------------------
# _index_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_document_posts_array_with_doc_id_field():
    client, response = _make_async_client({})

    with (
        patch('services.search_meilisearch.config') as mock_config,
        patch('services.search_meilisearch.httpx.AsyncClient', return_value=client),
    ):
        mock_config.get.return_value = 'http://localhost:7700'
        await _index_document('articles', 42, {'title': 'Hello', 'body': 'World'})

    call = client.post.call_args
    assert call[0][0] == 'http://localhost:7700/indexes/articles/documents'
    sent = call[1]['json']
    assert isinstance(sent, list) and len(sent) == 1
    assert sent[0]['id'] == 42
    assert sent[0]['title'] == 'Hello'
    assert sent[0]['body'] == 'World'
    response.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_index_document_overrides_id_in_document():
    """Even if the document has its own id, doc_id takes precedence."""
    client, _ = _make_async_client({})

    with (
        patch('services.search_meilisearch.config') as mock_config,
        patch('services.search_meilisearch.httpx.AsyncClient', return_value=client),
    ):
        mock_config.get.return_value = 'http://localhost:7700'
        await _index_document('articles', 99, {'id': 1, 'title': 'X'})

    sent = client.post.call_args[1]['json']
    assert sent[0]['id'] == 99


# ---------------------------------------------------------------------------
# _remove_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_document_deletes_by_id():
    client, response = _make_async_client({})

    with (
        patch('services.search_meilisearch.config') as mock_config,
        patch('services.search_meilisearch.httpx.AsyncClient', return_value=client),
    ):
        mock_config.get.return_value = 'http://localhost:7700'
        await _remove_document('articles', 42)

    call = client.delete.call_args
    assert call[0][0] == 'http://localhost:7700/indexes/articles/documents/42'
    response.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def test_register_wires_search_index_remove_callables():
    """register() must register the driver under the 'meilisearch' name."""
    from core.search import _DRIVERS, get_search_drivers

    _DRIVERS.pop('meilisearch', None)  # ensure clean slate
    register()
    try:
        assert 'meilisearch' in get_search_drivers()
        assert _DRIVERS['meilisearch']['search'] is _search
        assert _DRIVERS['meilisearch']['index_document'] is _index_document
        assert _DRIVERS['meilisearch']['remove_document'] is _remove_document
    finally:
        _DRIVERS.pop('meilisearch', None)
