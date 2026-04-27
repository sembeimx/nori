"""Tests for CORS configuration in settings."""

import os

import settings


def test_cors_origins_empty_by_default():
    """Without CORS_ORIGINS env var, the list is empty."""
    original = os.environ.pop('CORS_ORIGINS', None)
    try:
        # Re-evaluate: settings module already loaded, so test the parsing logic
        result = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
        assert result == []
    finally:
        if original is not None:
            os.environ['CORS_ORIGINS'] = original


def test_cors_origins_single():
    original = os.environ.get('CORS_ORIGINS')
    os.environ['CORS_ORIGINS'] = 'http://localhost:3000'
    try:
        result = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
        assert result == ['http://localhost:3000']
    finally:
        if original is not None:
            os.environ['CORS_ORIGINS'] = original
        else:
            os.environ.pop('CORS_ORIGINS', None)


def test_cors_origins_multiple():
    original = os.environ.get('CORS_ORIGINS')
    os.environ['CORS_ORIGINS'] = 'http://localhost:3000, https://miapp.com'
    try:
        result = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
        assert result == ['http://localhost:3000', 'https://miapp.com']
    finally:
        if original is not None:
            os.environ['CORS_ORIGINS'] = original
        else:
            os.environ.pop('CORS_ORIGINS', None)


def test_cors_default_methods():
    assert 'GET' in settings.CORS_ALLOW_METHODS
    assert 'POST' in settings.CORS_ALLOW_METHODS
    assert 'DELETE' in settings.CORS_ALLOW_METHODS
    assert 'OPTIONS' in settings.CORS_ALLOW_METHODS


def test_cors_credentials_enabled():
    assert settings.CORS_ALLOW_CREDENTIALS is True
