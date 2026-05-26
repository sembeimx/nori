"""Tests for core.auth.oauth — OAuth state and PKCE helpers."""

from __future__ import annotations

import base64
import hashlib

from core.auth.oauth import (
    _PKCE_SESSION_KEY,
    _STATE_SESSION_KEY,
    generate_pkce_verifier,
    generate_state,
    get_pkce_verifier,
    validate_state,
)

# -- generate_state / validate_state ----------------------------------------


def test_generate_state_returns_nonempty_string():
    session: dict = {}
    state = generate_state(session)
    assert isinstance(state, str)
    assert len(state) > 0


def test_generate_state_stores_in_session():
    session: dict = {}
    state = generate_state(session)
    assert session[_STATE_SESSION_KEY] == state


def test_generate_state_replaces_previous():
    session: dict = {}
    first = generate_state(session)
    second = generate_state(session)
    assert first != second
    assert session[_STATE_SESSION_KEY] == second


def test_validate_state_success():
    session: dict = {}
    state = generate_state(session)
    assert validate_state(session, state) is True


def test_validate_state_consumes_token():
    session: dict = {}
    state = generate_state(session)
    validate_state(session, state)
    assert _STATE_SESSION_KEY not in session


def test_validate_state_single_use():
    session: dict = {}
    state = generate_state(session)
    assert validate_state(session, state) is True
    assert validate_state(session, state) is False


def test_validate_state_wrong_token():
    session: dict = {}
    generate_state(session)
    assert validate_state(session, 'wrong-token') is False


def test_validate_state_missing_session_key():
    session: dict = {}
    assert validate_state(session, 'any-token') is False


def test_validate_state_empty_string():
    session: dict = {}
    generate_state(session)
    assert validate_state(session, '') is False


def test_validate_state_consumes_on_failure():
    """State is removed from session even on failed validation."""
    session: dict = {}
    generate_state(session)
    validate_state(session, 'wrong')
    assert _STATE_SESSION_KEY not in session


# -- generate_pkce_verifier / get_pkce_verifier ------------------------------


def test_pkce_verifier_format():
    session: dict = {}
    verifier, challenge = generate_pkce_verifier(session)
    assert isinstance(verifier, str)
    assert 43 <= len(verifier) <= 128
    assert isinstance(challenge, str)
    assert len(challenge) > 0


def test_pkce_challenge_matches_rfc7636():
    """Verify challenge == BASE64URL(SHA256(verifier)) without padding."""
    session: dict = {}
    verifier, challenge = generate_pkce_verifier(session)
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    assert challenge == expected


def test_pkce_verifier_stores_in_session():
    session: dict = {}
    verifier, _ = generate_pkce_verifier(session)
    assert session[_PKCE_SESSION_KEY] == verifier


def test_get_pkce_verifier_returns_and_consumes():
    session: dict = {}
    verifier, _ = generate_pkce_verifier(session)
    retrieved = get_pkce_verifier(session)
    assert retrieved == verifier
    assert _PKCE_SESSION_KEY not in session


def test_get_pkce_verifier_missing():
    session: dict = {}
    assert get_pkce_verifier(session) is None


def test_get_pkce_verifier_single_use():
    session: dict = {}
    generate_pkce_verifier(session)
    first = get_pkce_verifier(session)
    second = get_pkce_verifier(session)
    assert first is not None
    assert second is None


# -- raise_for_status_logged ------------------------------------------------


def test_raise_for_status_logged_noop_on_success(caplog):
    """A 2xx response passes through silently — no log, no raise."""
    import logging
    from unittest.mock import MagicMock

    from core.auth.oauth import raise_for_status_logged

    response = MagicMock()
    response.raise_for_status = MagicMock(return_value=None)
    response.status_code = 200

    logging.getLogger('nori').propagate = True
    with caplog.at_level(logging.WARNING, logger='nori.oauth'):
        raise_for_status_logged(response, 'github', 'token exchange')

    assert caplog.records == [], 'no log expected on 2xx'


def test_raise_for_status_logged_logs_and_reraises_on_4xx(caplog):
    """On HTTPStatusError, a WARNING with provider, stage, status, and a
    truncated body is emitted BEFORE re-raising. The contract for OAuth
    drivers is that the error keeps propagating to the caller — the log
    is purely operational debuggability (audit 2026-05-25 #4)."""
    import logging
    from unittest.mock import MagicMock

    import httpx
    import pytest as _pytest
    from core.auth.oauth import raise_for_status_logged

    response = MagicMock()
    response.status_code = 400
    response.text = 'bad_verification_code: The provided code is invalid.'
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            message='400 Bad Request',
            request=MagicMock(),
            response=response,
        )
    )

    logging.getLogger('nori').propagate = True
    with caplog.at_level(logging.WARNING, logger='nori.oauth'):
        with _pytest.raises(httpx.HTTPStatusError):
            raise_for_status_logged(response, 'github', 'token exchange')

    matching = [r for r in caplog.records if 'OAuth github token exchange failed' in r.getMessage()]
    assert matching, 'expected a WARNING that names the provider and the stage'
    msg = matching[0].getMessage()
    assert '400' in msg, 'log must include the HTTP status code'
    assert 'bad_verification_code' in msg, 'log must include a truncated response body for debugging'


def test_raise_for_status_logged_truncates_long_body(caplog):
    """The logged body is capped at 200 chars so a 10MB error page does not
    flood the log line."""
    import logging
    from unittest.mock import MagicMock

    import httpx
    import pytest as _pytest
    from core.auth.oauth import raise_for_status_logged

    response = MagicMock()
    response.status_code = 500
    response.text = 'A' * 5000
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            message='500 Internal Server Error',
            request=MagicMock(),
            response=response,
        )
    )

    logging.getLogger('nori').propagate = True
    with caplog.at_level(logging.WARNING, logger='nori.oauth'):
        with _pytest.raises(httpx.HTTPStatusError):
            raise_for_status_logged(response, 'google', 'user info')

    msg = next(r.getMessage() for r in caplog.records if 'OAuth google user info failed' in r.getMessage())
    # The body slice is 200 chars; the log format adds the prefix, so the
    # total line stays well under 1KB regardless of upstream response size.
    body_in_msg = msg.split(' — ', 1)[1]
    assert len(body_in_msg) <= 250
