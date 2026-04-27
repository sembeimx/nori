"""
Test factories for creating model instances with sensible defaults.

Usage::

    from factories import make_article, make_post, make_category

    article = await make_article(title='Custom Title')
    post = await make_post()
    root = await make_category(name='Root')
    child = await make_category(name='Child', parent_id=root.id)
"""

from __future__ import annotations

from typing import Any

from test_models import SampleArticle, SampleCategory, SamplePost

__all__ = ['make_article', 'make_post', 'make_category', 'reset_counters']

_counters: dict[str, int] = {}


def _next_id(prefix: str) -> int:
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return _counters[prefix]


def reset_counters() -> None:
    """Reset all counters (call between tests if needed)."""
    _counters.clear()


async def make_article(**overrides: Any) -> SampleArticle:
    n = _next_id('article')
    defaults: dict[str, Any] = {
        'title': f'Article {n}',
        'body': f'Body text for article {n}',
    }
    defaults.update(overrides)
    return await SampleArticle.create(**defaults)


async def make_post(**overrides: Any) -> SamplePost:
    n = _next_id('post')
    defaults: dict[str, Any] = {
        'title': f'Post {n}',
    }
    defaults.update(overrides)
    return await SamplePost.create(**defaults)


async def make_category(**overrides: Any) -> SampleCategory:
    n = _next_id('category')
    defaults: dict[str, Any] = {
        'name': f'Category {n}',
    }
    defaults.update(overrides)
    return await SampleCategory.create(**defaults)
