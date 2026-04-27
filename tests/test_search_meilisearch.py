"""Tests for services.search_meilisearch — Meilisearch filter builder.

These tests cover the filter string conversion logic that is specific
to the Meilisearch driver. The driver's HTTP calls are not tested here
(they require a running Meilisearch instance or full HTTP mocking).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from services.search_meilisearch import _build_filter_string


def test_build_filter_string_empty():
    """Empty filters dict returns None (no filter applied)."""
    assert _build_filter_string({}) is None


def test_build_filter_string_single():
    """A single key-value pair becomes 'key = \"value\"'."""
    assert _build_filter_string({'status': 'published'}) == 'status = "published"'


def test_build_filter_string_multiple():
    """Multiple key-value pairs are joined with AND."""
    result = _build_filter_string({'status': 'published', 'lang': 'en'})
    assert 'status = "published"' in result
    assert 'lang = "en"' in result
    assert ' AND ' in result


def test_build_filter_string_raw():
    """The _raw key passes the value through as-is for advanced expressions."""
    raw = 'price > 10 AND price < 50'
    assert _build_filter_string({'_raw': raw}) == raw
