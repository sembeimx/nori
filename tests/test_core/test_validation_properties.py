"""Property-based tests for core.http.validation using Hypothesis.

These complement the example-based tests in test_validation.py by exploring
the input space systematically. Hypothesis generates random inputs and asserts
INVARIANTS — properties that must hold for any valid input. When an invariant
breaks, Hypothesis shrinks the failing case to a minimal reproducer.

Properties tested here:
- Idempotence: validate() is a pure function, repeat calls yield the same result
- Pipe vs list parity: 'a|b' and ['a', 'b'] must be equivalent
- Length boundaries: min/max use len() in the canonical way
- Numeric boundaries: min_value/max_value use float() comparison
- numeric round-trip: any float-parseable string passes; non-parseable fails
- in membership: value in options ⇔ no error
- nullable / required short-circuit semantics
- Empty rules: validate(d, {}) == {}
"""

from __future__ import annotations

from core.http.validation import validate
from hypothesis import given, settings
from hypothesis import strategies as st

# Cap shrinking time so the suite stays fast; bump locally if a regression
# needs more aggressive search.
settings.register_profile('default', max_examples=200, deadline=500)
settings.load_profile('default')


# --- Helper strategies ---

# Plain text without pipes (which are rule separators) and without colons in
# rule positions. Used as field VALUES, not rule strings.
field_values = st.text(
    alphabet=st.characters(blacklist_categories=('Cs',), blacklist_characters='|'),
    max_size=200,
)

# Identifiers safe to use as field names — alphanumeric + underscore.
field_names = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='_'),
    min_size=1,
    max_size=20,
)

# Small positive integers used as boundaries for min/max length rules.
small_positive_ints = st.integers(min_value=1, max_value=100)


# --- Invariants on the validate() function as a whole ---


@given(data=st.dictionaries(field_names, field_values), rules=st.dictionaries(field_names, field_values))
def test_validate_is_idempotent(data, rules):
    """Running validate twice produces the same result. validate() must be pure."""
    rules_str = {k: 'required' for k in rules}  # any non-empty rule shape works
    first = validate(data, rules_str)
    second = validate(data, rules_str)
    assert first == second


@given(data=st.dictionaries(field_names, field_values))
def test_empty_rules_means_no_errors(data):
    """validate(data, {}) is always {} regardless of data."""
    assert validate(data, {}) == {}


@given(field=field_names, value=field_values)
def test_pipe_string_equivalent_to_list(field, value):
    """'min:5|max:10' and ['min:5', 'max:10'] must produce identical results."""
    data = {field: value}
    pipe_form = validate(data, {field: 'min:5|max:10'})
    list_form = validate(data, {field: ['min:5', 'max:10']})
    assert pipe_form == list_form


# --- min / max length rules ---


@given(value=field_values, n=small_positive_ints)
def test_min_length_boundary(value, n):
    """min:n errors iff value is non-empty AND len(value) < n.

    Empty string SKIPS the min check (use `required` for non-emptiness).
    This is the documented contract — captures the intentional skip.
    """
    errors = validate({'f': value}, {'f': f'min:{n}'})
    if value and len(value) < n:
        assert 'f' in errors
        assert any('at least' in m for m in errors['f'])
    else:
        assert errors == {}


@given(value=field_values, n=small_positive_ints)
def test_max_length_boundary(value, n):
    """max:n errors iff value is non-empty AND len(value) > n."""
    errors = validate({'f': value}, {'f': f'max:{n}'})
    if value and len(value) > n:
        assert 'f' in errors
        assert any('at most' in m for m in errors['f'])
    else:
        assert errors == {}


@given(value=field_values, lo=small_positive_ints, hi=small_positive_ints)
def test_min_max_combined(value, lo, hi):
    """min:lo|max:hi: error from each rule independently."""
    errors = validate({'f': value}, {'f': f'min:{lo}|max:{hi}'})
    too_short = bool(value) and len(value) < lo
    too_long = bool(value) and len(value) > hi
    if too_short or too_long:
        assert 'f' in errors
    else:
        assert errors == {}


# --- min_value / max_value (numeric) rules ---


@given(
    value=st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    n=st.integers(min_value=-1000, max_value=1000),
)
def test_min_value_boundary(value, n):
    """min_value:n on a float-parseable string errors iff value < n."""
    errors = validate({'f': str(value)}, {'f': f'min_value:{n}'})
    if value < n:
        assert 'f' in errors
    else:
        assert errors == {}


@given(
    value=st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    n=st.integers(min_value=-1000, max_value=1000),
)
def test_max_value_boundary(value, n):
    """max_value:n on a float-parseable string errors iff value > n."""
    errors = validate({'f': str(value)}, {'f': f'max_value:{n}'})
    if value > n:
        assert 'f' in errors
    else:
        assert errors == {}


