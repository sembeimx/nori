"""Tests for NoriTreeMixin."""

import pytest
from test_models import SampleCategory


@pytest.fixture(autouse=True)
async def _clean_categories():
    """Clean up test categories before each test."""
    await SampleCategory.all().delete()
    yield


async def _build_tree():
    """
    Build a test tree:
        Root
        +-- Child A
        |   +-- Grandchild A1
        +-- Child B
    """
    root = await SampleCategory.create(name='Root', parent_id=None)
    child_a = await SampleCategory.create(name='Child A', parent_id=root.id)
    child_b = await SampleCategory.create(name='Child B', parent_id=root.id)
    grandchild = await SampleCategory.create(name='Grandchild A1', parent_id=child_a.id)
    return root, child_a, child_b, grandchild


@pytest.mark.asyncio
async def test_children():
    root, child_a, child_b, _ = await _build_tree()
    children = await root.children()
    names = [c.name for c in children]
    assert 'Child A' in names
    assert 'Child B' in names
    assert len(children) == 2


@pytest.mark.asyncio
async def test_parent_node():
    root, child_a, _, _ = await _build_tree()
    parent = await child_a.parent_node()
    assert parent is not None
    assert parent.id == root.id


@pytest.mark.asyncio
async def test_parent_node_of_root_is_none():
    root, _, _, _ = await _build_tree()
    parent = await root.parent_node()
    assert parent is None


@pytest.mark.asyncio
async def test_is_root():
    root, child_a, _, _ = await _build_tree()
    assert await root.is_root() is True
    assert await child_a.is_root() is False


@pytest.mark.asyncio
async def test_is_leaf():
    root, _, child_b, grandchild = await _build_tree()
    assert await grandchild.is_leaf() is True
    assert await child_b.is_leaf() is True
    assert await root.is_leaf() is False


@pytest.mark.asyncio
async def test_siblings():
    _, child_a, child_b, _ = await _build_tree()
    siblings = await child_a.siblings()
    names = [s.name for s in siblings]
    assert 'Child B' in names
    assert 'Child A' not in names


@pytest.mark.asyncio
async def test_ancestors():
    root, child_a, _, grandchild = await _build_tree()
    ancestors = await grandchild.ancestors()
    ids = [a.id for a in ancestors]
    assert child_a.id in ids
    assert root.id in ids


@pytest.mark.asyncio
async def test_ancestors_of_root_is_empty():
    root, _, _, _ = await _build_tree()
    ancestors = await root.ancestors()
    assert len(ancestors) == 0


@pytest.mark.asyncio
async def test_descendants():
    root, child_a, child_b, grandchild = await _build_tree()
    descendants = await root.descendants()
    ids = [d.id for d in descendants]
    assert child_a.id in ids
    assert child_b.id in ids
    assert grandchild.id in ids


@pytest.mark.asyncio
async def test_tree_builds_structure():
    root, _, _, _ = await _build_tree()
    tree = await SampleCategory.tree()
    assert len(tree) == 1  # one root
    assert tree[0].name == 'Root'
    assert len(tree[0]._children) == 2


@pytest.mark.asyncio
async def test_move_to_prevents_self():
    root, _, _, _ = await _build_tree()
    with pytest.raises(ValueError, match='Cannot move a node to itself'):
        await root.move_to(root.id)


@pytest.mark.asyncio
async def test_move_to_prevents_descendant():
    root, child_a, _, grandchild = await _build_tree()
    with pytest.raises(ValueError, match='Cannot move a node to one of its descendants'):
        await root.move_to(grandchild.id)


# ---------------------------------------------------------------------------
# _quote_ident — dialect-aware identifier quoting
# ---------------------------------------------------------------------------


def _make_fake_conn(class_name: str):
    """Return a fake conn instance whose ``type(...).__name__`` matches.

    ``_quote_ident`` only inspects the connection class name, so a bare
    object of a freshly-built class is enough to drive each branch.
    """
    cls = type(class_name, (), {})
    return cls()


