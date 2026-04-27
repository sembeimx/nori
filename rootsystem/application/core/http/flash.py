"""
Flash messages -- temporary session-based feedback.

    from core.http.flash import flash, get_flashed_messages

    flash(request, 'Product created')
    flash(request, 'Failed to save', 'error')
"""

from __future__ import annotations


def flash(request, message: str, category: str = 'success') -> None:
    """Add a flash message to the session."""
    if '_flash_messages' not in request.session:
        request.session['_flash_messages'] = []
    request.session['_flash_messages'].append(
        {
            'message': message,
            'category': category,
        }
    )


def get_flashed_messages(session) -> list[dict[str, str]]:
    """Return and clear all flash messages (one-time read)."""
    return session.pop('_flash_messages', [])
