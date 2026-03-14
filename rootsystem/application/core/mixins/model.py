from __future__ import annotations

from typing import Any

from core.logger import get_logger

_log = get_logger('model')


class NoriModelMixin:
    """Mixin that adds ``to_dict()`` to Tortoise models.

    Provides automatic serialization with a safety net for sensitive data via
    the ``protected_fields`` class attribute.

    Usage::

        class User(NoriModelMixin, Model):
            protected_fields = ['password_hash', 'remember_token']
            ...

        user = await User.get(id=1)
        data = user.to_dict()                         # all fields (minus protected)
        data = user.to_dict(exclude=['email'])         # also exclude email
        data = user.to_dict(include_protected=True)    # force-include protected fields

    ``protected_fields`` acts as a security default — fields listed there are
    **always** excluded from ``to_dict()`` unless the caller explicitly passes
    ``include_protected=True``.  This prevents accidental leaks when a
    developer forgets to pass ``exclude=``.
    """

    protected_fields: list[str] = []
    """Fields that are excluded from ``to_dict()`` by default.

    Override this in your model to list sensitive columns that should never
    appear in API responses or template contexts unless explicitly requested::

        class User(NoriModelMixin, Model):
            protected_fields = ['password_hash', 'remember_token', 'two_factor_secret']
    """

    def to_dict(
        self,
        exclude: list[str] | None = None,
        *,
        include_protected: bool = False,
    ) -> dict[str, Any]:
        """Convert the model instance to a dictionary.

        Iterates over all Tortoise fields, skipping internal fields (prefixed
        with ``_``), explicitly excluded fields, and ``protected_fields``
        (unless *include_protected* is ``True``).

        Args:
            exclude: Additional field names to omit from the output.
            include_protected: When ``True``, ``protected_fields`` are
                included in the result.  Defaults to ``False`` so that
                sensitive data is never exposed accidentally.

        Returns:
            A ``dict[str, Any]`` mapping field names to their current values.
        """
        exclude_set: set[str] = set(exclude or [])
        if not include_protected:
            exclude_set.update(getattr(self, 'protected_fields', []))
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
