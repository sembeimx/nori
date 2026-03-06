from __future__ import annotations

from typing import Any

from core.logger import get_logger

_log = get_logger('model')


class NoriModelMixin:
    """
    Mixin that adds to_dict() to Tortoise models.

        class User(NoriModelMixin, Model):
            ...

        user = await User.get(id=1)
        data = user.to_dict()                         # all fields
        data = user.to_dict(exclude=['password'])      # without password
    """

    def to_dict(self, exclude: list[str] | None = None) -> dict[str, Any]:
        """
        Converts the model to a dict (excluding internal Tortoise fields).

        Args:
            exclude: list of fields to exclude from the result
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
            except Exception as exc:
                _log.warning("Failed to serialize field '%s': %s", field, exc)
        return result
