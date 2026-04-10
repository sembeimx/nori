# Forms, CSRF and Validation

Nori features a declarative validation engine using pipe-separated rules and a native CSRF protection system for form submissions.

The pipe syntax reads left-to-right like a checklist: required, then email, then max 255 characters. It's composable, compact, and avoids deeply nested dictionaries. One string per field, one glance to understand the rules.

## Mandatory CSRF Protection

Every form that makes a `POST` request must include a CSRF token. Since `csrf_field` is registered as a Jinja2 global, you can call it directly in your templates — no need to pass it from the controller:

```html
<form method="POST">
    {{ csrf_field(request.session)|safe }}

    <label>User</label>
    <input type="text" name="usr">

    <button type="submit">Send</button>
</form>
```

`csrf_field(request.session)` returns a `<input type="hidden" name="_csrf_token" value="...">` tag. The `|safe` filter is required to render the raw HTML.

If the CSRF token is missing or invalid on a state-changing request (POST, PUT, DELETE, PATCH), the middleware returns `403 Forbidden`.

> **JSON APIs are exempt**: Requests with `Content-Type: application/json` skip CSRF validation entirely. Browsers enforce CORS for cross-origin JSON requests, so the CSRF vector does not apply. API authentication should use JWT tokens instead (see [Authentication](authentication.md)).

## Pipe-Separated Declarative Validation (`validate`)

By capturing form dictionaries in `request.form()`, your controller delegates them to the generic validator, passing the rules with strings delimited by Pipes `|`.

```python
from core.http.validation import validate

async def process_form(self, request: Request):
    
    # 1. We get the entire dictionary sent from the Jinja Form
    raw_form = dict(await request.form())
    
    # 2. Central validation and injection of the failure schema
    errors = validate(raw_form, {
        'username': 'required|min:4|max:20',
        'email': 'required|email|max:255',
        'password': 'required|min:8',
        'confirm_password': 'required|matches:password',
        'age': 'numeric',
        'role': 'required|in:admin,editor,user',
    })
    
    # 2b. Optional: custom error messages per field.rule
    errors = validate(raw_form, {
        'email': 'required|email',
        'password': 'required|min:8',
    }, {
        'email.required': 'Email is mandatory',
        'password.min': 'Password must be at least 8 characters',
    })

    # 3. Decision Tree
    if errors:
        # We repopulate the current form including the pre-validated strings.
        return templates.TemplateResponse(request, 'myform.html', {
            'errors': errors,
            'sent_username': raw_form.get('username', '')
        })

    # If everything validated correctly, we proceed to the database.
```

### Native Included Rules

| Declared Rule | Operational Function |
| :---: | :--- |
| `required` | Blocks empty strings or omitted Key parameters in Form Request submission. |
| `min:N` | Sets a limiting Count Limit of characters less than `N`. |
| `max:N` | Ensures the string does not Overflow `N`. |
| `email` | Strict verification RegEx for official Email String (`name@domain.tld`). Rejects consecutive dots in local part per RFC 5321. |
| `numeric` | Admits native parseable Integers and Decimals. Rejects `Infinity` and `NaN`. |
| `matches:field_b` | Full equitable validity cross-check (E.g. `matches:old_password`). |
| `in:op,op2` | Forcing Static Enums of Options delimited by CSV (E.g.: `in:active,vetoed,suspended`). |
| `url` | Validates the string is a valid HTTP/HTTPS URL. |
| `date` | Validates the string is a valid ISO 8601 date (`YYYY-MM-DD`). |
| `confirmed` | Requires a matching `{field}_confirmation` field in the data (e.g., `password` checks `password_confirmation`). |
| `nullable` | Allows the field to be empty or missing without triggering any other rules. Place before other rules: `nullable\|email\|max:255`. |
| `array` | Validates the field value is a list. |
| `min_value:N` | Validates the numeric value is at least `N` (e.g., `min_value:0`, `min_value:1.5`). Unlike `min`, this checks the **number**, not string length. |
| `max_value:N` | Validates the numeric value is at most `N` (e.g., `max_value:100`). |
| `regex:pattern` | Validates the string matches a Python regular expression (e.g., `regex:^[A-Z]{3}$`). |
| `file` | Validates the field is an uploaded file (has a `filename` attribute). |
| `file_max:5mb` | Maximum file size. Accepts `mb`, `kb` suffixes or raw bytes (e.g. `file_max:500kb`, `file_max:10485760`). Invalid size values are rejected gracefully. |
| `file_types:jpg,png` | Restricts the file extension to the given comma-separated list. |

### Custom Error Messages

`validate()` accepts an optional third parameter to override default error messages per `field.rule`:

```python
errors = validate(form, {
    'name': 'required|min:3',
    'email': 'required|email',
}, {
    'name.required': 'Please enter your name',
    'name.min': 'Name is too short',
    'email.email': 'That doesn\'t look like an email',
})
```

Keys use `field.rule` format (e.g., `email.required`, `password.min`). If a custom message is not provided for a specific field.rule combination, the default message is used.

### File Upload Validation Example

```python
errors = validate(form, {
    'avatar': 'required|file|file_max:2mb|file_types:jpg,jpeg,png',
    'document': 'file|file_max:10mb|file_types:pdf',
})
```

File validation rules can be combined with other rules. The `file` rule checks that the value is an actual upload object, `file_max` checks the size, and `file_types` checks the extension. For full upload handling (MIME verification, magic byte checks, and storage), see [Services](services.md).

### Template: Showing Visual Errors
Inside Jinja2, since you have fed the template back with a dictionary `{field: ['error 1', 'error 2']}`, you just need to check the Key.

```html
<form method="POST">
    {{ csrf_field(request.session)|safe }}

    <input name="email" value="{{ usr_email|default('') }}" />
    {% if errors.email %}
        <!-- Showing the main failure of the iterated Array Index 0 block -->
        <span class="text-danger">{{ errors.email[0] }}</span>
    {% endif %}

</form>
```
