"""Pagination helpers: page-based and cursor-based navigation over QuerySets."""

from __future__ import annotations

import math
from typing import Any

from core.collection import collect


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
