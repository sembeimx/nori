"""Tests for core.pagination module."""
import math
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.pagination import paginate


class _FakeQuerySet:
    """Simulates a Tortoise QuerySet with count/offset/limit/all."""

    def __init__(self, items):
        self._items = items

    async def count(self):
        return len(self._items)

    def offset(self, n):
        self._offset = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    async def all(self):
        return self._items[self._offset:self._offset + self._limit]


@pytest.mark.asyncio
async def test_paginate_first_page():
    qs = _FakeQuerySet(list(range(50)))
    result = await paginate(qs, page=1, per_page=10)
    assert result['total'] == 50
    assert result['page'] == 1
    assert result['per_page'] == 10
    assert result['last_page'] == 5
    assert len(result['data']) == 10


@pytest.mark.asyncio
async def test_paginate_last_page():
    qs = _FakeQuerySet(list(range(25)))
    result = await paginate(qs, page=3, per_page=10)
    assert result['page'] == 3
    assert result['last_page'] == 3
    assert len(result['data']) == 5


@pytest.mark.asyncio
async def test_paginate_clamps_page_below_1():
    qs = _FakeQuerySet(list(range(10)))
    result = await paginate(qs, page=0, per_page=5)
    assert result['page'] == 1


@pytest.mark.asyncio
async def test_paginate_clamps_page_negative():
    qs = _FakeQuerySet(list(range(10)))
    result = await paginate(qs, page=-5, per_page=5)
    assert result['page'] == 1


@pytest.mark.asyncio
async def test_paginate_clamps_page_beyond_last():
    qs = _FakeQuerySet(list(range(10)))
    result = await paginate(qs, page=999, per_page=5)
    assert result['page'] == 2  # last_page = ceil(10/5) = 2


@pytest.mark.asyncio
async def test_paginate_clamps_per_page_below_1():
    qs = _FakeQuerySet(list(range(10)))
    result = await paginate(qs, page=1, per_page=0)
    assert result['per_page'] == 20  # default fallback


@pytest.mark.asyncio
async def test_paginate_empty_queryset():
    qs = _FakeQuerySet([])
    result = await paginate(qs, page=1, per_page=10)
    assert result['total'] == 0
    assert result['page'] == 1
    assert result['last_page'] == 1
    assert len(result['data']) == 0


@pytest.mark.asyncio
async def test_paginate_exact_division():
    qs = _FakeQuerySet(list(range(20)))
    result = await paginate(qs, page=2, per_page=10)
    assert result['last_page'] == 2
    assert result['page'] == 2
    assert len(result['data']) == 10


@pytest.mark.asyncio
async def test_paginate_returns_nori_collection():
    from core.collection import NoriCollection
    qs = _FakeQuerySet(list(range(5)))
    result = await paginate(qs, page=1, per_page=10)
    assert isinstance(result['data'], NoriCollection)


@pytest.mark.asyncio
async def test_paginate_caps_per_page_at_500():
    """per_page values above 500 are clamped to 500."""
    qs = _FakeQuerySet(list(range(1000)))
    result = await paginate(qs, page=1, per_page=9999)
    assert result['per_page'] == 500
    assert len(result['data']) == 500
