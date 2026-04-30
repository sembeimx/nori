"""Pagination helpers: page-based and cursor-based navigation over QuerySets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
from datetime import date, datetime
from typing import Any

from core.collection import collect
from core.conf import config

# Length of the truncated HMAC tag attached to each cursor token. 16 bytes
# (128 bits) is plenty for tamper detection — full SHA-256 would inflate
# the URL without adding meaningful security for a non-secret token.
_CURSOR_TAG_BYTES: int = 16


def _cursor_secret() -> bytes:
    """Resolve the signing key used to sign cursor tokens.

    Falls back to ``SECRET_KEY`` so projects don't have to configure a
    separate setting. The cursor tag isn't a secret — it just needs to
    be unforgeable by an external client.
    """
    secret = config.get('SECRET_KEY', '')
    if not secret:
        raise RuntimeError('SECRET_KEY is required to sign pagination cursors')
    return secret.encode() if isinstance(secret, str) else secret


async def paginate(queryset: Any, page: int = 1, per_page: int = 20) -> dict[str, Any]:
    """
    Paginate a Tortoise QuerySet.

        result = await paginate(Product.filter(status=1), page=2, per_page=20)
        # {
        #     'data': NoriCollection([...]),
        #     'total': 95,
        #     'page': 2,
        #     'per_page': 20,
        #     'last_page': 5
        # }
    """
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 20
    if per_page > 500:
        per_page = 500

    total = await queryset.count()
    last_page = max(1, math.ceil(total / per_page))

    if page > last_page:
        page = last_page

    offset = (page - 1) * per_page
    items = await queryset.offset(offset).limit(per_page).all()

    return {
        'data': collect(items),
        'total': total,
        'page': page,
        'per_page': per_page,
        'last_page': last_page,
    }


def _encode_cursor(value: Any) -> str:
    """Encode a cursor value as a URL-safe base64 token signed with HMAC.

    The token format is ``<urlsafe_b64(payload)>.<urlsafe_b64(tag)>`` where
    ``tag`` is the first 16 bytes of ``HMAC-SHA256(SECRET_KEY, payload)``.
    The signature lets the server reject hand-crafted cursors — without
    it, a client could substitute arbitrary timestamps to trigger
    expensive range scans or skip rows it shouldn't see.

    Supports datetimes, dates, and JSON-native scalars (int, str, float).
    The token is opaque to callers — they should treat it as a string.
    """
    if isinstance(value, datetime):
        payload: list[Any] = ['datetime', value.isoformat()]
    elif isinstance(value, date):
        payload = ['date', value.isoformat()]
    else:
        payload = ['raw', value]
    payload_bytes = json.dumps(payload).encode()
    tag = hmac.new(_cursor_secret(), payload_bytes, hashlib.sha256).digest()[:_CURSOR_TAG_BYTES]
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b'=').decode('ascii')
    tag_b64 = base64.urlsafe_b64encode(tag).rstrip(b'=').decode('ascii')
    return f'{payload_b64}.{tag_b64}'


def _decode_cursor(cursor: str) -> Any:
    """Decode and verify a token produced by :func:`_encode_cursor`.

    Raises:
        ValueError: If the token is malformed, the signature is missing,
            or the signature does not match. Surfaces to the caller as a
            400-class signal that the cursor is unusable.
    """
    try:
        payload_b64, tag_b64 = cursor.split('.', 1)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + '=' * (-len(payload_b64) % 4))
        provided_tag = base64.urlsafe_b64decode(tag_b64 + '=' * (-len(tag_b64) % 4))
    except (ValueError, TypeError) as exc:
        raise ValueError(f'Malformed pagination cursor: {cursor!r}') from exc

    expected_tag = hmac.new(_cursor_secret(), payload_bytes, hashlib.sha256).digest()[:_CURSOR_TAG_BYTES]
    if not hmac.compare_digest(provided_tag, expected_tag):
        raise ValueError('Pagination cursor signature mismatch')

    try:
        kind, value = json.loads(payload_bytes)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'Malformed pagination cursor payload: {cursor!r}') from exc
    if kind == 'datetime':
        return datetime.fromisoformat(value)
    if kind == 'date':
        return date.fromisoformat(value)
    return value


async def paginate_cursor(
    queryset: Any,
    *,
    cursor: str | None = None,
    per_page: int = 20,
    field: str = 'id',
    descending: bool = True,
) -> dict[str, Any]:
    """
    Cursor-based pagination using an indexed WHERE clause.

        # First page (newest first)
        result = await paginate_cursor(Article.all(), per_page=20)

        # Next page — pass the previous cursor
        result = await paginate_cursor(
            Article.all(),
            cursor=result['next_cursor'],
            per_page=20,
        )

    Cost is O(per_page) regardless of depth. ``paginate()`` (offset-
    based) scans and discards rows for every page beyond the first, so
    page 5000 of a 100k-row table is far slower than page 1 — the DB
    has to walk the index 100k positions just to skip them. Keyset
    pagination uses ``WHERE field < cursor`` (or ``>`` for ascending),
    which jumps straight to the right offset via the index.

    Trade-offs vs. ``paginate()``:
      * No total count, no last-page jump (would defeat the index).
      * Forward-only scrolling. Bookmark a page by saving the cursor.
      * ``field`` must be unique and indexed (the primary key is the
        common choice). Non-unique fields produce duplicates and skips
        when two rows share the same value at the page boundary.

    Args:
        queryset: A Tortoise QuerySet or any object exposing
            ``order_by()``, ``filter()``, ``limit()``, and ``all()``.
        cursor: Opaque token returned by the previous call; ``None``
            for the first page.
        per_page: Page size, clamped to [1, 500].
        field: Field to order on. Must be unique and indexed.
        descending: ``True`` for "newest first" (id DESC); ``False``
            for ascending.

    Returns:
        Dict with:
          * ``data`` (NoriCollection): the page's rows.
          * ``per_page`` (int): the effective page size.
          * ``next_cursor`` (str | None): token for the next page, or
            ``None`` when there are no more results.
          * ``has_next`` (bool): convenience flag mirroring
            ``next_cursor is not None``.
    """
    if per_page < 1:
        per_page = 20
    if per_page > 500:
        per_page = 500

    order_expr = f'-{field}' if descending else field
    qs = queryset.order_by(order_expr)

    if cursor is not None:
        decoded = _decode_cursor(cursor)
        op = '__lt' if descending else '__gt'
        qs = qs.filter(**{f'{field}{op}': decoded})

    # Fetch per_page + 1 to detect whether another page exists without
    # an extra COUNT query.
    raw = await qs.limit(per_page + 1).all()
    has_next = len(raw) > per_page
    items = raw[:per_page]

    next_cursor: str | None = None
    if has_next and items:
        last = items[-1]
        last_value = last.get(field) if isinstance(last, dict) else getattr(last, field)
        next_cursor = _encode_cursor(last_value)

    return {
        'data': collect(items),
        'per_page': per_page,
        'next_cursor': next_cursor,
        'has_next': has_next,
    }
