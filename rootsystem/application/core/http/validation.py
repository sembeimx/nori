"""
Validacion declarativa con reglas pipe-separated.

    errors = validate(data, {
        'email': 'required|email|max:255',
        'password': 'required|min:8',
    })
    # {} = valido, {'field': ['msg', ...]} = errores

    # Con mensajes custom:
    errors = validate(data, rules, {
        'email.required': 'El correo es obligatorio',
        'password.min': 'La clave debe tener al menos 8 caracteres',
    })
"""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

_DEFAULT_MESSAGES = {
    'required': '{field} es obligatorio',
    'min': '{field} debe tener al menos {n} caracteres',
    'max': '{field} debe tener como maximo {n} caracteres',
    'email': '{field} debe ser un email valido',
    'numeric': '{field} debe ser numerico',
    'matches': '{field} debe coincidir con {param}',
    'in': '{field} debe ser uno de: {options}',
    'file': '{field} debe ser un archivo valido',
    'file_max': '{field} excede el tamaño maximo de {size}',
    'file_types': '{field} debe ser de tipo: {types}',
}


def _parse_size(size_str: str) -> int:
    """Parse size string like '5mb', '500kb', '1024' into bytes."""
    size_str = size_str.strip().lower()
    if size_str.endswith('mb'):
        return int(float(size_str[:-2]) * 1024 * 1024)
    if size_str.endswith('kb'):
        return int(float(size_str[:-2]) * 1024)
    return int(size_str)


def validate(
    data: dict[str, object],
    rules: dict[str, str | list[str]],
    messages: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """
    Valida un dict de datos contra reglas declarativas.

    Args:
        data: dict de field_name -> value (de request.form())
        rules: dict de field_name -> reglas (string pipe-separated o lista)
        messages: dict opcional de 'field.rule' -> mensaje custom

    Returns:
        dict de field_name -> lista de errores. Vacio = valido.
    """
    errors: dict[str, list[str]] = {}

    for field, field_rules in rules.items():
        if isinstance(field_rules, str):
            field_rules = field_rules.split('|')

        value_raw = data.get(field)
        value = ''
        if value_raw is not None:
            value = str(value_raw)

        field_errors: list[str] = []

        for rule in field_rules:
            rule = rule.strip()
            if not rule:
                continue

            param: str | None = None
            if ':' in rule:
                rule, param = rule.split(':', 1)

            msg = _check_rule(rule, param, field, value, data, messages, value_raw)
            if msg:
                field_errors.append(msg)
                if rule == 'required':
                    break

        if field_errors:
            errors[field] = field_errors

    return errors


def _check_rule(
    rule: str,
    param: str | None,
    field: str,
    value: str,
    data: dict[str, object],
    messages: dict[str, str] | None,
    value_raw: object = None,
) -> str | None:
    if rule == 'required':
        if not value.strip():
            return _msg(field, rule, messages)

    elif rule == 'min':
        n = int(param)
        if value and len(value) < n:
            return _msg(field, rule, messages, n=n)

    elif rule == 'max':
        n = int(param)
        if value and len(value) > n:
            return _msg(field, rule, messages, n=n)

    elif rule == 'email':
        if value and not _EMAIL_RE.match(value):
            return _msg(field, rule, messages)

    elif rule == 'numeric':
        if value and not value.replace('.', '', 1).replace('-', '', 1).isdigit():
            return _msg(field, rule, messages)

    elif rule == 'matches':
        other_value = str(data.get(param, ''))
        if value != other_value:
            return _msg(field, rule, messages, param=param)

    elif rule == 'in':
        options = [o.strip() for o in param.split(',')]
        if value and value not in options:
            return _msg(field, rule, messages, options=', '.join(options))

    # File validation rules (operate on value_raw)
    elif rule == 'file':
        if value_raw is not None and not hasattr(value_raw, 'filename'):
            return _msg(field, rule, messages)

    elif rule == 'file_max':
        if value_raw is not None and hasattr(value_raw, 'size'):
            max_bytes = _parse_size(param)
            if value_raw.size > max_bytes:
                return _msg(field, rule, messages, size=param)

    elif rule == 'file_types':
        if value_raw is not None and hasattr(value_raw, 'filename'):
            allowed = [t.strip().lower() for t in param.split(',')]
            filename = value_raw.filename or ''
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in allowed:
                return _msg(field, rule, messages, types=param)

    return None


def _msg(
    field: str,
    rule: str,
    messages: dict[str, str] | None,
    **kwargs: object,
) -> str:
    """Resuelve el mensaje: custom (field.rule) > default."""
    if messages and f'{field}.{rule}' in messages:
        return messages[f'{field}.{rule}']
    template = _DEFAULT_MESSAGES[rule]
    return template.format(field=field, **kwargs)
