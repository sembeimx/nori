"""
Nori post-update patches — idempotent edits to user-land files.

Each patcher reads a user-owned file, checks whether the change is already
applied, and injects the missing bits. Existing user customizations are
preserved. The top-level `apply()` is invoked by `core.cli.framework_update()`
after the framework directories and files have been replaced on disk.

IMPORTANT — reload-safe:
`core.cli.framework_update()` imports this module via `importlib` AFTER
clearing it from `sys.modules`, so the freshly installed bytecode executes
— not whatever was in memory when the update started. That is how newly
added patches can apply on the same run that installs them. Do NOT move
these patchers back into `cli.py`; `cli.py` is already loaded in memory
by the time `framework_update()` runs.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Callable

_APP_DIR = os.path.join('rootsystem', 'application')
_ASGI_FILE = os.path.join(_APP_DIR, 'asgi.py')
_REQUIREMENTS_FILE = 'requirements.txt'

_BOOTSTRAP_IMPORT_LINE = 'from core.bootstrap import load_bootstrap'
_BOOTSTRAP_CALL_LINE = 'load_bootstrap()'
_REQUIREMENTS_NORI_REF = '-r requirements.nori.txt'


def _patch_bootstrap_hook_in_asgi() -> bool:
    if not os.path.exists(_ASGI_FILE):
        return False

    with open(_ASGI_FILE) as f:
        content = f.read()

    if _BOOTSTRAP_IMPORT_LINE in content:
        return False

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f'  Warning: cannot parse asgi.py ({e}) — skipping bootstrap patch')
        return False

    insert_lineno = 1
    for stmt in tree.body:
        is_docstring = (
            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)
        )
        is_future = isinstance(stmt, ast.ImportFrom) and stmt.module == '__future__'
        if is_docstring or is_future:
            # AST end_lineno is Optional[int]; for real source nodes it's always set.
            insert_lineno = (stmt.end_lineno or stmt.lineno) + 1
            continue
        break

    injection = (
        '\n'
        '# Bootstrap hook — MUST run before any framework/third-party import so\n'
        '# observability SDKs (Sentry, OTel, Datadog) can patch libraries at load time.\n'
        f'{_BOOTSTRAP_IMPORT_LINE}\n'
        f'{_BOOTSTRAP_CALL_LINE}\n'
        '\n'
    )

    lines = content.splitlines(keepends=True)
    idx = min(insert_lineno - 1, len(lines))
    lines.insert(idx, injection)

    with open(_ASGI_FILE, 'w') as f:
        f.write(''.join(lines))

    return True


def _patch_requirements_dash_r_to_nori() -> bool:
    if not os.path.exists(_REQUIREMENTS_FILE):
        return False

    with open(_REQUIREMENTS_FILE) as f:
        content = f.read()

    if _REQUIREMENTS_NORI_REF in content:
        return False

    with open(_REQUIREMENTS_FILE, 'w') as f:
        f.write(_REQUIREMENTS_NORI_REF + '\n\n' + content)

    return True


_PATCHERS: list[tuple[Callable[[], bool], str]] = [
    (_patch_bootstrap_hook_in_asgi, 'asgi.py: added bootstrap hook'),
    (_patch_requirements_dash_r_to_nori, 'requirements.txt: added -r requirements.nori.txt'),
]


def apply() -> list[str]:
    applied: list[str] = []
    for fn, label in _PATCHERS:
        try:
            if fn():
                applied.append(label)
        except Exception as e:
            print(f"  Warning: patch '{label}' failed — {e}")
    return applied
