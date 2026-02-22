from __future__ import annotations

import math
from typing import Any

from core.collection import collect


async def paginate(queryset: Any, page: int = 1, per_page: int = 20) -> dict[str, Any]:
    """
    Pagina un QuerySet de Tortoise con el mismo formato que Nori.

        result = await paginate(Product.filter(status=1), page=2, per_page=20)
        # {
        #     'data': NoriCollection([...]),
        #     'total': 95,
        #     'page': 2,
        #     'per_page': 20,
        #     'last_page': 5
        # }
    """
    total = await queryset.count()
    last_page = math.ceil(total / per_page) if total > 0 else 1

    offset = (page - 1) * per_page
    items = await queryset.offset(offset).limit(per_page).all()

    return {
        'data': collect(items),
        'total': total,
        'page': page,
        'per_page': per_page,
        'last_page': last_page,
    }
