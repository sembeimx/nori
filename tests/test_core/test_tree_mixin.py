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
    with pytest.raises(ValueError, match="Cannot move a node to itself"):
        await root.move_to(root.id)


@pytest.mark.asyncio
async def test_move_to_prevents_descendant():
    root, child_a, _, grandchild = await _build_tree()
    with pytest.raises(ValueError, match="Cannot move a node to one of its descendants"):
        await root.move_to(grandchild.id)
