from __future__ import annotations

from typing import Any, Callable, Iterable, TypeVar

T = TypeVar('T')

_builtin_min = min
_builtin_max = max


class NoriCollection(list[T]):
    """
    Lista con superpoderes. Envuelve resultados de Tortoise
    para proveer la misma API que Collection de Nori Engine.
    """

    def first(self) -> T | None:
        return self[0] if self else None

    def last(self) -> T | None:
        return self[-1] if self else None

    def is_empty(self) -> bool:
        return len(self) == 0

    def pluck(self, key: str) -> list[Any]:
        """Extraer valores de un campo."""
        return [getattr(item, key, item.get(key) if isinstance(item, dict) else None)
                for item in self]

    def where(self, key: str, operator_or_value: Any = '__sentinel__', value: Any = '__sentinel__') -> NoriCollection[T]:
        """Filtrar en memoria con operadores."""
        def _get_val(item: Any) -> Any:
            return getattr(item, key, item.get(key) if isinstance(item, dict) else None)

        if value == '__sentinel__':
            if operator_or_value == '__sentinel__':
                return NoriCollection(i for i in self if _get_val(i))
            return NoriCollection(i for i in self if _get_val(i) == operator_or_value)

        op = operator_or_value
        ops: dict[str, Callable[[Any, Any], bool]] = {
            '=':  lambda a, b: a == b,
            '!=': lambda a, b: a != b,
            '>':  lambda a, b: a is not None and a > b,
            '<':  lambda a, b: a is not None and a < b,
            '>=': lambda a, b: a is not None and a >= b,
            '<=': lambda a, b: a is not None and a <= b,
        }
        fn = ops.get(op, ops['='])
        return NoriCollection(i for i in self if fn(_get_val(i), value))

    def sort_by(self, key: str, reverse: bool = False) -> NoriCollection[T]:
        return NoriCollection(sorted(self, key=lambda i: getattr(i, key, None) or '', reverse=reverse))

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
        return [NoriCollection(self[i:i + size]) for i in range(0, len(self), size)]

    def map(self, fn: Callable[[T], Any]) -> NoriCollection[Any]:
        return NoriCollection(fn(item) for item in self)

    def each(self, fn: Callable[[T], Any]) -> NoriCollection[T]:
        for item in self:
            fn(item)
        return self

    def sum(self, key: str) -> float:
        return sum(getattr(i, key, 0) or 0 for i in self)

    def avg(self, key: str) -> float:
        vals = [getattr(i, key, 0) or 0 for i in self]
        return sum(vals) / len(vals) if vals else 0

    def min(self, key: str) -> Any | None:
        vals = [getattr(i, key, None) for i in self if getattr(i, key, None) is not None]
        return _builtin_min(vals) if vals else None

    def max(self, key: str) -> Any | None:
        vals = [getattr(i, key, None) for i in self if getattr(i, key, None) is not None]
        return _builtin_max(vals) if vals else None

    def to_list(self) -> list[Any]:
        """Convierte a lista de dicts (serializable a JSON)."""
        result: list[Any] = []
        for i in self:
            if hasattr(i, '__dict__'):
                # Tortoise model: excluir campos internos
                d = {k: v for k, v in i.__dict__.items() if not k.startswith('_')}
                result.append(d)
            elif isinstance(i, dict):
                result.append(i)
            else:
                result.append(i)
        return result

    def to_dict(self, key_field: str) -> dict[Any, T]:
        """Indexar por campo: {pk: model}."""
        return {getattr(i, key_field): i for i in self}


def collect(data: Iterable[T]) -> NoriCollection[T]:
    """
    Helper para convertir cualquier iterable a NoriCollection.

        users = collect(await User.all())
        names = users.pluck('name')
    """
    return NoriCollection(data)
