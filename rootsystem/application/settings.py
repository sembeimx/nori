import os
from os.path import abspath, dirname, isabs, join
from dotenv import load_dotenv

_root = dirname(dirname(dirname(abspath(__file__))))
_app_dir = dirname(abspath(__file__))
load_dotenv(join(_app_dir, '.env'))

DEBUG = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')
SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')

TEMPLATE_DIR = join(_root, 'rootsystem', 'templates')
STATIC_DIR = join(_root, 'rootsystem', 'static')

# Database engine: mysql | postgres | sqlite
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
CORS_ALLOW_HEADERS = ['*']
CORS_ALLOW_CREDENTIALS = True

# File Uploads
UPLOAD_DIR = join(_app_dir, 'uploads')
UPLOAD_MAX_SIZE = int(os.environ.get('UPLOAD_MAX_SIZE', 10 * 1024 * 1024))  # 10 MB

# Email (SMTP)
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
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')

TORTOISE_ORM = {
    'connections': {
        'default': _connection,
    },
    'apps': {
        'models': {
            'models': ['models.user', 'models.product'],
            'default_connection': 'default',
        }
    },
}
