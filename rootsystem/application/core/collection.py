"""NoriCollection: list with chainable map/filter/pluck/sum/group_by helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

T = TypeVar('T')

_builtin_min = min
_builtin_max = max
_SENTINEL = object()


def _get_field(item: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict (via __getitem__) or any other object (via getattr).

    Mirrors the access pattern in ``pluck`` and ``where`` so all reducers
    handle both model instances and plain dicts uniformly.
    """
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


class NoriCollection(list[T]):
    """
    List with superpowers. Wraps Tortoise results
    to provide the same API as Nori Engine's Collection.
    """

    def first(self) -> T | None:
        """Return the first element, or None if empty.

        >>> NoriCollection([1, 2, 3]).first()
        1
        >>> NoriCollection().first() is None
        True
        """
        return self[0] if self else None

    def last(self) -> T | None:
        """Return the last element, or None if empty.

        >>> NoriCollection([1, 2, 3]).last()
        3
        >>> NoriCollection().last() is None
        True
        """
        return self[-1] if self else None

    def is_empty(self) -> bool:
        """Return True if the collection has no elements.

        >>> NoriCollection().is_empty()
        True
        >>> NoriCollection([0]).is_empty()
        False
        """
        return len(self) == 0

    def pluck(self, key: str) -> list[Any]:
        """Extract values from a field across every item.

        >>> users = NoriCollection([{'name': 'ana'}, {'name': 'beto'}])
        >>> users.pluck('name')
        ['ana', 'beto']
        >>> NoriCollection([{'name': 'ana'}]).pluck('missing')
        [None]
        """
        return [getattr(item, key, item.get(key) if isinstance(item, dict) else None) for item in self]

    def where(self, key: str, operator_or_value: Any = _SENTINEL, value: Any = _SENTINEL) -> NoriCollection[T]:
        """Filter in-memory with optional comparison operators.

        Two-arg form (equality):

        >>> users = NoriCollection([{'role': 'admin'}, {'role': 'user'}])
        >>> users.where('role', 'admin').pluck('role')
        ['admin']

        Three-arg form (operator + value):

        >>> items = NoriCollection([{'price': 5}, {'price': 10}, {'price': 20}])
        >>> items.where('price', '>', 8).pluck('price')
        [10, 20]
        """

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
        """Split the collection into chunks of at most ``size`` elements.

        >>> [list(c) for c in NoriCollection([1, 2, 3, 4, 5]).chunk(2)]
        [[1, 2], [3, 4], [5]]
        """
        return [NoriCollection(self[i : i + size]) for i in range(0, len(self), size)]

    def map(self, fn: Callable[[T], Any]) -> NoriCollection[Any]:
        return NoriCollection(fn(item) for item in self)

    def each(self, fn: Callable[[T], Any]) -> NoriCollection[T]:
        for item in self:
            fn(item)
        return self

    def sum(self, key: str) -> float:
        """Sum a numeric field across all items. Missing/None values count as 0.

        Works on both model instances (attribute access) and dicts (key access)
        — consistent with ``pluck`` and ``where``.

        >>> NoriCollection([{'price': 5}, {'price': 10}]).sum('price')
        15
        >>> NoriCollection().sum('price')
        0
        """
        return sum(_get_field(i, key, 0) or 0 for i in self)

    def avg(self, key: str) -> float | None:
        """Average of field values. Returns None for empty collections.

        >>> NoriCollection([{'price': 10}, {'price': 20}, {'price': 30}]).avg('price')
        20.0
        >>> NoriCollection().avg('price') is None
        True
        """
        if not self:
            return None
        vals = [_get_field(i, key, 0) or 0 for i in self]
        return sum(vals) / len(self)

    def min(self, key: str) -> Any | None:
        """Minimum of field values. Skips None entries; returns None on empty.

        >>> NoriCollection([{'n': 3}, {'n': 1}, {'n': 2}]).min('n')
        1
        >>> NoriCollection([{'n': None}, {'n': 5}]).min('n')
        5
        """
        vals = [_get_field(i, key, None) for i in self]
        non_null = [v for v in vals if v is not None]
        return _builtin_min(non_null) if non_null else None

    def max(self, key: str) -> Any | None:
        """Maximum of field values. Skips None entries; returns None on empty.

        >>> NoriCollection([{'n': 3}, {'n': 1}, {'n': 2}]).max('n')
        3
        """
        vals = [_get_field(i, key, None) for i in self]
        non_null = [v for v in vals if v is not None]
        return _builtin_max(non_null) if non_null else None

    def to_list(self) -> list[Any]:
        """Convert to list of dicts (JSON serializable).

        Raises:
            TypeError: If an element is a Tortoise model that does not
                inherit from ``NoriModelMixin``. Walking ``_meta.fields_map``
                would emit every field, including secrets the developer
                assumed ``protected_fields`` was hiding (``password_hash``,
                tokens, internal notes). Refuse loudly instead of leaking.
        """
        result: list[Any] = []
        for i in self:
            if hasattr(i, 'to_dict') and callable(i.to_dict):
                # Use NoriModelMixin.to_dict() when available
                result.append(i.to_dict())
            elif hasattr(i, '_meta') and hasattr(i._meta, 'fields_map'):
                raise TypeError(
                    f'{type(i).__name__!r} is a Tortoise model without NoriModelMixin. '
                    'Serializing it would expose every field via _meta.fields_map, '
                    'including any sensitive ones (password_hash, tokens, etc.) that '
                    'protected_fields would have hidden. Inherit from NoriModelMixin '
                    '(`from core import NoriModelMixin`) and declare protected_fields, '
                    'or call .to_dict() on each instance manually before to_list().'
                )
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