def test_quote_ident_postgres_uses_double_quotes(monkeypatch):
    """Postgres / asyncpg uses ANSI double-quoted identifiers. Without
    quoting, mixed-case names get lowercase-folded and reserved words
    (``desc``, ``table``) trigger a syntax error at parse time.
    """
    from core.mixins import tree

    fake = _make_fake_conn('AsyncpgDBClient')
    monkeypatch.setattr(tree.Tortoise, 'get_connection', lambda alias='default': fake)

    assert tree._quote_ident('Order') == '"Order"'
    assert tree._quote_ident('desc') == '"desc"'


def test_quote_ident_sqlite_uses_double_quotes(monkeypatch):
    """SQLite accepts several quote styles but ANSI double-quotes is the
    safe portable default — also what falls out of the catch-all branch.
    """
    from core.mixins import tree

    fake = _make_fake_conn('SqliteClient')
    monkeypatch.setattr(tree.Tortoise, 'get_connection', lambda alias='default': fake)

    assert tree._quote_ident('User') == '"User"'


def test_quote_ident_mysql_uses_backticks(monkeypatch):
    """MySQL's default ``sql_mode`` reserves double-quotes for string
    literals; identifiers are quoted with backticks. We cannot assume
    ``ANSI_QUOTES`` is enabled in user deployments.
    """
    from core.mixins import tree

    fake = _make_fake_conn('MysqlClient')
    monkeypatch.setattr(tree.Tortoise, 'get_connection', lambda alias='default': fake)

    assert tree._quote_ident('Order') == '`Order`'


def test_quote_ident_mariadb_uses_backticks(monkeypatch):
    """MariaDB inherits MySQL's quoting style by default."""
    from core.mixins import tree

    fake = _make_fake_conn('MariaDBClient')
    monkeypatch.setattr(tree.Tortoise, 'get_connection', lambda alias='default': fake)

    assert tree._quote_ident('Order') == '`Order`'


def test_quote_ident_unknown_dialect_falls_back_to_double_quotes(monkeypatch):
    """Defensive default: ANSI SQL standard quoting for any driver we
    have not enumerated. Better to emit a portable quote style than to
    silently interpolate the bare identifier.
    """
    from core.mixins import tree

    fake = _make_fake_conn('SomeFutureDBClient')
    monkeypatch.setattr(tree.Tortoise, 'get_connection', lambda alias='default': fake)

    assert tree._quote_ident('Order') == '"Order"'


# ---------------------------------------------------------------------------
# Recursive CTE — identifier quoting integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ancestors_sql_quotes_identifiers(monkeypatch):
    """Pre-1.28 the recursive CTE interpolated raw identifiers — a model
    whose ``Meta.table`` was mixed-case (``Order``) or a reserved word
    (``desc``) would fail at SQL parse time. The test DB is SQLite so
    the captured SQL uses ANSI double-quotes; the assertion verifies the
    table and both columns appear in their quoted forms.
    """
    _, _, _, grandchild = await _build_tree()

    from tortoise import Tortoise as _T

    conn = _T.get_connection('default')
    captured: list[str] = []
    original = conn.execute_query

    async def capture(sql, params=None):
        captured.append(sql)
        return await original(sql, params or [])

    monkeypatch.setattr(conn, 'execute_query', capture)
    await grandchild.ancestors()

    cte = next((s for s in captured if 'WITH RECURSIVE' in s), None)
    assert cte is not None, f'recursive CTE not captured: {captured!r}'
    assert '"sample_category"' in cte, f'table identifier not quoted: {cte}'
    assert '"id"' in cte, f'pk column not quoted: {cte}'
    assert '"parent_id"' in cte, f'parent column not quoted: {cte}'


@pytest.mark.asyncio
async def test_descendants_sql_quotes_identifiers(monkeypatch):
    """Mirror coverage for ``descendants()`` — same quoting contract."""
    root, _, _, _ = await _build_tree()

    from tortoise import Tortoise as _T

    conn = _T.get_connection('default')
    captured: list[str] = []
    original = conn.execute_query

    async def capture(sql, params=None):
        captured.append(sql)
        return await original(sql, params or [])

    monkeypatch.setattr(conn, 'execute_query', capture)
    await root.descendants()

    cte = next((s for s in captured if 'WITH RECURSIVE' in s), None)
    assert cte is not None, f'recursive CTE not captured: {captured!r}'
    assert '"sample_category"' in cte
    assert '"id"' in cte
    assert '"parent_id"' in cte
