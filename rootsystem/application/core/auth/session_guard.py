"""
Session revocation via per-user version counter (read-through cache + DB).

Starlette's ``SessionMiddleware`` issues signed cookies — the signature
prevents tampering, not theft. Once the cookie leaves the user's browser
(stolen via XSS, malware, physical access, third-party JS leak), the
attacker has the same authority as the user until the cookie's
``max_age`` expires. There is no native revocation channel; the
framework cannot un-issue a signed cookie it already gave out.

The session-version guard plugs that hole with a per-user integer
counter. At login the project copies the user's current version into
``session['session_version']``. On every gated request, the framework
compares the session's version against the canonical version stored in
the database. Bumping the DB column (``invalidate_session(user_id)``)
makes every cookie carrying a stale version fail the next gated
request, atomically across all in-flight sessions for that user.

The cache is a read-through accelerator only — the database is the
authoritative source. If Redis evicts the version key, the framework
re-reads from the DB on the next request and re-populates the cache.
A revocation written only to the cache would last as long as the cache
key TTL; persisting it in the DB makes it durable across cache resets.

Failure modes (when both cache AND DB are unreachable in the same
request) are configurable:

* ``SESSION_VERSION_FAIL_MODE = 'open'`` (default)
  Log CRITICAL + audit event ``session_guard.fail_open`` + allow the
  request. Pragmatic for SaaS / blogs; assumes a brief storage hiccup
  is more disruptive than a brief revocation gap.

* ``SESSION_VERSION_FAIL_MODE = 'closed'``
  Same logging + audit event ``session_guard.fail_closed`` + deny the
  request (401 / redirect). Right for finance / healthcare; assumes
  a brief denial-of-service is preferable to a brief security gap.

Both modes are protected against sustained outages by a process-local
circuit breaker: once N consecutive failures land within a sliding
window, the breaker opens and forces fail-closed for a configurable
cooldown period regardless of fail-mode. The breaker state lives in
plain module globals — deliberately NOT in the cache, since the cache
is exactly the resource we cannot rely on at the moment we need to
make this decision. Each worker process tracks its own breaker; cache
recovery is detected by the next successful read clearing the counter.

Boot-time validation: when ``SESSION_VERSION_CHECK = True`` is enabled
in settings, ``configure_session_guard()`` (called from the ASGI
lifespan) verifies that the registered ``User`` model exposes a
``session_version`` field. If the field is missing the framework
raises ``RuntimeError`` with the exact migration to apply, rather than
silently degrading to "always allow" — explicit failure is the only
safe path when the project has opted into the feature.

Usage in project code::

    # settings.py
    SESSION_VERSION_CHECK = True
    SESSION_VERSION_FAIL_MODE = 'open'   # or 'closed'

    # models/user.py — add the column
    class User(NoriModelMixin, Model):
        session_version = fields.IntField(default=0)
        # ... other fields ...

    # Bump on logout, password change, "log out everywhere":
    from core.auth.session_guard import invalidate_session

    async def logout_everywhere(self, request):
        await invalidate_session(int(request.session['user_id']),
                                 request=request)
        request.session.clear()
        return RedirectResponse('/login', status_code=302)
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request

from core.audit import audit
from core.cache import cache_get, cache_set
from core.conf import config
from core.logger import get_logger
from core.registry import get_model

_log = get_logger('session_guard')

_PREFIX = 'session_guard:'


def _version_key(user_id: int) -> str:
    return f'{_PREFIX}{user_id}:version'


# ---------------------------------------------------------------------------
# Process-local circuit breaker
# ---------------------------------------------------------------------------
#
# Mutually-exclusive design constraint: the breaker MUST NOT depend on the
# cache to make a decision. The whole point of the breaker is "the cache
# (and possibly the DB) is unreachable" — using ``cache_incr`` in that
# branch would either crash with the second exception or, worse, oscillate
# if the cache flickers. The state lives in module globals and is updated
# in plain Python — asyncio's single-loop cooperative model means there is
# no race between coroutines reading and writing these counters as long as
# the read-decide-write happens without an ``await`` in the middle, which
# is the case here.
#
# Each worker process maintains its own breaker. With N workers a cache
# outage will trip ``threshold`` failures per process before each opens its
# breaker — that is by design. There is no shared state to coordinate
# across workers without using the cache, which is the resource we are
# specifically trying to avoid relying on.
_circuit_state: dict[str, float | int] = {
    'consecutive_fails': 0,
    'last_fail_at': 0.0,
    'open_until': 0.0,
}


def _reset_circuit() -> None:
    """Reset the breaker to its initial state. Used by tests; not part of
    the public API. Production code never resets the breaker manually —
    the next successful read resets ``consecutive_fails`` via
    ``_record_success``.
    """
    _circuit_state['consecutive_fails'] = 0
    _circuit_state['last_fail_at'] = 0.0
    _circuit_state['open_until'] = 0.0


def _is_circuit_open() -> bool:
    """Returns True iff the breaker is currently tripped open."""
    return time.time() < float(_circuit_state['open_until'])


def _record_fail() -> bool:
    """Record one storage failure. Returns True iff this failure tripped
    the breaker open. The window is sliding — failures older than the
    configured window do not count toward the threshold, so a project
    that hits the cache once a minute and gets one error every 5 minutes
    never trips the breaker.
    """
    now = time.time()
    threshold = int(config.get('SESSION_VERSION_CIRCUIT_THRESHOLD', 50))
    window = int(config.get('SESSION_VERSION_CIRCUIT_WINDOW', 60))
    open_for = int(config.get('SESSION_VERSION_CIRCUIT_OPEN_DURATION', 30))

    if now - float(_circuit_state['last_fail_at']) > window:
        _circuit_state['consecutive_fails'] = 0

    _circuit_state['consecutive_fails'] = int(_circuit_state['consecutive_fails']) + 1
    _circuit_state['last_fail_at'] = now

    if int(_circuit_state['consecutive_fails']) >= threshold:
        _circuit_state['open_until'] = now + open_for
        return True
    return False


def _record_success() -> None:
    """Record one successful storage read. Resets the failure counter so
    transient hiccups do not accumulate toward the breaker threshold.
    """
    _circuit_state['consecutive_fails'] = 0
    _circuit_state['open_until'] = 0.0


# ---------------------------------------------------------------------------
# Live version lookup (cache → DB read-through)
# ---------------------------------------------------------------------------


_VERSION_NOT_FOUND = -1  # sentinel: user row does not exist in DB


async def _get_live_version(user_id: int) -> int | None:
    """Returns the canonical session_version for ``user_id``.

    Resolution order:

    1. Cache hit       → return the cached value, record success.
    2. Cache miss      → read from DB, populate cache (best-effort),
                         return the DB value.
    3. Cache error     → fall through to DB.
    4. DB error        → record failure, return ``None``.
    5. User not found  → return ``_VERSION_NOT_FOUND`` (-1). This is
                         distinct from "both stores unavailable"
                         because a deleted user MUST be denied even
                         when the storage layer is healthy.
    """
    cache_failed = False
    try:
        cached = await cache_get(_version_key(user_id))
    except Exception as exc:
        _log.warning('Session guard cache read failed for user %s: %s', user_id, exc)
        cache_failed = True
        cached = None

    if cached is not None and not cache_failed:
        _record_success()
        return int(cached)

    # Cache miss or cache error — go to the DB. The DB is authoritative;
    # losing the cache only costs us one extra round-trip per request
    # until the cache repopulates.
    try:
        User = get_model('User')
    except LookupError:
        # User model not registered. This should be impossible if
        # configure_session_guard() was called at boot, but a project
        # could theoretically toggle the setting at runtime. Treat as a
        # storage failure rather than crashing.
        _log.error('Session guard: User model not registered; cannot resolve session_version')
        _record_fail()
        return None

    try:
        user_obj = await User.get_or_none(id=user_id)
    except Exception as exc:
        _log.error('Session guard DB read failed for user %s: %s', user_id, exc)
        _record_fail()
        return None

    _record_success()

    if user_obj is None:
        return _VERSION_NOT_FOUND

    live_v = int(getattr(user_obj, 'session_version', 0))

    # Best-effort cache populate. If this fails the request still
    # succeeds — the next request will hit the DB again, which is
    # the correct degraded behavior.
    try:
        await cache_set(_version_key(user_id), live_v)
    except Exception as exc:
        _log.warning('Session guard cache write failed for user %s: %s', user_id, exc)

    return live_v


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_session_version(request: Request) -> bool:
    """Validate the request's session against the canonical version.

    Returns ``True`` to allow the request, ``False`` to deny.

    The function is a no-op (returns True) when:
    * ``SESSION_VERSION_CHECK`` is False / unset (feature disabled).
    * The session has no ``user_id`` (anonymous request — caller's
      ``login_required`` should have handled this already, but we
      defend in depth).
    * The session has no ``session_version`` key. This means the
      session was created by a process running pre-feature, OR the
      project's login flow was not updated to populate the field.
      We allow it through this request; the project should populate
      the field at next login.

    Denial paths emit ``audit(...)`` events for forensic trail:
    * ``session_guard.revoked``       — version mismatch (the most
      common path — admin called ``invalidate_session()``).
    * ``session_guard.user_deleted``  — user row no longer exists.
    * ``session_guard.circuit_open``  — breaker forced fail-closed.
    * ``session_guard.fail_open``     — both stores down, allowed by
      configured fail mode.
    * ``session_guard.fail_closed``   — both stores down, denied by
      configured fail mode.
    """
    if not config.get('SESSION_VERSION_CHECK', False):
        return True

    user_id_raw = request.session.get('user_id')
    if not user_id_raw:
        return True

    session_v = request.session.get('session_version')
    if session_v is None:
        # Session predates the feature OR the login flow has not been
        # updated. Allow this request — the docs spell out that the
        # project must populate the field at login for the guard to
        # take effect. Skipping it here keeps existing sessions live
        # across the upgrade boundary.
        return True

    user_id = int(user_id_raw)

    if _is_circuit_open():
        audit(
            request,
            'session_guard.circuit_open',
            model_name='session',
            record_id=str(user_id),
        )
        return False

    live_v = await _get_live_version(user_id)

    if live_v is None:
        # Both cache and DB failed. Apply configured fail mode + audit.
        # ``_record_fail`` was already called inside ``_get_live_version``;
        # check whether that flipped the breaker open and surface that
        # specifically (it is more actionable than a generic fail event).
        if _is_circuit_open():
            _log.critical(
                'Session guard circuit opened — %d consecutive storage failures within window',
                int(_circuit_state['consecutive_fails']),
            )
            audit(
                request,
                'session_guard.circuit_open',
                model_name='session',
                record_id=str(user_id),
            )
            return False

        mode = str(config.get('SESSION_VERSION_FAIL_MODE', 'open')).lower()
        action = f'session_guard.fail_{"closed" if mode == "closed" else "open"}'
        audit(request, action, model_name='session', record_id=str(user_id))
        return mode != 'closed'

    if live_v == _VERSION_NOT_FOUND:
        audit(
            request,
            'session_guard.user_deleted',
            model_name='session',
            record_id=str(user_id),
        )
        return False

    if int(session_v) != live_v:
        audit(
            request,
            'session_guard.revoked',
            model_name='session',
            record_id=str(user_id),
            changes={'session_v': int(session_v), 'live_v': live_v},
        )
        return False

    return True


async def bump_session_version(user_id: int) -> int:
    """Increment ``user.session_version`` in the DB, sync the cache.

    Returns the new version. Lower-level than ``invalidate_session`` —
    skips the audit event so callers that already write their own audit
    (e.g. a "change password" controller) don't double-log. Most
    callers should use ``invalidate_session`` instead.
    """
    User = get_model('User')
    user_obj = await User.get_or_none(id=user_id)
    if user_obj is None:
        raise ValueError(f'Cannot bump session_version: user {user_id} does not exist')

    current = int(getattr(user_obj, 'session_version', 0))
    new_version = current + 1
    user_obj.session_version = new_version
    await user_obj.save(update_fields=['session_version'])

    # Sync the cache so the next gated request sees the new version
    # without a DB round-trip. Best-effort: if the cache is down, the
    # next request will repopulate from the DB anyway.
    try:
        await cache_set(_version_key(user_id), new_version)
    except Exception as exc:
        _log.warning('Session guard cache update after bump failed for user %s: %s', user_id, exc)

    return new_version


async def invalidate_session(
    user_id: int,
    *,
    request: Request | None = None,
) -> int:
    """Revoke all live sessions for ``user_id``. Returns the new version.

    This is the public entry point for "log out everywhere", "password
    changed → kill old sessions", and admin-initiated revocation.
    Compared to ``bump_session_version``, this also writes an audit
    event ``session.invalidated`` for forensic trail. Call from a
    request handler when possible — passing the request lets the audit
    log capture the actor, IP, and request_id. Background callers (CLI
    revoke, scheduled cleanup) can pass ``request=None`` to skip the
    audit event; in that case the caller is responsible for its own
    trail.
    """
    new_version = await bump_session_version(user_id)
    if request is not None:
        audit(
            request,
            'session.invalidated',
            model_name='User',
            record_id=str(user_id),
            changes={'new_version': new_version},
        )
    return new_version


def configure_session_guard() -> None:
    """Boot-time validation. Call from the ASGI lifespan after model
    registration. If ``SESSION_VERSION_CHECK = True`` and the User
    model lacks ``session_version``, raise ``RuntimeError`` with the
    exact migration to apply.

    Loud failure is intentional. The alternative — silently
    degrading to "always allow" — would let a project ship with the
    feature flag flipped on but the field missing, in which case the
    revocation channel never works AND the project has no signal that
    something is wrong. The boot-time check makes the misconfiguration
    impossible to miss.
    """
    if not config.get('SESSION_VERSION_CHECK', False):
        return

    try:
        User = get_model('User')
    except LookupError as exc:
        raise RuntimeError(
            'SESSION_VERSION_CHECK is enabled but no User model is registered. '
            'Either register a User model in rootsystem/application/models/__init__.py '
            "via register_model('User', User), or set SESSION_VERSION_CHECK = False "
            'in settings.py.'
        ) from exc

    fields_map: dict[str, Any] = getattr(getattr(User, '_meta', None), 'fields_map', {}) or {}
    if 'session_version' not in fields_map:
        raise RuntimeError(
            'SESSION_VERSION_CHECK is enabled but the User model has no '
            "'session_version' field. Add the column and run the migration:\n\n"
            '  # models/user.py\n'
            '  class User(NoriModelMixin, Model):\n'
            '      session_version = fields.IntField(default=0)\n'
            '      # ... existing fields ...\n\n'
            '  # Then:\n'
            "  python3 nori.py migrate:make 'add session_version to user'\n"
            '  python3 nori.py migrate:upgrade\n\n'
            'Or set SESSION_VERSION_CHECK = False in settings.py to disable '
            'the feature.'
        )
