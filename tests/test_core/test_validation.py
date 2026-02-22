"""Tests for core.http.validation."""
from core.http.validation import validate


# --- required ---

def test_required_missing():
    errors = validate({}, {'name': 'required'})
    assert 'name' in errors
    assert 'obligatorio' in errors['name'][0]


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
    assert 'al menos 6' in errors['pw'][0]


def test_min_ok():
    errors = validate({'pw': '123456'}, {'pw': 'required|min:6'})
    assert errors == {}


def test_max_too_long():
    errors = validate({'name': 'a' * 10}, {'name': 'required|max:5'})
    assert 'name' in errors
    assert 'maximo 5' in errors['name'][0]


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
    assert 'uno de' in errors['role'][0]


# --- multiple rules ---

def test_multiple_errors():
    errors = validate({'email': 'x', 'pw': ''}, {
        'email': 'required|email|max:255',
        'pw': 'required|min:8',
    })
    assert 'email' in errors
    assert 'pw' in errors


def test_required_stops_chain():
    """When required fails, subsequent rules for that field are skipped."""
    errors = validate({'email': ''}, {'email': 'required|email|min:5'})
    assert len(errors['email']) == 1
    assert 'obligatorio' in errors['email'][0]


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
    errors = validate({}, {'email': 'required'}, {
        'email.required': 'El correo es obligatorio',
    })
    assert errors['email'][0] == 'El correo es obligatorio'


def test_custom_message_only_affects_target_field():
    errors = validate({}, {'email': 'required', 'name': 'required'}, {
        'email.required': 'El correo es obligatorio',
    })
    assert errors['email'][0] == 'El correo es obligatorio'
    assert 'obligatorio' in errors['name'][0]
    assert errors['name'][0] != 'El correo es obligatorio'
