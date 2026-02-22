"""Tests for core.mail._build_message (no SMTP connection needed)."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../rootsystem/application')))

from core.mail import _build_message


def test_build_message_html_only():
    """HTML-only message has correct structure."""
    msg = _build_message('user@test.com', 'Hello', '<h1>Hi</h1>')
    assert msg['Subject'] == 'Hello'
    assert msg['To'] == 'user@test.com'
    parts = msg.get_payload()
    assert len(parts) == 1
    assert parts[0].get_content_type() == 'text/html'


def test_build_message_with_text_fallback():
    """Message with text fallback has both parts."""
    msg = _build_message('user@test.com', 'Hello', '<h1>Hi</h1>', body_text='Hi')
    parts = msg.get_payload()
    assert len(parts) == 2
    assert parts[0].get_content_type() == 'text/plain'
    assert parts[1].get_content_type() == 'text/html'


def test_build_message_multiple_recipients():
    """Multiple recipients are joined with comma."""
    msg = _build_message(['a@test.com', 'b@test.com'], 'Hello', '<p>Hi</p>')
    assert msg['To'] == 'a@test.com, b@test.com'


def test_build_message_mime_structure():
    """Message is multipart/alternative."""
    msg = _build_message('user@test.com', 'Test', '<p>test</p>')
    assert msg.get_content_type() == 'multipart/alternative'
