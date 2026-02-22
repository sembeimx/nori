"""
Flash messages — feedback temporal via sesion.

    from core.http.flash import flash, get_flashed_messages

    flash(request, 'Producto creado')
    flash(request, 'Error al guardar', 'error')
"""
from __future__ import annotations


def flash(request, message: str, category: str = 'success') -> None:
    """Agrega un mensaje flash a la sesion."""
    if '_flash_messages' not in request.session:
        request.session['_flash_messages'] = []
    request.session['_flash_messages'].append({
        'message': message,
        'category': category,
    })


def get_flashed_messages(session) -> list[dict[str, str]]:
    """Retorna y elimina todos los mensajes flash (lectura unica)."""
    return session.pop('_flash_messages', [])
