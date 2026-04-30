"""
Meilisearch search driver for Nori.

`Meilisearch <https://www.meilisearch.com/>`_ is an open-source, self-hosted
full-text search engine with a simple REST API. It can be installed via Docker
in seconds::

    docker run -d -p 7700:7700 getmeili/meilisearch:latest

This driver communicates with Meilisearch over HTTP using ``httpx`` (already
a dependency of Nori). No additional packages are required.

Setup
-----

1. Add the following variables to your ``.env``::

       SEARCH_DRIVER=meilisearch
       MEILISEARCH_URL=http://localhost:7700
       MEILISEARCH_API_KEY=your-master-key     # optional in development

2. Register the driver at app startup (e.g. ``routes.py``)::

       from services.search_meilisearch import register
       register()

3. (Optional) Configure searchable attributes and filterable attributes
   directly in Meilisearch's dashboard or via its settings API. This driver
   does **not** manage index settings — it only indexes, searches, and
   removes documents.

Usage
-----

::

    from core.search import search, index_document, remove_document

    # Index after creating a record
    await index_document('articles', article.id, {
        'id': article.id,
        'title': article.title,
        'body': article.body,
        'status': article.status,
    })

    # Search with optional filters
    results = await search('articles', 'async python', filters={'status': 'published'})

    # Remove after deleting a record
    await remove_document('articles', article.id)

Filters
-------

The ``filters`` dict is converted to Meilisearch's filter syntax
automatically. Each key-value pair becomes ``key = "value"`` and multiple
pairs are joined with ``AND``::

    filters={'status': 'published', 'lang': 'en'}
    # → 'status = "published" AND lang = "en"'

For more complex filters (OR, numeric ranges, geo), pass a raw filter
string as a single key::

    filters={'_raw': 'status = "published" AND (lang = "en" OR lang = "es")'}
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from core.conf import config
from core.search import register_search_driver

# Meilisearch attribute names allow letters, digits, underscores, hyphens,
# and dots for nested fields. Reject anything else to prevent operator
# injection through dict keys.
_SAFE_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_.\-]*$')

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the module-level httpx client, creating it on first use.

    A single persistent client pools TCP connections to the Meilisearch
    instance across search/index/remove calls.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def shutdown() -> None:
    """Close the shared httpx client. Call from your ASGI lifespan."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _escape_value(value: Any) -> str:
    """Escape a value for inclusion inside a double-quoted Meilisearch filter.

    Meilisearch's filter syntax uses ``\\`` as the escape character inside
    quoted strings. Backslashes must be doubled and double-quotes prefixed,
    otherwise a value like ``foo" OR bar = "baz`` would close the literal
    early and inject operators.
    """
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def _build_filter_string(filters: dict[str, Any]) -> str | None:
    """Convert a filters dict to a Meilisearch filter string.

    Args:
        filters: Dict of field-value pairs. If a ``_raw`` key is present,
                 its value is used as-is (for advanced filter expressions).

    Returns:
        A filter string or ``None`` if filters is empty.

    Raises:
        ValueError: If a key is not a safe Meilisearch attribute name
                    (letters, digits, underscores, hyphens, dots only).

    Examples::

        >>> _build_filter_string({'status': 'published'})
        'status = "published"'
        >>> _build_filter_string({'status': 'published', 'lang': 'en'})
        'status = "published" AND lang = "en"'
        >>> _build_filter_string({'_raw': 'price > 10 AND price < 50'})
        'price > 10 AND price < 50'
    """
    if not filters:
        return None
    if '_raw' in filters:
        return str(filters['_raw'])
    parts = []
    for k, v in filters.items():
        if not _SAFE_KEY.match(k):
            raise ValueError(f'Unsafe filter key: {k!r}')
        parts.append(f'{k} = "{_escape_value(v)}"')
    return ' AND '.join(parts)


def _get_headers() -> dict[str, str]:
    """Build HTTP headers for Meilisearch requests.

    Returns:
        Dict with Content-Type and Authorization (if API key is set).
    """
    headers: dict[str, str] = {'Content-Type': 'application/json'}
    api_key = config.get('MEILISEARCH_API_KEY', '')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    return headers


def _get_base_url() -> str:
    """Return the Meilisearch base URL from settings.

    Defaults to ``http://localhost:7700`` if not configured.
    """
    return config.get('MEILISEARCH_URL', 'http://localhost:7700').rstrip('/')


async def _search(
    index: str,
    query: str,
    filters: dict[str, Any],
    limit: int,
    offset: int,
) -> list[dict]:
    """Execute a search query against a Meilisearch index.

    Args:
        index: Index name (e.g. ``'articles'``).
        query: Search query string.
        filters: Dict of filters — see :func:`_build_filter_string`.
        limit: Max number of results.
        offset: Number of results to skip.

    Returns:
        List of hit dicts as returned by Meilisearch.

    Raises:
        httpx.HTTPStatusError: If Meilisearch returns a non-2xx response.
    """
    base_url = _get_base_url()
    payload: dict[str, Any] = {
        'q': query,
        'limit': limit,
        'offset': offset,
    }
    filter_str = _build_filter_string(filters)
    if filter_str:
        payload['filter'] = filter_str

    client = _get_client()
    resp = await client.post(
        f'{base_url}/indexes/{index}/search',
        json=payload,
        headers=_get_headers(),
    )
    resp.raise_for_status()

    return resp.json().get('hits', [])


async def _index_document(
    index: str,
    doc_id: str | int,
    document: dict,
) -> None:
    """Add or update a single document in a Meilisearch index.

    Meilisearch uses the ``id`` field as the primary key by default. This
    function ensures the document always includes an ``id`` field set to
    ``doc_id``.

    Args:
        index: Index name.
        doc_id: Document primary key.
        document: Dict of fields to index.

    Raises:
        httpx.HTTPStatusError: If Meilisearch returns a non-2xx response.
    """
    base_url = _get_base_url()
    doc = {**document, 'id': doc_id}

    client = _get_client()
    resp = await client.post(
        f'{base_url}/indexes/{index}/documents',
        json=[doc],
        headers=_get_headers(),
    )
    resp.raise_for_status()


async def _remove_document(
    index: str,
    doc_id: str | int,
) -> None:
    """Remove a single document from a Meilisearch index.

    Args:
        index: Index name.
        doc_id: Document primary key to remove.

    Raises:
        httpx.HTTPStatusError: If Meilisearch returns a non-2xx response.
    """
    base_url = _get_base_url()

    client = _get_client()
    resp = await client.delete(
        f'{base_url}/indexes/{index}/documents/{doc_id}',
        headers=_get_headers(),
    )
    resp.raise_for_status()


def register() -> None:
    """Register the Meilisearch search driver.

    Call this once at app startup::

        from services.search_meilisearch import register
        register()
    """
    register_search_driver(
        'meilisearch',
        {
            'search': _search,
            'index_document': _index_document,
            'remove_document': _remove_document,
        },
    )
