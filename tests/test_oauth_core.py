"""Tests for core.auth.oauth — OAuth state and PKCE helpers."""
from __future__ import annotations

import base64
import hashlib

from core.auth.oauth import (
    generate_state,
    validate_state,
    generate_pkce_verifier,
    get_pkce_verifier,
    _STATE_SESSION_KEY,
    _PKCE_SESSION_KEY,
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
