from __future__ import annotations

"""
Model registry — decouples the core from concrete model imports.

Application code registers its models at startup::

    from core.registry import register_model
    from models.audit_log import AuditLog

    register_model('AuditLog', AuditLog)

Core modules retrieve them by name without importing from ``models/``::

    from core.registry import get_model

    AuditLog = get_model('AuditLog')
    await AuditLog.create(...)
"""

from typing import Any

_models: dict[str, type] = {}


def register_model(name: str, model_class: type) -> None:
    """Register a model class by name.

    Args:
        name: Logical name (e.g. ``'AuditLog'``, ``'Job'``, ``'Role'``).
        model_class: The Tortoise ``Model`` subclass.
    """
    _models[name] = model_class


def get_model(name: str) -> Any:
    """Retrieve a registered model class by name.

    Args:
        name: The name used during registration.

    Returns:
        The model class.

    Raises:
        LookupError: If the model was not registered.
    """
    try:
        return _models[name]
    except KeyError:
        raise LookupError(
            f"Model '{name}' not registered. "
            f"Ensure it is imported and registered in models/__init__.py"
        ) from None


def get_registered_models() -> dict[str, type]:
    """Return a copy of all registered models (for introspection)."""
    return dict(_models)
