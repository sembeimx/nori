"""Tests for settings — SQLite config branch."""


def test_sqlite_config(monkeypatch):
    """When DB_ENGINE=sqlite, TORTOISE_ORM connection should be a sqlite:// URL."""
    monkeypatch.setenv('DB_ENGINE', 'sqlite')
    monkeypatch.setenv('DB_NAME', 'test.sqlite3')

    # Re-import to pick up new env
    import importlib

    import settings

    importlib.reload(settings)

    conn = settings.TORTOISE_ORM['connections']['default']
    assert isinstance(conn, str)
    assert conn.startswith('sqlite://')
    assert conn.endswith('test.sqlite3')


def test_sqlite_absolute_path(monkeypatch):
    """Absolute DB_NAME should be used as-is."""
    monkeypatch.setenv('DB_ENGINE', 'sqlite')
    monkeypatch.setenv('DB_NAME', '/tmp/my.sqlite3')

    import importlib

    import settings

    importlib.reload(settings)

    conn = settings.TORTOISE_ORM['connections']['default']
    assert conn == 'sqlite:///tmp/my.sqlite3'


def test_mysql_config(monkeypatch):
    """When DB_ENGINE=mysql, TORTOISE_ORM connection should be a dict."""
    monkeypatch.setenv('DB_ENGINE', 'mysql')
    monkeypatch.setenv('DB_HOST', 'dbhost')

    import importlib

    import settings

    importlib.reload(settings)

    conn = settings.TORTOISE_ORM['connections']['default']
    assert isinstance(conn, dict)
    assert conn['engine'] == 'tortoise.backends.mysql'
    assert conn['credentials']['host'] == 'dbhost'


def test_postgres_config(monkeypatch):
    """When DB_ENGINE=postgres, should use asyncpg backend."""
    monkeypatch.setenv('DB_ENGINE', 'postgres')

    import importlib

    import settings

    importlib.reload(settings)

    conn = settings.TORTOISE_ORM['connections']['default']
    assert isinstance(conn, dict)
    assert conn['engine'] == 'tortoise.backends.asyncpg'