# --- numeric rule round-trip ---


@given(value=st.floats(allow_nan=False, allow_infinity=False, min_value=-1e10, max_value=1e10))
def test_numeric_accepts_floats(value):
    """Any finite float, when stringified, must pass `numeric`."""
    errors = validate({'f': str(value)}, {'f': 'numeric'})
    assert errors == {}


@given(value=st.text(alphabet=st.characters(whitelist_categories=('Ll', 'Lu')), min_size=1, max_size=20))
def test_numeric_rejects_pure_letters(value):
    """A non-empty string of only letters cannot be float()-parsed."""
    errors = validate({'f': value}, {'f': 'numeric'})
    assert 'f' in errors


def test_numeric_rejects_inf():
    """Explicit infinity strings are rejected."""
    assert 'f' in validate({'f': 'inf'}, {'f': 'numeric'})
    assert 'f' in validate({'f': '-inf'}, {'f': 'numeric'})
    assert 'f' in validate({'f': 'Infinity'}, {'f': 'numeric'})


def test_numeric_rejects_nan():
    """Explicit NaN strings are rejected."""
    assert 'f' in validate({'f': 'nan'}, {'f': 'numeric'})
    assert 'f' in validate({'f': 'NaN'}, {'f': 'numeric'})


# --- in membership ---


@given(
    options=st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd')),
            min_size=1,
            max_size=10,
        ),
        min_size=1,
        max_size=5,
        unique=True,
    ),
    extra=st.text(
        alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd')),
        min_size=1,
        max_size=10,
    ),
)
def test_in_membership(options, extra):
    """value in options → no error; value not in options → error."""
    options_str = ','.join(options)
    # Hypothesis may generate `extra` that happens to collide with an option.
    chosen_in = options[0]
    chosen_out = extra if extra not in options else f'{extra}_zzz_unique'

    assert validate({'f': chosen_in}, {'f': f'in:{options_str}'}) == {}
    assert 'f' in validate({'f': chosen_out}, {'f': f'in:{options_str}'})


# --- nullable / required short-circuit ---


@given(
    rules_after_nullable=st.sampled_from(['min:5', 'max:3', 'numeric', 'email', 'url']),
)
def test_nullable_skips_all_other_rules(rules_after_nullable):
    """Empty value + nullable: every other rule is skipped."""
    errors = validate({'f': ''}, {'f': f'nullable|{rules_after_nullable}'})
    assert errors == {}


@given(
    value=st.text(
        alphabet=st.characters(whitelist_categories=('Zs',), whitelist_characters=' \t\n'),
        max_size=10,
    ),
)
def test_required_short_circuits(value):
    """When `required` fails on whitespace-only input, no other rules emit errors."""
    errors = validate({'f': value}, {'f': 'required|min:100|email'})
    # Only the required error should appear, not min and email too.
    assert 'f' in errors
    assert len(errors['f']) == 1
    assert 'is required' in errors['f'][0]


# --- Idempotence on the more interesting case (with errors) ---


@given(
    rule=st.sampled_from(['required', 'numeric', 'email', 'min:5', 'max:3', 'url']),
    value=field_values,
)
def test_idempotence_with_arbitrary_rule(rule, value):
    """validate is pure regardless of which rule runs."""
    data = {'f': value}
    rules = {'f': rule}
    assert validate(data, rules) == validate(data, rules)


# --- Boundary cases (exact equality) ---


@given(n=small_positive_ints)
def test_min_at_boundary_does_not_error(n):
    """A string of exactly length n must satisfy min:n (boundary inclusive)."""
    value = 'x' * n
    errors = validate({'f': value}, {'f': f'min:{n}'})
    assert errors == {}


@given(n=small_positive_ints)
def test_max_at_boundary_does_not_error(n):
    """A string of exactly length n must satisfy max:n (boundary inclusive)."""
    value = 'x' * n
    errors = validate({'f': value}, {'f': f'max:{n}'})
    assert errors == {}


@given(n=st.integers(min_value=-1000, max_value=1000))
def test_min_value_at_boundary_does_not_error(n):
    """Numeric value exactly equal to n must satisfy min_value:n."""
    errors = validate({'f': str(n)}, {'f': f'min_value:{n}'})
    assert errors == {}


@given(n=st.integers(min_value=-1000, max_value=1000))
def test_max_value_at_boundary_does_not_error(n):
    """Numeric value exactly equal to n must satisfy max_value:n."""
    errors = validate({'f': str(n)}, {'f': f'max_value:{n}'})
    assert errors == {}


