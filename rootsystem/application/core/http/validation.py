"""
Declarative validation with pipe-separated rules.

    errors = validate(data, {
        'email': 'required|email|max:255',
        'password': 'required|min:8',
    })
    # {} = valid, {'field': ['msg', ...]} = errors

    # With custom messages:
    errors = validate(data, rules, {
        'email.required': 'Email is mandatory',
        'password.min': 'Password must be at least 8 characters',
    })

    # Async validation (for rules like unique):
    errors = await validate_async(data, {
        'email': 'required|email|unique:users,email',
    })
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9][a-zA-Z0-9_%+-]*'  # first char + allowed chars (no leading dot)
    r'(\.[a-zA-Z0-9][a-zA-Z0-9_%+-]*)*'  # optional groups starting with single dot (no consecutive dots)
    r'@'
    r'[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*'
    r'\.[a-zA-Z]{2,}$'
)

_URL_RE = re.compile(
    r'^https?://'
    r'[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?'
    r'(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*'
    r'(:\d{1,5})?'
    r'(/[^\s]*)?$'
)

_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

_DEFAULT_MESSAGES = {
    'required': '{field} is required',
    'min': '{field} must be at least {n} characters',
    'max': '{field} must be at most {n} characters',
    'email': '{field} must be a valid email',
    'numeric': '{field} must be numeric',
    'matches': '{field} must match {param}',
    'in': '{field} must be one of: {options}',
    'url': '{field} must be a valid URL',
    'date': '{field} must be a valid date (YYYY-MM-DD)',
    'confirmed': '{field} confirmation does not match',
    'nullable': '',
    'array': '{field} must be a list',
    'min_value': '{field} must be at least {n}',
    'max_value': '{field} must be at most {n}',
    'regex': '{field} format is invalid',
    'file': '{field} must be a valid file',
    'file_max': '{field} exceeds maximum size of {size}',
    'file_types': '{field} must be of type: {types}',
    'unique': '{field} has already been taken',
}


def _parse_size(size_str: str) -> int:
    """Parse size string like '5mb', '500kb', '1024' into bytes."""
    size_str = size_str.strip().lower()
    if size_str.endswith('mb'):
        num = size_str[:-2].strip()
        if not num:
            raise ValueError(f"Invalid size: '{size_str}'")
        result = int(float(num) * 1024 * 1024)
    elif size_str.endswith('kb'):
        num = size_str[:-2].strip()
        if not num:
            raise ValueError(f"Invalid size: '{size_str}'")
        result = int(float(num) * 1024)
    else:
        result = int(size_str)
    if result <= 0:
        raise ValueError(f"Size must be positive: '{size_str}'")
    return result


def validate(
    data: dict[str, object],
    rules: dict[str, str | list[str]],
    messages: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """
    Validates a data dict against declarative rules.

    Args:
        data: dict of field_name -> value (from request.form())
        rules: dict of field_name -> rules (pipe-separated string or list)
        messages: optional dict of 'field.rule' -> custom message

    Returns:
        dict of field_name -> list of errors. Empty = valid.
    """
    errors: dict[str, list[str]] = {}

    for field, field_rules in rules.items():
        if isinstance(field_rules, str):
            field_rules = field_rules.split('|')

        value_raw = data.get(field)
        value = ''
        if value_raw is not None:
            value = str(value_raw)

        # nullable: skip all rules if value is empty/missing
        if 'nullable' in field_rules and not value.strip():
            continue

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
        try:
            n = int(param)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid parameter for 'min' rule: '{param}'") from None
        if value and len(value) < n:
            return _msg(field, rule, messages, n=n)

    elif rule == 'max':
        try:
            n = int(param)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid parameter for 'max' rule: '{param}'") from None
        if value and len(value) > n:
            return _msg(field, rule, messages, n=n)

    elif rule == 'email':
        if value and not _EMAIL_RE.match(value):
            return _msg(field, rule, messages)

    elif rule == 'numeric':
        if value:
            try:
                f = float(value)
                import math

                if math.isinf(f) or math.isnan(f):
                    return _msg(field, rule, messages)
            except ValueError:
                return _msg(field, rule, messages)

    elif rule == 'matches':
        other_value = str(data.get(param, ''))
        if value != other_value:
            return _msg(field, rule, messages, param=param)

    elif rule == 'in':
        options = [o.strip() for o in param.split(',')]
        if value and value not in options:
            return _msg(field, rule, messages, options=', '.join(options))

    elif rule == 'url':
        if value and not _URL_RE.match(value):
            return _msg(field, rule, messages)

    elif rule == 'date':
        if value:
            from datetime import date as _date

            try:
                _date.fromisoformat(value)
            except ValueError:
                return _msg(field, rule, messages)

    elif rule == 'confirmed':
        confirm_value = str(data.get(f'{field}_confirmation', ''))
        if value != confirm_value:
            return _msg(field, rule, messages)

    elif rule == 'nullable':
        pass  # handled in the validate() loop

    elif rule == 'unique':
        pass  # handled in validate_async()

    elif rule == 'array':
        if value_raw is not None and not isinstance(value_raw, list):
            return _msg(field, rule, messages)

    elif rule == 'min_value':
        try:
            n = float(param)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid parameter for 'min_value' rule: '{param}'") from None
        if value:
            try:
                if float(value) < n:
                    return _msg(field, rule, messages, n=param)
            except ValueError:
                return _msg(field, rule, messages, n=param)

    elif rule == 'max_value':
        try:
            n = float(param)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid parameter for 'max_value' rule: '{param}'") from None
        if value:
            try:
                if float(value) > n:
                    return _msg(field, rule, messages, n=param)
            except ValueError:
                return _msg(field, rule, messages, n=param)

    elif rule == 'regex':
        if value and not re.match(param, value):
            return _msg(field, rule, messages)

    # File validation rules (operate on value_raw)
    elif rule == 'file':
        if value_raw is not None and not hasattr(value_raw, 'filename'):
            return _msg(field, rule, messages)

    elif rule == 'file_max':
        if value_raw is not None and hasattr(value_raw, 'filename'):
            try:
                max_bytes = _parse_size(param)
            except ValueError:
                return _msg(field, rule, messages, size=param)
            file_size = getattr(value_raw, 'size', None)
            if file_size is not None and file_size > max_bytes:
                return _msg(field, rule, messages, size=param)

    elif rule == 'file_types':
        if value_raw is not None and hasattr(value_raw, 'filename'):
            allowed = [t.strip().lower() for t in param.split(',')]
            filename = value_raw.filename or ''
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext not in allowed:
                return _msg(field, rule, messages, types=param)

    return None


async def validate_async(
    data: dict[str, object],
    rules: dict[str, str | list[str]],
    messages: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """
    Async variant of validate() that supports database-dependent rules.

    Runs all synchronous rules first via validate(), then checks async
    rules (``unique``) only for fields that passed synchronous validation.

    The ``unique`` rule checks that a value does not already exist in the
    database.  Syntax::

        'unique:table,column'              # basic uniqueness check
        'unique:table,column,except_value' # exclude a row by primary key

    Args:
        data: dict of field_name -> value (from request.form())
        rules: dict of field_name -> rules (pipe-separated string or list)
        messages: optional dict of 'field.rule' -> custom message

    Returns:
        dict of field_name -> list of errors. Empty = valid.
    """
    errors = validate(data, rules, messages)

    for field, field_rules in rules.items():
        if field in errors:
            continue

        if isinstance(field_rules, str):
            field_rules = field_rules.split('|')

        value_raw = data.get(field)
        value = str(value_raw) if value_raw is not None else ''

        if 'nullable' in field_rules and not value.strip():
            continue

        for rule in field_rules:
            rule = rule.strip()
            if not rule:
                continue

            param: str | None = None
            if ':' in rule:
                rule, param = rule.split(':', 1)

            if rule == 'unique' and value.strip():
                msg = await _check_unique(param, field, value, messages)
                if msg:
                    errors.setdefault(field, []).append(msg)

    return errors


async def _check_unique(
    param: str | None,
    field: str,
    value: str,
    messages: dict[str, str] | None,
) -> str | None:
    """Check uniqueness against the database via Tortoise connection."""
    if not param:
        raise ValueError("'unique' rule requires parameters: unique:table,column")

    parts = param.split(',')
    if len(parts) < 2:
        raise ValueError(f"'unique' rule requires at least table and column: unique:table,column — got: '{param}'")

    table = parts[0].strip()
    column = parts[1].strip()
    except_id = parts[2].strip() if len(parts) > 2 else None

    if not _IDENTIFIER_RE.match(table):
        raise ValueError(f"Invalid table name: '{table}'")
    if not _IDENTIFIER_RE.match(column):
        raise ValueError(f"Invalid column name: '{column}'")

    from tortoise import connections

    conn = connections.get('default')

    if except_id:
        sql = f'SELECT COUNT(*) AS cnt FROM {table} WHERE {column} = $1 AND id != $2'
        _, result = await conn.execute_query(sql, [value, except_id])
    else:
        sql = f'SELECT COUNT(*) AS cnt FROM {table} WHERE {column} = $1'
        _, result = await conn.execute_query(sql, [value])

    count = result[0]['cnt'] if result else 0
    if count > 0:
        return _msg(field, 'unique', messages)
    return None


def _msg(
    field: str,
    rule: str,
    messages: dict[str, str] | None,
    **kwargs: object,
) -> str:
    """Resolves the message: custom (field.rule) > default."""
    if messages and f'{field}.{rule}' in messages:
        return messages[f'{field}.{rule}']
    template = _DEFAULT_MESSAGES[rule]
    return template.format(field=field, **kwargs)
