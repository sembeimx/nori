"""Tests for core.pagination module."""

import pytest
from core.pagination import _decode_cursor, _encode_cursor, paginate, paginate_cursor


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
        return self._items[self._offset : self._offset + self._limit]


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


# ---------------------------------------------------------------------------
# paginate_cursor
# ---------------------------------------------------------------------------


class _Row:
    """Tiny stand-in for a Tortoise model row."""

    def __init__(self, id: int):
        self.id = id

    def __repr__(self):
        return f'_Row({self.id})'


class _CursorQuerySet:
    """Fake QuerySet that supports order_by / filter / limit / all.

    Holds rows as a list of _Row; order_by reverses for ``-id``;
    filter applies an id__lt or id__gt; limit truncates.
    """

    def __init__(self, rows, order=None, lt=None, gt=None, limit=None):
        self._rows = rows
        self._order = order
        self._lt = lt
        self._gt = gt
        self._limit = limit

    def order_by(self, expr):
        return _CursorQuerySet(
            self._rows,
            order=expr,
            lt=self._lt,
            gt=self._gt,
            limit=self._limit,
        )

    def filter(self, **kwargs):
        lt = kwargs.get('id__lt', self._lt)
        gt = kwargs.get('id__gt', self._gt)
        return _CursorQuerySet(self._rows, order=self._order, lt=lt, gt=gt, limit=self._limit)

    def limit(self, n):
        return _CursorQuerySet(self._rows, order=self._order, lt=self._lt, gt=self._gt, limit=n)

    async def all(self):
        rows = list(self._rows)
        if self._order == '-id':
            rows.sort(key=lambda r: r.id, reverse=True)
        elif self._order == 'id':
            rows.sort(key=lambda r: r.id)
        if self._lt is not None:
            rows = [r for r in rows if r.id < self._lt]
        if self._gt is not None:
            rows = [r for r in rows if r.id > self._gt]
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows


def _rows(n):
    return [_Row(i) for i in range(1, n + 1)]


@pytest.mark.asyncio
async def test_paginate_cursor_first_page_descending():
    qs = _CursorQuerySet(_rows(50))
    result = await paginate_cursor(qs, per_page=10)
    ids = [r.id for r in result['data']]
    assert ids == [50, 49, 48, 47, 46, 45, 44, 43, 42, 41]
    assert result['has_next'] is True
    assert result['next_cursor'] is not None
    assert result['per_page'] == 10


@pytest.mark.asyncio
async def test_paginate_cursor_advances_via_next_cursor():
    """Following next_cursor must yield a contiguous, non-overlapping
    window — the keyset guarantee that OFFSET cannot give if rows are
    inserted between page fetches."""
    qs = _CursorQuerySet(_rows(50))

    page1 = await paginate_cursor(qs, per_page=10)
    page2 = await paginate_cursor(qs, cursor=page1['next_cursor'], per_page=10)

    assert [r.id for r in page2['data']] == [40, 39, 38, 37, 36, 35, 34, 33, 32, 31]
    assert page2['has_next'] is True


@pytest.mark.asyncio
async def test_paginate_cursor_last_page_has_no_next_cursor():
    qs = _CursorQuerySet(_rows(15))
    page1 = await paginate_cursor(qs, per_page=10)
    page2 = await paginate_cursor(qs, cursor=page1['next_cursor'], per_page=10)

    assert [r.id for r in page2['data']] == [5, 4, 3, 2, 1]
    assert page2['has_next'] is False
    assert page2['next_cursor'] is None


@pytest.mark.asyncio
async def test_paginate_cursor_ascending():
    qs = _CursorQuerySet(_rows(15))
    page1 = await paginate_cursor(qs, per_page=10, descending=False)
    assert [r.id for r in page1['data']] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert page1['has_next'] is True

    page2 = await paginate_cursor(qs, cursor=page1['next_cursor'], per_page=10, descending=False)
    assert [r.id for r in page2['data']] == [11, 12, 13, 14, 15]
    assert page2['has_next'] is False


@pytest.mark.asyncio
async def test_paginate_cursor_caps_per_page():
    qs = _CursorQuerySet(_rows(1000))
    result = await paginate_cursor(qs, per_page=9999)
    assert result['per_page'] == 500
    assert len(result['data']) == 500


@pytest.mark.asyncio
async def test_paginate_cursor_empty_queryset():
    qs = _CursorQuerySet([])
    result = await paginate_cursor(qs, per_page=10)
    assert list(result['data']) == []
    assert result['has_next'] is False
    assert result['next_cursor'] is None


@pytest.mark.asyncio
async def test_paginate_cursor_rejects_malformed_cursor():
    qs = _CursorQuerySet(_rows(10))
    with pytest.raises(ValueError, match='Malformed'):
        await paginate_cursor(qs, cursor='not-a-real-cursor')


def test_cursor_roundtrip_int():
    assert _decode_cursor(_encode_cursor(42)) == 42


def test_cursor_roundtrip_datetime():
    from datetime import datetime, timezone

    dt = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    assert _decode_cursor(_encode_cursor(dt)) == dt


def test_cursor_roundtrip_string():
    assert _decode_cursor(_encode_cursor('abc')) == 'abc'


def test_cursor_rejects_tampered_payload():
    """Re-encoding a different value with the legitimate signature still fails."""
    import base64
    import json

    real = _encode_cursor(42)
    payload_b64, _tag = real.split('.', 1)

    # Forge a new payload but keep the original tag — signature must reject.
    forged_payload = base64.urlsafe_b64encode(json.dumps(['raw', 9999]).encode()).rstrip(b'=').decode('ascii')
    forged_token = f'{forged_payload}.{_tag}'
    with pytest.raises(ValueError, match='signature mismatch'):
        _decode_cursor(forged_token)


def test_cursor_rejects_token_without_signature():
    """A token without the `.tag` suffix is treated as malformed."""
    import base64
    import json

    payload_b64 = base64.urlsafe_b64encode(json.dumps(['raw', 1]).encode()).rstrip(b'=').decode('ascii')
    with pytest.raises(ValueError, match='Malformed'):
        _decode_cursor(payload_b64)


def test_cursor_rejects_signature_from_different_secret(monkeypatch):
    """A token signed with a different secret is rejected."""
    from core import pagination

    real = _encode_cursor(42)

    # Rotate the SECRET_KEY mid-flight.
    monkeypatch.setattr(pagination, '_cursor_secret', lambda: b'a-different-secret')
    with pytest.raises(ValueError, match='signature mismatch'):
        _decode_cursor(real)