# --- Email regex stress test ---


@given(email=st.emails())
def test_email_accepts_hypothesis_generated(email):
    """Hypothesis-generated emails matching Nori's pragmatic contract are accepted.

    Nori's email regex is INTENTIONALLY more restrictive than RFC 5321/5322 —
    the same pragmatic shape Django/Rails/Laravel ship. Hypothesis-generated
    emails that fall outside that shape are filtered (not failures); whatever
    remains must be accepted.

    Documented exclusions (NOT bugs — by design):
      * Quoted local parts: ``"strange chars"@example.com``
      * IP-literal hosts: ``user@[192.0.2.1]``
      * Single-character TLDs: ``a@b.c`` (regex requires {2,})
      * IDN / Punycode TLDs (``xn--90ais`` for ``.рф``): regex requires
        pure letters in the TLD, no digits or hyphens.
      * Local part starting with non-alphanumeric: ``/user@example.com``,
        ``+tag@example.com``, ``_legit@example.com`` — first char must be
        ``[a-zA-Z0-9]``. Trailing-position underscore/plus/percent/hyphen
        IS supported (e.g. ``user+tag@example.com``).
      * Hostname labels starting with a digit: ``user@1example.com`` is
        outside the regex (host label first char is ``[a-zA-Z0-9]`` but
        modern DNS allows digits — Hypothesis-generated cases with all-
        digit subdomains are filtered).

    If you change ``_EMAIL_RE`` in ``core.http.validation``, update both the
    regex AND this filter so the contract stays self-documenting.
    """
    local, _, host = email.partition('@')
    if '"' in email or '@[' in email:
        return
    tld = host.rsplit('.', 1)[-1]
    if len(tld) < 2 or not tld.isalpha():
        return  # filter single-char TLDs and IDN/Punycode TLDs (xn--…)
    if not local or not local[0].isalnum():
        return
    allowed_after_first = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%+-.')
    if any(c not in allowed_after_first for c in local[1:]):
        return
    if '..' in local:
        return
    # Each host label (between dots) must start with a letter or digit per the
    # regex; subsequent chars are letters/digits/hyphens; must not end in hyphen.
    for label in host.split('.'):
        if not label or not label[0].isalnum() or label.endswith('-'):
            return
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in label):
            return

    errors = validate({'e': email}, {'e': 'email'})
    assert errors == {}, f'regex rejected hypothesis-generated email: {email!r}'


# --- Whitespace handling on `required` ---


@given(
    ws=st.text(
        alphabet=st.sampled_from([' ', '\t', '\n', '\r', ' ']),
        min_size=1,
        max_size=20,
    ),
)
def test_required_rejects_pure_whitespace(ws):
    """Whitespace-only values count as missing for `required`."""
    errors = validate({'f': ws}, {'f': 'required'})
    assert 'f' in errors


# --- password_strength ---


@given(value=st.text(min_size=1, max_size=50), n=st.integers(min_value=1, max_value=50))
def test_password_strength_length_only_matches_min_rule(value, n):
    """Without class flags, password_strength:N matches min:N for non-empty input.

    Both rules check len(value) >= N for non-empty values. They diverge on
    EMPTY strings (both skip) and on the error message text, but for
    membership in the error map they must agree.
    """
    pw_errors = validate({'f': value}, {'f': f'password_strength:{n}'})
    min_errors = validate({'f': value}, {'f': f'min:{n}'})
    assert ('f' in pw_errors) == ('f' in min_errors)


@given(
    n=st.integers(min_value=1, max_value=20),
    has_upper=st.booleans(),
    has_lower=st.booleans(),
    has_digit=st.booleans(),
    has_special=st.booleans(),
)
def test_password_strength_class_flags_independent(n, has_upper, has_lower, has_digit, has_special):
    """Each class flag rejects iff the corresponding character class is missing."""
    parts = []
    if has_upper:
        parts.append('A')
    if has_lower:
        parts.append('a')
    if has_digit:
        parts.append('1')
    if has_special:
        parts.append('!')
    # Pad to satisfy min length n with a neutral filler.
    value = ''.join(parts).ljust(n, 'a')

    rule = f'password_strength:{n},upper,lower,digit,special'
    errors = validate({'f': value}, {'f': rule})

    needs_upper = not any(c.isupper() for c in value)
    needs_lower = not any(c.islower() for c in value)
    needs_digit = not any(c.isdigit() for c in value)
    needs_special = not any(not c.isalnum() for c in value)

    if needs_upper or needs_lower or needs_digit or needs_special or len(value) < n:
        assert 'f' in errors
    else:
        assert errors == {}
