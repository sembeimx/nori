"""
Multi-driver search dispatcher for full-text search.

Nori's search module provides a thin, driver-based abstraction for indexing
and searching documents. The core ships with **no built-in driver** — search
is inherently an external concern (Meilisearch, Typesense, Algolia, etc.) and
each provider lives in ``services/`` as a plug-in, keeping the core clean.

Quick start
-----------

1. Register a driver (e.g. in ``routes.py`` or app startup)::

       from services.search_meilisearch import register
       register()

2. Set the env var::

       SEARCH_DRIVER=meilisearch

3. Use the public API from any controller::

       from core.search import search, index_document, remove_document

       # Index a document (usually after create/update in your controller)
       await index_document('articles', article.id, article.to_dict())

       # Search
       results = await search('articles', 'async python', filters={'status': 'published'})

       # Remove from index (usually after delete in your controller)
       await remove_document('articles', article.id)

Driver contract
---------------

A search driver is a dict (or object) that provides **three** async callables::

    {
        'search':          async def(index, query, filters, limit, offset) -> list[dict],
        'index_document':  async def(index, doc_id, document) -> None,
        'remove_document': async def(index, doc_id) -> None,
    }

Each callable receives only simple, serializable arguments — no framework
objects, no ORM models. This makes drivers easy to write and test.

Register your driver with :func:`register_search_driver` and you're done.
See ``services/search_meilisearch.py`` for a complete example.
"""

from __future__ import annotations

from typing import Any, Callable

from core.conf import config
from core.logger import get_logger

_log = get_logger('search')

# ---------------------------------------------------------------------------
# Driver registry
# ---------------------------------------------------------------------------

_DRIVERS: dict[str, dict[str, Callable]] = {}


def register_search_driver(name: str, driver: dict[str, Callable]) -> None:
    """Register a custom search driver.

    Args:
        name: Unique driver name (e.g. ``'meilisearch'``, ``'typesense'``).
        driver: A dict with three keys, each mapping to an async callable:

            - ``'search'``: ``async def(index: str, query: str, filters: dict,
              limit: int, offset: int) -> list[dict]``
            - ``'index_document'``: ``async def(index: str, doc_id: str | int,
              document: dict) -> None``
            - ``'remove_document'``: ``async def(index: str, doc_id: str | int)
              -> None``

    Raises:
        ValueError: If the driver dict is missing required keys.

    Example::

        register_search_driver('meilisearch', {
            'search': my_search_fn,
            'index_document': my_index_fn,
            'remove_document': my_remove_fn,
        })
    """
    required_keys = {'search', 'index_document', 'remove_document'}
    missing = required_keys - set(driver)
    if missing:
        raise ValueError(f"Search driver '{name}' is missing required keys: {', '.join(sorted(missing))}")
    _DRIVERS[name] = driver
    _log.info('Registered search driver: %s', name)


def get_search_drivers() -> set[str]:
    """Return the names of all registered search drivers.

    Useful for debugging or health-check endpoints::

        from core.search import get_search_drivers
        print(get_search_drivers())  # e.g. {'meilisearch'}
    """
    return set(_DRIVERS)


def _get_driver(driver: str | None = None) -> tuple[str, dict[str, Callable]]:
    """Resolve and return the ``(name, driver_dict)`` to use.

    Args:
        driver: Explicit driver name, or ``None`` to read from
                ``settings.SEARCH_DRIVER``.

    Raises:
        ValueError: If the resolved driver name is not registered.
    """
    driver_name = driver or config.get('SEARCH_DRIVER', None) or None
    if driver_name is None:
        raise ValueError('No search driver configured. Set SEARCH_DRIVER in your .env or pass driver= explicitly.')
    handler = _DRIVERS.get(driver_name)
    if handler is None:
        available = ', '.join(sorted(_DRIVERS)) if _DRIVERS else '(none registered)'
        raise ValueError(f"Unknown search driver '{driver_name}'. Available drivers: {available}")
    return driver_name, handler


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def search(
    index: str,
    query: str,
    *,
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    offset: int = 0,
    driver: str | None = None,
) -> list[dict]:
    """Search for documents in a given index.

    Args:
        index: The name of the search index (e.g. ``'articles'``,
               ``'products'``). Corresponds to an index/collection in
               the external search engine.
        query: The search query string entered by the user.
        filters: Optional dict of field-value filters to narrow results.
                 How filters are applied depends on the driver. For
                 Meilisearch this becomes a filter string; for Algolia
                 it maps to ``facetFilters``.
        limit: Maximum number of results to return (default ``20``).
        offset: Number of results to skip — useful for pagination
                (default ``0``).
        driver: Override ``settings.SEARCH_DRIVER`` for this call.

    Returns:
        A list of dicts, each representing a matched document. The exact
        shape depends on the driver, but typically mirrors the document
        structure that was indexed.

    Raises:
        ValueError: If no driver is configured or the driver is unknown.

    Example::

        results = await search('articles', 'async python', filters={'status': 'published'}, limit=10)
        for hit in results:
            print(hit['title'], hit['id'])
    """
    name, drv = _get_driver(driver)
    _log.debug('search index=%s query=%r driver=%s', index, query, name)
    return await drv['search'](index, query, filters or {}, limit, offset)


async def index_document(
    index: str,
    doc_id: str | int,
    document: dict,
    *,
    driver: str | None = None,
) -> None:
    """Add or update a document in the search index.

    Call this explicitly from your controller after creating or updating
    a record. Nori does **not** hook into model saves automatically —
    you control when indexing happens.

    Args:
        index: The name of the search index.
        doc_id: A unique identifier for the document (usually the model's
                primary key).
        document: A dict of fields to index. Use ``model.to_dict()`` or
                  build a custom dict with only the fields you want
                  searchable.
        driver: Override ``settings.SEARCH_DRIVER`` for this call.

    Raises:
        ValueError: If no driver is configured or the driver is unknown.

    Example::

        article = await Article.create(title='Hello', body='World')
        await index_document('articles', article.id, article.to_dict())

    Tip:
        To index in the background without blocking the response, combine
        with :func:`core.tasks.background`::

            from core.tasks import background

            task = background(index_document, 'articles', article.id, article.to_dict())
            return JSONResponse({'id': article.id}, background=task)
    """
    name, drv = _get_driver(driver)
    _log.debug('index_document index=%s id=%s driver=%s', index, doc_id, name)
    await drv['index_document'](index, doc_id, document)


async def remove_document(
    index: str,
    doc_id: str | int,
    *,
    driver: str | None = None,
) -> None:
    """Remove a document from the search index.

    Call this explicitly from your controller after deleting a record.

    Args:
        index: The name of the search index.
        doc_id: The unique identifier of the document to remove.
        driver: Override ``settings.SEARCH_DRIVER`` for this call.

    Raises:
        ValueError: If no driver is configured or the driver is unknown.

    Example::

        await article.delete()
        await remove_document('articles', article.id)
    """
    name, drv = _get_driver(driver)
    _log.debug('remove_document index=%s id=%s driver=%s', index, doc_id, name)
    await drv['remove_document'](index, doc_id)
