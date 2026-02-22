from __future__ import annotations

from typing import Any


class NoriModelMixin:
    """
    Mixin que agrega to_dict() a modelos Tortoise.

        class User(NoriModelMixin, Model):
            ...

        user = await User.get(id=1)
        data = user.to_dict()                         # todos los campos
        data = user.to_dict(exclude=['password'])      # sin password
    """

    def to_dict(self, exclude: list[str] | None = None) -> dict[str, Any]:
        """
        Convierte el modelo a dict (excluyendo campos internos de Tortoise).

        Args:
            exclude: lista de campos a excluir del resultado
        """
        exclude_set: set[str] = set(exclude or [])
        result: dict[str, Any] = {}
        for field in self._meta.fields_map:
            if field in exclude_set:
                continue
            if field.startswith('_'):
                continue
            try:
                result[field] = getattr(self, field)
            except Exception:
                pass
        return result
