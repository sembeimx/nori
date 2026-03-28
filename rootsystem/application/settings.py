from __future__ import annotations

import os
from os.path import abspath, dirname, isabs, join
from dotenv import load_dotenv

_root = dirname(dirname(dirname(abspath(__file__))))
_app_dir = dirname(abspath(__file__))
load_dotenv(join(_app_dir, '.env'))

import secrets as _secrets

DEBUG = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')

_secret_env = os.environ.get('SECRET_KEY', '')
if not _secret_env and not DEBUG:
    raise RuntimeError("SECRET_KEY environment variable is required in production")
SECRET_KEY = _secret_env or _secrets.token_urlsafe(32)

TEMPLATE_DIR = join(_root, 'rootsystem', 'templates')
STATIC_DIR = join(_root, 'rootsystem', 'static')

# Database
DB_ENABLED = os.environ.get('DB_ENABLED', 'true').lower() in ('true', '1', 'yes')
DB_ENGINE = os.environ.get('DB_ENGINE', 'mysql')

if DB_ENGINE == 'sqlite':
    _db_name = os.environ.get('DB_NAME', 'db.sqlite3')
    _db_path = _db_name if isabs(_db_name) else join(_app_dir, _db_name)
    _connection = f'sqlite://{_db_path}'
else:
    _connection = {
        'engine': 'tortoise.backends.mysql' if DB_ENGINE == 'mysql'
                  else 'tortoise.backends.asyncpg',
        'credentials': {
            'host': os.environ.get('DB_HOST', 'localhost'),
            'port': int(os.environ.get('DB_PORT', '3306' if DB_ENGINE == 'mysql' else '5432')),
            'user': os.environ.get('DB_USER', ''),
            'password': os.environ.get('DB_PASSWORD', ''),
            'database': os.environ.get('DB_NAME', ''),
        }
    }

# CORS
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get('CORS_ORIGINS', '').split(',')
    if o.strip()
]
CORS_ALLOW_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']
CORS_ALLOW_HEADERS = ['Content-Type', 'Authorization', 'X-CSRF-Token']
CORS_ALLOW_CREDENTIALS = True

# File Uploads
STORAGE_DRIVER = os.environ.get('STORAGE_DRIVER', 'local')  # local | (custom drivers)
UPLOAD_DIR = join(_app_dir, 'uploads')
UPLOAD_MAX_SIZE = int(os.environ.get('UPLOAD_MAX_SIZE', 10 * 1024 * 1024))  # 10 MB

# Email
MAIL_DRIVER = os.environ.get('MAIL_DRIVER', 'smtp')  # smtp | log | (custom drivers)
MAIL_HOST = os.environ.get('MAIL_HOST', 'localhost')
MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
MAIL_USER = os.environ.get('MAIL_USER', '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
MAIL_FROM = os.environ.get('MAIL_FROM', 'noreply@localhost')
MAIL_TLS = os.environ.get('MAIL_TLS', 'true').lower() in ('true', '1', 'yes')

# JWT / API Tokens
JWT_SECRET = os.environ.get('JWT_SECRET', SECRET_KEY)
JWT_EXPIRATION = int(os.environ.get('JWT_EXPIRATION', '3600'))

# Rate Limiting
THROTTLE_BACKEND = os.environ.get('THROTTLE_BACKEND', 'memory')  # memory | redis

# Trusted proxies — only trust X-Forwarded-For from these IPs
# Comma-separated list (e.g. '127.0.0.1,10.0.0.1')
TRUSTED_PROXIES = [
    ip.strip()
    for ip in os.environ.get('TRUSTED_PROXIES', '').split(',')
    if ip.strip()
]
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')

# Caching
CACHE_BACKEND = os.environ.get('CACHE_BACKEND', 'memory')  # memory | redis

# Search (external drivers registered in services/)
SEARCH_DRIVER = os.environ.get('SEARCH_DRIVER', '')  # meilisearch | (custom drivers)

# Queue
QUEUE_DRIVER = os.environ.get('QUEUE_DRIVER', 'memory')  # memory | database

# OAuth — Social login providers (configured per-provider in services/)
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GITHUB_CLIENT_ID = os.environ.get('GITHUB_CLIENT_ID', '')
GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_CLIENT_SECRET', '')

_model_modules = ['models']
try:
    import aerich  # noqa: F401
    _model_modules.append('aerich.models')
except ImportError:
    pass

TORTOISE_ORM = {
    'connections': {
        'default': _connection,
    },
    'apps': {
        'models': {
            'models': _model_modules,
            'default_connection': 'default',
        }
    },
}


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_settings() -> list[str]:
    """Validate configuration at startup.

    Checks performed:

    - Database credentials are present for non-SQLite in production.
    - Template and static directories exist on disk.
    - ``JWT_SECRET`` differs from ``SECRET_KEY`` in production.
    - ``JWT_SECRET`` has a minimum length of 32 characters in production
      (required for HMAC-SHA256 security).

    Returns:
        List of warning/error messages (empty if everything is OK).

    Raises:
        RuntimeError: In production (``DEBUG=false``) if any critical
            validation fails.
    """
    errors: list[str] = []

    # Database credentials required for non-sqlite in production
    if DB_ENABLED and DB_ENGINE != 'sqlite' and not DEBUG:
        if not os.environ.get('DB_USER'):
            errors.append("DB_USER is required for production databases")
        if not os.environ.get('DB_PASSWORD'):
            errors.append("DB_PASSWORD is required for production databases")
        if not os.environ.get('DB_NAME'):
            errors.append("DB_NAME is required for production databases")

    # Template and static dirs should exist
    if not os.path.isdir(TEMPLATE_DIR):
        errors.append(f"TEMPLATE_DIR not found: {TEMPLATE_DIR}")
    if not os.path.isdir(STATIC_DIR):
        errors.append(f"STATIC_DIR not found: {STATIC_DIR}")

    # JWT secret should differ from SECRET_KEY in production
    if not DEBUG and JWT_SECRET == SECRET_KEY:
        errors.append("JWT_SECRET should be set independently from SECRET_KEY in production")

    # JWT secret must have minimum length for HMAC-SHA256 security
    if not DEBUG and len(JWT_SECRET) < 32:
        errors.append(
            "JWT_SECRET is too short (minimum 32 characters). "
            "Use a cryptographically random string: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    if errors and not DEBUG:
        raise RuntimeError(
            "Settings validation failed:\n  - " + "\n  - ".join(errors)
        )

    return errors
