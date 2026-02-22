# Forms, CSRF and Validation

Nori features an aggressive declarative validation engine (100% inspired by Laravel's Pipe-Separated system) and a native ecosystem against CSRF vulnerabilities in State submissions.

## Mandatory CSRF Protection

Every server response from a Nori Controller that issues a Form with a `POST` method action must mandatorily dispatch the security tag to Jinja2 via the context dictionary.

```python
from core.auth.csrf import csrf_field

# Rendering my empty GET html to the visitor
return templates.TemplateResponse(request, 'auth/myform.html', {
    'csrf_field': csrf_field(request.session)
})
```

In the respective HTML, you will use the global tag, which will inject the `hidden` input of the Dynamic Hash in real time.

```html
<form method="POST">
    {{ csrf_field|safe }}  <!-- Don't forget the |safe to render the TAG -->
    
    <label>User</label>
    <input type="text" name="usr">
    
    <button type="submit">Send</button>
</form>
```

If the server detects that in the Routes file the `myform` Endpoint is sent via `POST`, and infers the hidden `_csrf_token` is omitted or obsolete, it will halt execution immediately protecting your Database schemas and returning `403 Forbidden` JSON/HTML of imminent rejection.

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
    
    # 3. Decision Tree
    if errors:
        # We repopulate the current form including the pre-validated strings.
        return templates.TemplateResponse(request, 'myform.html', {
            'csrf_field': csrf_field(request.session),
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
| `email` | Strict verification RegEx for official Email String (`name@domain.tld`). |
| `numeric` | Admits native parseable Integers and Decimals from the Web dictionary Key. |
| `matches:field_b` | Full equitable validity cross-check (E.g. `matches:old_password`). |
| `in:op,op2` | Forcing Static Enums of Options delimited by CSV (E.g.: `in:active,vetoed,suspended`). |

### Template: Showing Visual Errors
Inside Jinja2, since you have fed the template back with a dictionary `{field: ['error 1', 'error 2']}`, you just need to check the Key.

```html
<form method="POST">
    {{ csrf_field|safe }}
    
    <input name="email" value="{{ usr_email|default('') }}" />
    {% if errors.email %}
        <!-- Showing the main failure of the iterated Array Index 0 block -->
        <span class="text-danger">{{ errors.email[0] }}</span> 
    {% endif %}
    
</form>
```
