from __future__ import annotations

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

from typing import Any

import httpx

import settings
from core.search import register_search_driver


def _build_filter_string(filters: dict[str, Any]) -> str | None:
    """Convert a filters dict to a Meilisearch filter string.

    Args:
        filters: Dict of field-value pairs. If a ``_raw`` key is present,
                 its value is used as-is (for advanced filter expressions).

    Returns:
        A filter string or ``None`` if filters is empty.

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
    parts = [f'{k} = "{v}"' for k, v in filters.items()]
    return ' AND '.join(parts)


def _get_headers() -> dict[str, str]:
    """Build HTTP headers for Meilisearch requests.

    Returns:
        Dict with Content-Type and Authorization (if API key is set).
    """
    headers: dict[str, str] = {'Content-Type': 'application/json'}
    api_key = getattr(settings, 'MEILISEARCH_API_KEY', '')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    return headers


def _get_base_url() -> str:
    """Return the Meilisearch base URL from settings.

    Defaults to ``http://localhost:7700`` if not configured.
    """
    return getattr(settings, 'MEILISEARCH_URL', 'http://localhost:7700').rstrip('/')


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

    async with httpx.AsyncClient() as client:
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

    async with httpx.AsyncClient() as client:
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

    async with httpx.AsyncClient() as client:
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
    register_search_driver('meilisearch', {
        'search': _search,
        'index_document': _index_document,
        'remove_document': _remove_document,
    })
