"""Tests for core.http.validation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.http.validation import validate, validate_async

# --- required ---


def test_required_missing():
    errors = validate({}, {'name': 'required'})
    assert 'name' in errors
    assert 'is required' in errors['name'][0]


def test_required_empty_string():
    errors = validate({'name': '   '}, {'name': 'required'})
    assert 'name' in errors


def test_required_present():
    errors = validate({'name': 'Alice'}, {'name': 'required'})
    assert errors == {}


# --- min / max ---


def test_min_too_short():
    errors = validate({'pw': '123'}, {'pw': 'required|min:6'})
    assert 'pw' in errors
    assert 'at least 6' in errors['pw'][0]


def test_min_ok():
    errors = validate({'pw': '123456'}, {'pw': 'required|min:6'})
    assert errors == {}


def test_max_too_long():
    errors = validate({'name': 'a' * 10}, {'name': 'required|max:5'})
    assert 'name' in errors
    assert 'at most 5' in errors['name'][0]


def test_max_ok():
    errors = validate({'name': 'hello'}, {'name': 'required|max:10'})
    assert errors == {}


# --- email ---


def test_email_valid():
    errors = validate({'email': 'user@example.com'}, {'email': 'required|email'})
    assert errors == {}


def test_email_invalid():
    errors = validate({'email': 'not-an-email'}, {'email': 'required|email'})
    assert 'email' in errors


def test_email_missing_domain():
    errors = validate({'email': 'user@'}, {'email': 'required|email'})
    assert 'email' in errors


# --- numeric ---


def test_numeric_valid():
    errors = validate({'price': '19.99'}, {'price': 'required|numeric'})
    assert errors == {}


def test_numeric_integer():
    errors = validate({'qty': '42'}, {'qty': 'required|numeric'})
    assert errors == {}


def test_numeric_invalid():
    errors = validate({'price': 'abc'}, {'price': 'required|numeric'})
    assert 'price' in errors


# --- matches ---


def test_matches_ok():
    data = {'password': 'secret', 'confirm': 'secret'}
    errors = validate(data, {'confirm': 'required|matches:password'})
    assert errors == {}


def test_matches_fail():
    data = {'password': 'secret', 'confirm': 'different'}
    errors = validate(data, {'confirm': 'required|matches:password'})
    assert 'confirm' in errors


# --- in ---


def test_in_valid():
    errors = validate({'role': 'admin'}, {'role': 'required|in:admin,user,editor'})
    assert errors == {}


def test_in_invalid():
    errors = validate({'role': 'hacker'}, {'role': 'required|in:admin,user,editor'})
    assert 'role' in errors
    assert 'one of' in errors['role'][0]


# --- multiple rules ---


def test_multiple_errors():
    errors = validate(
        {'email': 'x', 'pw': ''},
        {
            'email': 'required|email|max:255',
            'pw': 'required|min:8',
        },
    )
    assert 'email' in errors
    assert 'pw' in errors


def test_required_stops_chain():
    """When required fails, subsequent rules for that field are skipped."""
    errors = validate({'email': ''}, {'email': 'required|email|min:5'})
    assert len(errors['email']) == 1
    assert 'is required' in errors['email'][0]


# --- rules as list ---


def test_rules_as_list():
    errors = validate({'name': ''}, {'name': ['required', 'max:100']})
    assert 'name' in errors


# --- all valid ---


def test_all_valid():
    data = {
        'name': 'Alice',
        'email': 'alice@example.com',
        'password': 'strongpass',
    }
    rules = {
        'name': 'required|max:100',
        'email': 'required|email|max:255',
        'password': 'required|min:8',
    }
    assert validate(data, rules) == {}


# --- custom messages ---


def test_custom_message_overrides_default():
    errors = validate(
        {},
        {'email': 'required'},
        {
            'email.required': 'Email is mandatory',
        },
    )
    assert errors['email'][0] == 'Email is mandatory'


def test_custom_message_only_affects_target_field():
    errors = validate(
        {},
        {'email': 'required', 'name': 'required'},
        {
            'email.required': 'Email is mandatory',
        },
    )
    assert errors['email'][0] == 'Email is mandatory'
    assert 'is required' in errors['name'][0]
    assert errors['name'][0] != 'Email is mandatory'


# --- numeric edge cases ---


def test_numeric_rejects_infinity():
    errors = validate({'n': 'inf'}, {'n': 'required|numeric'})
    assert 'n' in errors


def test_numeric_rejects_nan():
    errors = validate({'n': 'nan'}, {'n': 'required|numeric'})
    assert 'n' in errors


def test_numeric_rejects_negative_infinity():
    errors = validate({'n': '-Infinity'}, {'n': 'required|numeric'})
    assert 'n' in errors


def test_numeric_accepts_negative():
    errors = validate({'n': '-42.5'}, {'n': 'required|numeric'})
    assert errors == {}


# --- email edge cases ---


def test_email_rejects_consecutive_dots():
    errors = validate({'email': 'user..name@example.com'}, {'email': 'required|email'})
    assert 'email' in errors


def test_email_rejects_leading_dot():
    errors = validate({'email': '.user@example.com'}, {'email': 'required|email'})
    assert 'email' in errors


def test_email_accepts_plus_tag():
    errors = validate({'email': 'user+tag@example.com'}, {'email': 'required|email'})
    assert errors == {}


# --- file_max edge cases ---


def test_file_max_rejects_negative_size():
    """Negative size in file_max rule raises ValueError."""
    import pytest as pt
    from core.http.validation import _parse_size

    with pt.raises(ValueError, match='positive'):
        _parse_size('-5mb')


def test_file_max_rejects_zero_size():
    import pytest as pt
    from core.http.validation import _parse_size

    with pt.raises(ValueError, match='positive'):
        _parse_size('0')


def test_file_max_invalid_size_returns_error():
    """file_max with an invalid size string should return a validation error, not crash."""

    class FakeFile:
        filename = 'test.jpg'
        size = 100

    errors = validate({'avatar': FakeFile()}, {'avatar': 'file|file_max:-5mb'})
    assert 'avatar' in errors


# --- url ---


def test_url_valid_http():
    errors = validate({'site': 'http://example.com'}, {'site': 'required|url'})
    assert errors == {}


def test_url_valid_https_with_path():
    errors = validate({'site': 'https://example.com/path?q=1'}, {'site': 'required|url'})
    assert errors == {}


def test_url_invalid_no_scheme():
    errors = validate({'site': 'example.com'}, {'site': 'required|url'})
    assert 'site' in errors


def test_url_invalid_ftp():
    errors = validate({'site': 'ftp://example.com'}, {'site': 'required|url'})
    assert 'site' in errors


def test_url_empty_skipped():
    errors = validate({'site': ''}, {'site': 'url'})
    assert errors == {}


# --- date ---


def test_date_valid_iso():
    errors = validate({'dob': '2024-01-15'}, {'dob': 'required|date'})
    assert errors == {}


def test_date_invalid_format():
    errors = validate({'dob': '15/01/2024'}, {'dob': 'required|date'})
    assert 'dob' in errors


def test_date_invalid_values():
    errors = validate({'dob': '2024-13-32'}, {'dob': 'required|date'})
    assert 'dob' in errors


def test_date_empty_skipped():
    errors = validate({'dob': ''}, {'dob': 'date'})
    assert errors == {}


# --- confirmed ---


def test_confirmed_match():
    data = {'password': 'secret123', 'password_confirmation': 'secret123'}
    errors = validate(data, {'password': 'required|confirmed'})
    assert errors == {}


def test_confirmed_mismatch():
    data = {'password': 'secret123', 'password_confirmation': 'different'}
    errors = validate(data, {'password': 'required|confirmed'})
    assert 'password' in errors


def test_confirmed_missing_confirmation_field():
    data = {'password': 'secret123'}
    errors = validate(data, {'password': 'required|confirmed'})
    assert 'password' in errors


# --- nullable ---


def test_nullable_skips_empty():
    errors = validate({'bio': ''}, {'bio': 'nullable|min:10'})
    assert errors == {}


def test_nullable_skips_missing():
    errors = validate({}, {'bio': 'nullable|min:10'})
    assert errors == {}


def test_nullable_still_validates_present():
    errors = validate({'bio': 'hi'}, {'bio': 'nullable|min:10'})
    assert 'bio' in errors


def test_nullable_valid_value():
    errors = validate({'bio': 'This is a long enough bio'}, {'bio': 'nullable|min:10'})
    assert errors == {}


# --- array ---


def test_array_valid():
    errors = validate({'tags': ['a', 'b']}, {'tags': 'required|array'})
    assert errors == {}


def test_array_invalid_string():
    errors = validate({'tags': 'not-a-list'}, {'tags': 'required|array'})
    assert 'tags' in errors


def test_array_none_skipped():
    errors = validate({}, {'tags': 'array'})
    assert errors == {}


# --- min_value / max_value ---


def test_min_value_valid():
    errors = validate({'age': '18'}, {'age': 'required|min_value:0'})
    assert errors == {}


def test_min_value_too_low():
    errors = validate({'age': '-1'}, {'age': 'required|min_value:0'})
    assert 'age' in errors
    assert 'at least' in errors['age'][0]


def test_min_value_float():
    errors = validate({'price': '9.99'}, {'price': 'required|min_value:5.5'})
    assert errors == {}


def test_min_value_non_numeric():
    errors = validate({'age': 'abc'}, {'age': 'required|min_value:0'})
    assert 'age' in errors


def test_max_value_valid():
    errors = validate({'qty': '50'}, {'qty': 'required|max_value:100'})
    assert errors == {}


def test_max_value_too_high():
    errors = validate({'qty': '150'}, {'qty': 'required|max_value:100'})
    assert 'qty' in errors
    assert 'at most' in errors['qty'][0]


def test_max_value_boundary():
    errors = validate({'qty': '100'}, {'qty': 'required|max_value:100'})
    assert errors == {}


def test_max_value_empty_skipped():
    errors = validate({'qty': ''}, {'qty': 'max_value:100'})
    assert errors == {}


# --- regex ---


def test_regex_match():
    errors = validate({'code': 'ABC'}, {'code': r'required|regex:^[A-Z]{3}$'})
    assert errors == {}


def test_regex_no_match():
    errors = validate({'code': 'abc'}, {'code': r'required|regex:^[A-Z]{3}$'})
    assert 'code' in errors


def test_regex_partial_no_match():
    errors = validate({'code': 'AB'}, {'code': r'required|regex:^[A-Z]{3}$'})
    assert 'code' in errors


def test_regex_empty_skipped():
    errors = validate({'code': ''}, {'code': r'regex:^[A-Z]+$'})
    assert errors == {}


# --- combined new rules ---


def test_combined_nullable_url():
    errors = validate({'website': ''}, {'website': 'nullable|url'})
    assert errors == {}


def test_combined_date_min_max():
    errors = validate(
        {'age': '25', 'dob': '1999-01-01'},
        {
            'age': 'required|numeric|min_value:18|max_value:120',
            'dob': 'required|date',
        },
    )
    assert errors == {}


# --- unique (sync validate ignores it) ---


def test_unique_ignored_in_sync_validate():
    """The unique rule is silently skipped in sync validate()."""
    errors = validate({'email': 'test@example.com'}, {'email': 'required|unique:users,email'})
    assert errors == {}


# --- validate_async ---


def _mock_conn(rows):
    """Create a mock Tortoise connection returning given rows."""
    conn = MagicMock()
    conn.execute_query = AsyncMock(return_value=(1, rows))
    return conn


@pytest.mark.asyncio
async def test_validate_async_unique_taken():
    with patch('tortoise.connections') as mock_conns:
        mock_conns.get.return_value = _mock_conn([{'cnt': 1}])
        errors = await validate_async(
            {'email': 'taken@example.com'},
            {'email': 'required|email|unique:users,email'},
        )
    assert 'email' in errors
    assert 'already been taken' in errors['email'][0]


@pytest.mark.asyncio
async def test_validate_async_unique_available():
    with patch('tortoise.connections') as mock_conns:
        mock_conns.get.return_value = _mock_conn([{'cnt': 0}])
        errors = await validate_async(
            {'email': 'new@example.com'},
            {'email': 'required|email|unique:users,email'},
        )
    assert errors == {}


@pytest.mark.asyncio
async def test_validate_async_unique_with_except():
    with patch('tortoise.connections') as mock_conns:
        conn = _mock_conn([{'cnt': 0}])
        mock_conns.get.return_value = conn
        errors = await validate_async(
            {'email': 'existing@example.com'},
            {'email': 'required|email|unique:users,email,42'},
        )
    assert errors == {}
    sql_call = conn.execute_query.call_args
    assert 'id != $2' in sql_call[0][0]
    assert sql_call[0][1] == ['existing@example.com', '42']


@pytest.mark.asyncio
async def test_validate_async_unique_skipped_when_sync_fails():
    """If a sync rule fails (e.g., email format), unique is not checked."""
    errors = await validate_async(
        {'email': 'not-an-email'},
        {'email': 'required|email|unique:users,email'},
    )
    assert 'email' in errors
    assert len(errors['email']) == 1
    assert 'valid email' in errors['email'][0]


@pytest.mark.asyncio
async def test_validate_async_unique_skipped_when_empty_nullable():
    errors = await validate_async(
        {'email': ''},
        {'email': 'nullable|unique:users,email'},
    )
    assert errors == {}


@pytest.mark.asyncio
async def test_validate_async_unique_custom_message():
    with patch('tortoise.connections') as mock_conns:
        mock_conns.get.return_value = _mock_conn([{'cnt': 1}])
        errors = await validate_async(
            {'email': 'taken@example.com'},
            {'email': 'required|unique:users,email'},
            {'email.unique': 'This email is already registered'},
        )
    assert errors['email'][0] == 'This email is already registered'


@pytest.mark.asyncio
async def test_validate_async_unique_invalid_table_name():
    with pytest.raises(ValueError, match='Invalid table name'):
        await validate_async(
            {'email': 'a@b.com'},
            {'email': 'required|unique:DROP TABLE--,email'},
        )


@pytest.mark.asyncio
async def test_validate_async_unique_missing_column():
    with pytest.raises(ValueError, match='at least table and column'):
        await validate_async(
            {'email': 'a@b.com'},
            {'email': 'required|unique:users'},
        )


@pytest.mark.asyncio
async def test_validate_async_without_unique_rules():
    """validate_async works fine with only sync rules (no DB hit)."""
    errors = await validate_async(
        {'name': 'Alice', 'email': 'alice@example.com'},
        {'name': 'required|min:2', 'email': 'required|email'},
    )
    assert errors == {}


# --- password_strength ---


def test_password_strength_default_min_length_8():
    """Without params, default min length is 8."""
    assert validate({'p': 'short'}, {'p': 'password_strength'}) != {}
    assert validate({'p': 'longenough'}, {'p': 'password_strength'}) == {}


def test_password_strength_custom_min_length():
    assert validate({'p': 'a' * 11}, {'p': 'password_strength:12'}) != {}
    assert validate({'p': 'a' * 12}, {'p': 'password_strength:12'}) == {}


def test_password_strength_upper_required():
    assert 'p' in validate({'p': 'alllowercase'}, {'p': 'password_strength:8,upper'})
    assert validate({'p': 'HasUpper'}, {'p': 'password_strength:8,upper'}) == {}


def test_password_strength_lower_required():
    assert 'p' in validate({'p': 'ALLUPPERCASE'}, {'p': 'password_strength:8,lower'})
    assert validate({'p': 'HasLower'}, {'p': 'password_strength:8,lower'}) == {}


def test_password_strength_digit_required():
    assert 'p' in validate({'p': 'NoDigitsHere'}, {'p': 'password_strength:8,digit'})
    assert validate({'p': 'Digits1Here'}, {'p': 'password_strength:8,digit'}) == {}


def test_password_strength_special_required():
    assert 'p' in validate({'p': 'NoSpecial1'}, {'p': 'password_strength:8,special'})
    assert validate({'p': 'HasSpecial!'}, {'p': 'password_strength:8,special'}) == {}


def test_password_strength_all_classes_required():
    """Strong password covering all four classes passes."""
    errors = validate({'p': 'Abc1!xyz'}, {'p': 'password_strength:8,upper,lower,digit,special'})
    assert errors == {}


def test_password_strength_combined_violations_one_message():
    """Multiple violations are combined into ONE error message."""
    errors = validate({'p': 'ab'}, {'p': 'password_strength:8,upper,digit,special'})
    assert 'p' in errors
    assert len(errors['p']) == 1
    msg = errors['p'][0]
    # Expect length AND classes mentioned in one message.
    assert 'at least 8' in msg
    assert 'uppercase' in msg
    assert 'digit' in msg
    assert 'special' in msg


def test_password_strength_skips_empty_value():
    """Empty values pass — pair with `required` to enforce non-emptiness."""
    assert validate({'p': ''}, {'p': 'password_strength:8,upper,digit'}) == {}


def test_password_strength_with_required():
    """Pairing with `required` makes empty values an error."""
    errors = validate({'p': ''}, {'p': 'required|password_strength:8'})
    assert 'p' in errors


def test_password_strength_invalid_min_length_raises():
    """Non-numeric first param raises ValueError at validate time."""
    with pytest.raises(ValueError, match='Invalid min_length'):
        validate({'p': 'something'}, {'p': 'password_strength:abc'})


def test_password_strength_unicode_classes():
    """Class checks are Unicode-aware (str.isupper / islower / isdigit)."""
    # Ñ counts as uppercase, ñ as lowercase
    assert validate({'p': 'Ñoñoño1!'}, {'p': 'password_strength:8,upper,lower,digit,special'}) == {}


def test_password_strength_custom_message():
    """Custom message override works the same as other rules."""
    errors = validate(
        {'p': 'ab'},
        {'p': 'password_strength:12'},
        {'p.password_strength': 'Password too weak'},
    )
    assert errors['p'] == ['Password too weak']
