from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable, TypeVar

T = TypeVar('T')

_builtin_min = min
_builtin_max = max
_SENTINEL = object()


class NoriCollection(list[T]):
    """
    List with superpowers. Wraps Tortoise results
    to provide the same API as Nori Engine's Collection.
    """

    def first(self) -> T | None:
        return self[0] if self else None

    def last(self) -> T | None:
        return self[-1] if self else None

    def is_empty(self) -> bool:
        return len(self) == 0

    def pluck(self, key: str) -> list[Any]:
        """Extract values from a field."""
        return [getattr(item, key, item.get(key) if isinstance(item, dict) else None) for item in self]

    def where(self, key: str, operator_or_value: Any = _SENTINEL, value: Any = _SENTINEL) -> NoriCollection[T]:
        """Filter in-memory with operators."""

        def _get_val(item: Any) -> Any:
            return getattr(item, key, item.get(key) if isinstance(item, dict) else None)

        if value is _SENTINEL:
            if operator_or_value is _SENTINEL:
                return NoriCollection(i for i in self if _get_val(i))
            return NoriCollection(i for i in self if _get_val(i) == operator_or_value)

        op = operator_or_value
        ops: dict[str, Callable[[Any, Any], bool]] = {
            '=': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
            '>': lambda a, b: a is not None and a > b,
            '<': lambda a, b: a is not None and a < b,
            '>=': lambda a, b: a is not None and a >= b,
            '<=': lambda a, b: a is not None and a <= b,
        }
        fn = ops.get(op, ops['='])
        return NoriCollection(i for i in self if fn(_get_val(i), value))

    def sort_by(self, key: str, reverse: bool = False) -> NoriCollection[T]:
        """Sort by field. None values are sorted to the end."""
        return NoriCollection(
            sorted(
                self,
                key=lambda i: (getattr(i, key, None) is None, getattr(i, key, None)),
                reverse=reverse,
            )
        )

    def group_by(self, key: str) -> dict[Any, NoriCollection[T]]:
        groups: dict[Any, NoriCollection[T]] = {}
        for item in self:
            k = getattr(item, key, None)
            groups.setdefault(k, NoriCollection()).append(item)
        return groups

    def unique(self, key: str | None = None) -> NoriCollection[T]:
        if key is None:
            return NoriCollection(dict.fromkeys(self))
        seen: set[Any] = set()
        result: NoriCollection[T] = NoriCollection()
        for item in self:
            k = getattr(item, key, None)
            if k not in seen:
                seen.add(k)
                result.append(item)
        return result

    def chunk(self, size: int) -> list[NoriCollection[T]]:
        return [NoriCollection(self[i : i + size]) for i in range(0, len(self), size)]

    def map(self, fn: Callable[[T], Any]) -> NoriCollection[Any]:
        return NoriCollection(fn(item) for item in self)

    def each(self, fn: Callable[[T], Any]) -> NoriCollection[T]:
        for item in self:
            fn(item)
        return self

    def sum(self, key: str) -> float:
        return sum(getattr(i, key, 0) or 0 for i in self)

    def avg(self, key: str) -> float | None:
        """Average of field values. Returns None for empty collections."""
        if not self:
            return None
        vals = [getattr(i, key, 0) or 0 for i in self]
        return sum(vals) / len(self)

    def min(self, key: str) -> Any | None:
        vals = [getattr(i, key, None) for i in self if getattr(i, key, None) is not None]
        return _builtin_min(vals) if vals else None

    def max(self, key: str) -> Any | None:
        vals = [getattr(i, key, None) for i in self if getattr(i, key, None) is not None]
        return _builtin_max(vals) if vals else None

    def to_list(self) -> list[Any]:
        """Convert to list of dicts (JSON serializable)."""
        result: list[Any] = []
        for i in self:
            if hasattr(i, 'to_dict') and callable(i.to_dict):
                # Use NoriModelMixin.to_dict() when available
                result.append(i.to_dict())
            elif hasattr(i, '_meta') and hasattr(i._meta, 'fields_map'):
                # Tortoise model without mixin: use fields_map
                d = {}
                for field in i._meta.fields_map:
                    if not field.startswith('_'):
                        try:
                            d[field] = getattr(i, field)
                        except Exception:  # noqa: S110, BLE001 — silently skip inaccessible fields (lazy/descriptor) during serialization
                            pass
                result.append(d)
            elif isinstance(i, dict):
                result.append(i)
            elif hasattr(i, '__dict__'):
                # Plain objects: exclude internal fields
                d = {k: v for k, v in i.__dict__.items() if not k.startswith('_')}
                result.append(d)
            else:
                result.append(i)
        return result

    def to_dict(self, key_field: str) -> dict[Any, T]:
        """Index by field: {pk: model}."""
        return {getattr(i, key_field): i for i in self}


def collect(data: Iterable[T]) -> NoriCollection[T]:
    """
    Helper to convert any iterable to NoriCollection.

        users = collect(await User.all())
        names = users.pluck('name')
    """
    return NoriCollection(data)
