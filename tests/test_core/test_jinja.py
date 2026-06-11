"""Tests for core.jinja template globals.

WU-1 additions: RED tests for csrf_field(request) and csrf_token(request)
signatures. These will fail against the session-based implementation and pass
after WU-2.
"""

from __future__ import annotations

from core.jinja import templates


def test_csrf_field_registered_as_global():
    """csrf_field should be available in Jinja2 templates."""
    assert 'csrf_field' in templates.env.globals


def test_get_flashed_messages_registered_as_global():
    """get_flashed_messages should be available in Jinja2 templates."""
    assert 'get_flashed_messages' in templates.env.globals


def test_csrf_field_callable():
    """The registered csrf_field should be callable."""
    assert callable(templates.env.globals['csrf_field'])


def test_get_flashed_messages_callable():
    """The registered get_flashed_messages should be callable."""
    assert callable(templates.env.globals['get_flashed_messages'])


# ---------------------------------------------------------------------------
# RED tests — new request-accepting signature (WU-1)
# REQ-CSRF-009, REQ-CSRF-010
# ---------------------------------------------------------------------------


def test_csrf_field_accepts_request():
    """csrf_field(request) reads request.cookies and emits a masked hidden input.

    REQ-CSRF-009: the function accepts a request object, not a session dict.
    """
    import hmac

    from core.auth.csrf import csrf_field
    from core.auth.security import Security

    nonce = Security.generate_csrf_token()
    import settings

    sig = hmac.new(settings.SECRET_KEY.encode(), nonce.encode(), 'sha256').hexdigest()
    cookie_val = f'{nonce}.{sig}'

    class _FakeRequest:
        cookies = {'csrftoken': cookie_val}
        scope: dict = {}

    html = csrf_field(_FakeRequest())
    assert 'name="_csrf_token"' in html
    assert '<input' in html
    # Value must be the BREACH-masked form, not the raw cookie value
    assert f'value="{cookie_val}"' not in html, (
        'csrf_field(request) must return a masked token, not the raw cookie value'
    )


def test_csrf_field_uses_pending_cookie_when_no_cookie():
    """On first GET (no cookie), csrf_field uses scope['csrf_pending_cookie'].

    REQ-CSRF-009: first-request coordination via scope seam.
    """
    import hmac

    import settings
    from core.auth.csrf import csrf_field
    from core.auth.security import Security

    nonce = Security.generate_csrf_token()
    sig = hmac.new(settings.SECRET_KEY.encode(), nonce.encode(), 'sha256').hexdigest()
    cookie_val = f'{nonce}.{sig}'

    class _FakeRequest:
        cookies: dict = {}  # no cookie in request
        scope = {'csrf_pending_cookie': cookie_val}

    html = csrf_field(_FakeRequest())
    assert 'name="_csrf_token"' in html
    assert html != '<input type="hidden" name="_csrf_token" value="">', (
        'csrf_field must use scope[csrf_pending_cookie] when no cookie is present'
    )


def test_csrf_token_returns_raw_cookie_value():
    """csrf_token(request) returns the raw {nonce}.{sig} verbatim (not masked, not HMAC-only).

    REQ-CSRF-010.
    """
    import hmac

    import settings
    from core.auth.csrf import csrf_token
    from core.auth.security import Security

    nonce = Security.generate_csrf_token()
    sig = hmac.new(settings.SECRET_KEY.encode(), nonce.encode(), 'sha256').hexdigest()
    cookie_val = f'{nonce}.{sig}'

    class _FakeRequest:
        cookies = {'csrftoken': cookie_val}
        scope: dict = {}

    result = csrf_token(_FakeRequest())
    assert result == cookie_val, f'csrf_token(request) must return the raw cookie value {cookie_val!r}; got {result!r}'


def test_csrf_token_returns_pending_cookie_on_first_visit():
    """No cookie + scope['csrf_pending_cookie'] -> csrf_token returns that value.

    REQ-CSRF-010.
    """
    import hmac

    import settings
    from core.auth.csrf import csrf_token
    from core.auth.security import Security

    nonce = Security.generate_csrf_token()
    sig = hmac.new(settings.SECRET_KEY.encode(), nonce.encode(), 'sha256').hexdigest()
    cookie_val = f'{nonce}.{sig}'

    class _FakeRequest:
        cookies: dict = {}
        scope = {'csrf_pending_cookie': cookie_val}

    result = csrf_token(_FakeRequest())
    assert result == cookie_val


# ---------------------------------------------------------------------------
# REQ-CSRF-012, design §5 — custom CSRF_COOKIE_NAME reaches base.html so the
# JS shim reads it from window.NORI_CSRF_COOKIE_NAME (no hard-coded name).
# ---------------------------------------------------------------------------


def test_csrf_cookie_name_global_is_registered():
    """csrf_cookie_name is exposed as a Jinja global for base.html to render."""
    assert 'csrf_cookie_name' in templates.env.globals
    assert callable(templates.env.globals['csrf_cookie_name'])


def test_custom_csrf_cookie_name_reaches_rendered_base_html(monkeypatch):
    """A custom CSRF_COOKIE_NAME (e.g. __Host-csrftoken) is rendered into base.html's
    window.NORI_CSRF_COOKIE_NAME global, BEFORE the csrf.js include.

    Pins Finding 2: the shim no longer hard-codes 'csrftoken' — base.html renders the
    configured name so the shim tracks the operator's __Host-csrftoken choice.
    """
    from core.auth import csrf as csrf_module

    monkeypatch.setattr(csrf_module, '_cookie_name', lambda: '__Host-csrftoken')

    template = templates.env.get_template('base.html')
    rendered = template.render(request=type('R', (), {'session': {}})())

    # The configured name appears in the rendered global assignment.
    assert '__Host-csrftoken' in rendered
    assert 'window.NORI_CSRF_COOKIE_NAME' in rendered

    # The global is rendered BEFORE the csrf.js include so it is set when the shim runs.
    global_pos = rendered.index('window.NORI_CSRF_COOKIE_NAME')
    include_pos = rendered.index('<script src="/static/js/csrf.js"')
    assert global_pos < include_pos, 'window.NORI_CSRF_COOKIE_NAME must be rendered before the csrf.js include'


def test_default_csrf_cookie_name_reaches_rendered_base_html():
    """With no override, base.html renders the default 'csrftoken' name."""
    template = templates.env.get_template('base.html')
    rendered = template.render(request=type('R', (), {'session': {}})())
    assert '"csrftoken"' in rendered
    assert 'window.NORI_CSRF_COOKIE_NAME' in rendered
