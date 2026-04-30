"""Tests for NoriCollection."""

from core.collection import NoriCollection, collect


class Obj:
    """Simple object for testing attribute access."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# --- collect() ---


def test_collect_from_list():
    c = collect([1, 2, 3])
    assert isinstance(c, NoriCollection)
    assert list(c) == [1, 2, 3]


def test_collect_from_generator():
    c = collect(x * 2 for x in range(3))
    assert list(c) == [0, 2, 4]


def test_collect_empty():
    c = collect([])
    assert len(c) == 0
    assert c.is_empty()


# --- first / last ---


def test_first():
    assert collect([10, 20, 30]).first() == 10


def test_first_empty():
    assert collect([]).first() is None


def test_last():
    assert collect([10, 20, 30]).last() == 30


def test_last_empty():
    assert collect([]).last() is None


# --- is_empty ---


def test_is_empty_true():
    assert collect([]).is_empty() is True


def test_is_empty_false():
    assert collect([1]).is_empty() is False


# --- pluck ---


def test_pluck_objects():
    items = [Obj(name='a'), Obj(name='b')]
    assert collect(items).pluck('name') == ['a', 'b']


def test_pluck_dicts():
    items = [{'name': 'x'}, {'name': 'y'}]
    assert collect(items).pluck('name') == ['x', 'y']


# --- where ---


def test_where_equals():
    items = [Obj(status=1), Obj(status=2), Obj(status=1)]
    result = collect(items).where('status', 1)
    assert len(result) == 2


def test_where_operator_gt():
    items = [Obj(price=10), Obj(price=50), Obj(price=30)]
    result = collect(items).where('price', '>', 20)
    assert len(result) == 2


def test_where_operator_ne():
    items = [Obj(x=1), Obj(x=2), Obj(x=3)]
    result = collect(items).where('x', '!=', 2)
    assert len(result) == 2


def test_where_truthy():
    items = [Obj(active=True), Obj(active=False), Obj(active=True)]
    result = collect(items).where('active')
    assert len(result) == 2


# --- sort_by ---


def test_sort_by():
    items = [Obj(name='c'), Obj(name='a'), Obj(name='b')]
    result = collect(items).sort_by('name')
    assert result.pluck('name') == ['a', 'b', 'c']


def test_sort_by_reverse():
    items = [Obj(name='a'), Obj(name='c'), Obj(name='b')]
    result = collect(items).sort_by('name', reverse=True)
    assert result.pluck('name') == ['c', 'b', 'a']


# --- group_by ---


def test_group_by():
    items = [Obj(type='a', v=1), Obj(type='b', v=2), Obj(type='a', v=3)]
    groups = collect(items).group_by('type')
    assert len(groups['a']) == 2
    assert len(groups['b']) == 1


# --- unique ---


def test_unique_primitives():
    result = collect([1, 2, 2, 3, 3]).unique()
    assert list(result) == [1, 2, 3]


def test_unique_by_key():
    items = [Obj(id=1, name='a'), Obj(id=2, name='b'), Obj(id=1, name='c')]
    result = collect(items).unique('id')
    assert len(result) == 2
    assert result.pluck('name') == ['a', 'b']


# --- chunk ---


def test_chunk():
    result = collect([1, 2, 3, 4, 5]).chunk(2)
    assert len(result) == 3
    assert list(result[0]) == [1, 2]
    assert list(result[1]) == [3, 4]
    assert list(result[2]) == [5]


# --- map / each ---


def test_map():
    result = collect([1, 2, 3]).map(lambda x: x * 10)
    assert list(result) == [10, 20, 30]
    assert isinstance(result, NoriCollection)


def test_each():
    acc = []
    result = collect([1, 2, 3]).each(lambda x: acc.append(x))
    assert acc == [1, 2, 3]
    assert list(result) == [1, 2, 3]  # returns self


# --- sum / avg / min / max ---


def test_sum():
    items = [Obj(price=10), Obj(price=20), Obj(price=30)]
    assert collect(items).sum('price') == 60


def test_avg():
    items = [Obj(score=10), Obj(score=20)]
    assert collect(items).avg('score') == 15.0


def test_avg_empty():
    assert collect([]).avg('x') is None


def test_min():
    items = [Obj(v=5), Obj(v=2), Obj(v=8)]
    assert collect(items).min('v') == 2


def test_min_empty():
    assert collect([]).min('v') is None


def test_max():
    items = [Obj(v=5), Obj(v=2), Obj(v=8)]
    assert collect(items).max('v') == 8


# --- to_list / to_dict ---


def test_to_list_dicts():
    items = [{'a': 1}, {'a': 2}]
    assert collect(items).to_list() == [{'a': 1}, {'a': 2}]


def test_to_list_objects():
    items = [Obj(name='x', _internal='skip')]
    result = collect(items).to_list()
    assert len(result) == 1
    assert 'name' in result[0]
    assert '_internal' not in result[0]


def test_to_dict():
    items = [Obj(id=1, name='a'), Obj(id=2, name='b')]
    result = collect(items).to_dict('id')
    assert result[1].name == 'a'
    assert result[2].name == 'b'


def test_to_list_refuses_tortoise_model_without_mixin():
    """Tortoise models without NoriModelMixin must NOT auto-serialize via
    _meta.fields_map — that path emits every field, leaking password_hash,
    tokens, etc. that protected_fields would have hidden.

    Simulate the shape of a Tortoise model with a fake _meta object so
    the test does not require the ORM to be initialized.
    """
    import pytest

    class FakeMeta:
        fields_map = {'id': None, 'email': None, 'password_hash': None}

    class LeakyModel:
        _meta = FakeMeta()
        id = 1
        email = 'a@b'
        password_hash = 'do-not-leak'  # noqa: S105 — fixture value, not a real secret

    leaky = LeakyModel()

    with pytest.raises(TypeError, match='NoriModelMixin'):
        collect([leaky]).to_list()


def test_to_list_works_with_nori_model_mixin_to_dict():
    """When the model exposes to_dict() (i.e. inherits NoriModelMixin),
    to_list() defers to it and respects whatever the model decided to
    expose."""

    class FakeMeta:
        fields_map = {'id': None, 'email': None, 'password_hash': None}

    class GoodModel:
        _meta = FakeMeta()

        def to_dict(self):
            return {'id': 1, 'email': 'a@b'}  # password_hash filtered out by mixin

    out = collect([GoodModel()]).to_list()
    assert out == [{'id': 1, 'email': 'a@b'}]


# --- sort_by with None values ---


def test_sort_by_with_none_values():
    """None values should be sorted to the end."""
    items = [Obj(name=None), Obj(name='a'), Obj(name='c'), Obj(name=None), Obj(name='b')]
    result = collect(items).sort_by('name')
    names = [i.name for i in result]
    # Non-None values first in order, then Nones at the end
    assert names == ['a', 'b', 'c', None, None]


def test_sort_by_all_none():
    """Sorting when all values are None should not error."""
    items = [Obj(name=None), Obj(name=None)]
    result = collect(items).sort_by('name')
    assert len(result) == 2
