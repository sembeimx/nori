"""
Master seeder that orchestrates all individual seeders.

    python3 nori.py db:seed
"""

from __future__ import annotations

import importlib

from core.logger import get_logger

_log = get_logger('seeder')

# Register your seeders here (module paths relative to the application directory)
SEEDERS: list[str] = [
    # 'seeders.user_seeder',
    # 'seeders.category_seeder',
]


async def run() -> None:
    """Run all registered seeders in order."""
    if not SEEDERS:
        _log.info("No seeders registered. Add modules to SEEDERS list in database_seeder.py")
        print("No seeders registered. Edit seeders/database_seeder.py to add seeder modules.")
        return

    for module_path in SEEDERS:
        _log.info("Running seeder: %s", module_path)
        print(f"  Seeding: {module_path}...")
        try:
            mod = importlib.import_module(module_path)
            if not hasattr(mod, 'run') or not callable(mod.run):
                _log.warning("Seeder %s has no run() function, skipping", module_path)
                continue
            await mod.run()
        except Exception as exc:
            _log.error("Seeder %s failed: %s", module_path, exc, exc_info=True)
            raise

    print("Database seeding complete.")
