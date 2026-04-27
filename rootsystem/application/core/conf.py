"""
Configuration provider — single access point for settings within the core.

Instead of ``import settings`` scattered across core modules, the framework
accesses configuration through this module.  The application initialises it
once at startup::

    import settings
    from core.conf import configure
    configure(settings)

Core modules then read values without importing ``settings`` directly::

    from core.conf import config

    secret = config.SECRET_KEY
    db     = config.get('DB_ENGINE', 'sqlite')
"""

from __future__ import annotations

from typing import Any


class _Config:
    """Lazy proxy around the application settings module."""

    __slots__ = ('_settings',)

    def __init__(self) -> None:
        self._settings: Any = None

    # -- bootstrap -----------------------------------------------------------

    def configure(self, settings_module: Any) -> None:
        """Bind the application settings module.

        Called once at startup (``asgi.py`` lifespan or CLI bootstrap).
        """
        self._settings = settings_module

    @property
    def is_configured(self) -> bool:
        return self._settings is not None

    # -- access --------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Read a setting by name with an optional default."""
        if self._settings is None:
            return default
        return getattr(self._settings, key, default)

    def __getattr__(self, key: str) -> Any:
        """Attribute-style access: ``config.SECRET_KEY``."""
        if key.startswith('_'):
            raise AttributeError(key)
        if self._settings is None:
            raise RuntimeError('Nori config not initialised — call core.conf.configure(settings) at startup')
        try:
            return getattr(self._settings, key)
        except AttributeError:
            raise AttributeError(f"Settings has no attribute '{key}'") from None


# Singleton — importable as ``from core.conf import config``
config = _Config()

# Convenience alias so callers can do ``from core.conf import configure``
configure = config.configure
