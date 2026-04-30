"""
Form-value re-population after validation errors.

Pattern (controller):

    errors = validate(form, rules)
    if errors:
        flash_old(request, form)
        return templates.TemplateResponse(
            request, 'create.html', {'errors': errors}
        )

Pattern (template):

    <input name="email" value="{{ old('email') }}">
    <textarea name="bio">{{ old('bio') }}</textarea>

The `old()` Jinja global reads the last-flashed values from the user's
session, so the form re-renders with whatever the user typed instead of
empty fields. Sensitive fields (passwords) are excluded from the flash by
default.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from jinja2 import pass_context
from starlette.requests import Request

_SESSION_KEY = '_old'

_DEFAULT_EXCLUDE: tuple[str, ...] = (
    'password',
    'password_confirmation',
    'current_password',
    'new_password',
)


def _is_uploaded_file(value: Any) -> bool:
    """Return True if ``value`` looks like a Starlette ``UploadFile``.

    Duck-typing instead of ``isinstance(value, UploadFile)`` so the helper
    keeps working under test fakes and any future replacement of the
    Starlette upload object — anything exposing both ``filename`` and a
    callable ``read`` is treated as a file. The cost of a false positive
    on a benign duck-type is just a missing field in the re-rendered form,
    which the user can re-enter; the cost of a false negative is the
    500 this function exists to prevent.
    """
    return hasattr(value, 'filename') and callable(getattr(value, 'read', None))


def flash_old(
    request: Request,
    form: Any,
    exclude: Iterable[str] | None = None,
) -> None:
    """Stash form values in the session for the next `{{ old() }}` lookup.

    Sensitive fields in `_DEFAULT_EXCLUDE` are dropped automatically. Pass
    an explicit `exclude` (any iterable of field names) to override or
    extend the list — the user's iterable replaces the default.

    File uploads (``UploadFile``-like values) are dropped before the write.
    The cookie-backed ``SessionMiddleware`` JSON-serialises the session on
    every response, and ``UploadFile`` is not JSON-serialisable — without
    this filter, a multipart form that fails any other validation rule
    crashes the response with a 500 the moment ``flash_old`` runs. Browsers
    refuse to pre-populate ``<input type="file">`` for security reasons
    anyway, so dropping the file is the right semantic too: the user has to
    re-pick the file, but every other field they typed is preserved in
    the re-rendered form.
    """
    skip = set(_DEFAULT_EXCLUDE if exclude is None else exclude)
    safe = {
        k: v
        for k, v in dict(form).items()
        if k not in skip and not _is_uploaded_file(v)
    }
    request.session[_SESSION_KEY] = safe


def _old_value(session: Any, field: str, default: str = '') -> Any:
    return session.get(_SESSION_KEY, {}).get(field, default)


@pass_context
def old(ctx, field: str, default: str = '') -> Any:
    """Jinja global. Returns the last-flashed value for `field`, or `default`.

    Reads from `ctx['request'].session`. The starlette templating context
    always exposes `request`, so this works inside any template rendered
    via `templates.TemplateResponse(request, ...)`.
    """
    request = ctx.get('request')
    if request is None:
        return default
    return _old_value(request.session, field, default)
