# Authentication and Authorization

Nori provides a complete, ready-to-use authentication system that includes session middlewares, route decorators for permissions, JSON Web Token (JWT) based authentication for APIs, and secure password handling using PBKDF2-SHA256 hashing.

## Password Hashing (Security)

To create users or validate manual logins, you must always use the `Security` class provided by the framework in `core.auth.security`.

```python
from core.auth.security import Security

# Hashing a plain text password
hashed_password = Security.hash_password('my_secret_password')
# 'pbkdf2_sha256$100000$salt$hash'

# Comparison / Verification
is_valid = Security.verify_password('my_secret_password', hashed_password) # True
```

`Security` also offers quick stochastic hexadecimal token generators:
```python
token = Security.generate_token()      # 64 hex characters
csrf = Security.generate_csrf_token()  # 64 hex characters
```

## Session Middlewares

Nori manages the logged-in user state in an encrypted session cookie using the `SECRET_KEY` from `.env`.

To log in after successfully validating the password, simply inject variables into the `request.session` dict:

```python
async def login(self, request: Request):
    # [Validation logic omitted]
    
    # Start Session (Effective "Login")
    request.session['user_id'] = str(user.id)
    request.session['role'] = 'admin' if user.level > 0 else 'user'
    
    return RedirectResponse(url='/dashboard', status_code=302)

async def logout(self, request: Request):
    # Close Session
    request.session.clear()
    
    return RedirectResponse(url='/', status_code=302)
```

## View Restriction (Decorators)

You can restrict entire controllers by applying decorators above the `async def` definition:

* `@login_required`
* `@require_role('my_role')`
* `@require_any_role('sales', 'management')`

*(Note: The role string `'admin'` has a general bypass by default).*

```python
from core.auth.decorators import login_required, require_role, require_any_role

class DashboardController:

    @login_required # Forces the session to contain an active 'user_id' dict key.
    async def account(self, request: Request):
        return ...

    @require_role('editor')
    async def change_password(self, request: Request):
        return ...
```

**Decorator Behavior:**
Depending on what the client tried to access, they act smartly (Content Negotiation via `Accept` Header):
* If the client is a browser (`Content-Type` HTML), they transparently redirect to `/login` (302) or `/forbidden` (403).
* If the client is pure Fetch/AJAX HTTP (`application/json`), they throw standard JSON dictionaries `{"error": "Unauthorized"}` with HTTP codes `401` and `403`.

---

## APIs and JSON Web Tokens (JWT)

For creating *Stateless* RESTful APIs, the traditional session system (cookies) is not suitable. Nori has native HMAC-SHA256 signatures in `core.auth.jwt`.

### Create a JWT (Login)
```python
from core.auth.jwt import create_token
from starlette.responses import JSONResponse

async def api_login(self, request: Request):
    # [Validate pwd...]
    
    # General payload and JSON dispatch
    jwt_str = create_token({'user_id': user.id}, expires_in=3600)
    return JSONResponse({'token': jwt_str})
```
*They are signed validating against the `JWT_SECRET` variable and automatically expire under Nori's Unix Epoch counters.*

### Protect API Routes (Decorator)
```python
from core.auth.decorators import token_required

@token_required
async def api_profile(self, request: Request):
    # If reached here, the token exists, is valid, and hasn't expired.
    
    # The injected payload is recovered directly from the decorator:
    user_id = request.state.token_payload['user_id']
    
    return JSONResponse({'status': 'ok', 'id': user_id})
```

The decorator reads the `Authorization: Bearer <token>` header. If missing, malformed, or invalid, it returns `401 Unauthorized` as JSON. The token is trimmed and limited to 4096 characters to prevent abuse.

---

## Granular Permissions (ACL)

For fine-grained access control beyond simple roles, use the permission system. Permissions use dot-notation (e.g. `articles.edit`, `users.delete`) and are loaded from the database at login time.

### Setup at Login

After authenticating, set the user's `role_ids` in the session and call `load_permissions()`:

```python
from core.auth.decorators import load_permissions

async def login(self, request: Request):
    # [Validate credentials...]
    request.session['user_id'] = str(user.id)
    request.session['role'] = user.role
    request.session['role_ids'] = [user.role_id]  # Required for load_permissions
    await load_permissions(request.session, user.id)
    return RedirectResponse(url='/dashboard', status_code=302)
```

**Important**: `load_permissions()` reads `role_ids` from the session to query the `Role→Permission` M2M. If `role_ids` is missing or empty, a warning is logged and the user will have no permissions.

### Protecting Routes

```python
from core.auth.decorators import require_permission

class ArticleController:
    @require_permission('articles.edit')
    async def edit(self, request: Request):
        ...
```

The `admin` role bypasses all permission checks.
