from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tortoise import Tortoise
from tortoise.models import Model
from typing_extensions import Self

from core.collection import NoriCollection, collect


def _placeholders(count: int) -> list[str]:
    """Return SQL parameter placeholders appropriate for the current DB backend."""
    conn = Tortoise.get_connection('default')
    cls_name = type(conn).__name__.lower()
    if 'sqlite' in cls_name:
        return ['?'] * count
    if 'asyncpg' in cls_name or 'postgres' in cls_name:
        return [f'${i}' for i in range(1, count + 1)]
    return ['%s'] * count


class NoriTreeMixin(Model):
    """
    Mixin for adjacency-list tree structures.
    Requires a parent ForeignKey field pointing to self.

        class Category(NoriTreeMixin):
            name = fields.CharField(max_length=100)
            parent = fields.ForeignKeyField(
                'models.Category', related_name='children_rel',
                null=True, default=None
            )
            class Meta:
                table = 'category'

        node = await Category.get(id=5)
        children = await node.children()
        ancestors = await node.ancestors()
        descendants = await node.descendants()
        tree = await Category.tree()
    """

    class Meta:
        abstract = True

    # --- Configuration ---
    # Subclasses must define a ForeignKey to 'self' named 'parent'
    # with related_name='children_rel'
    _parent_field: str = 'parent_id'  # FK column name in the DB

    async def children(self) -> NoriCollection[Any]:
        """Direct children."""
        pk = self.pk
        results = await self.__class__.filter(**{self._parent_field: pk}).all()
        return collect(results)

    async def parent_node(self) -> Self | None:
        """Parent node. None if root."""
        parent_id = getattr(self, self._parent_field, None)
        if parent_id is None:
            return None
        return await self.__class__.get_or_none(pk=parent_id)

    async def ancestors(self) -> NoriCollection[Any]:
        """
        All ancestors up to root (1 query via recursive CTE).
        Returns NoriCollection ordered from direct parent to root.
        """
        pk = self.pk
        parent_id = getattr(self, self._parent_field, None)
        if parent_id is None:
            return NoriCollection()

        table = self.__class__._meta.db_table
        pk_col = self.__class__._meta.pk_attr
        parent_col = self._parent_field

        # Validate identifiers to prevent SQL injection
        for ident in (table, pk_col, parent_col):
            if not ident.replace('_', '').isalnum():
                raise ValueError(f'Invalid SQL identifier: {ident}')

        ph = _placeholders(2)
        sql = (
            f'WITH RECURSIVE ancestors AS ('
            f'  SELECT * FROM {table} WHERE {pk_col} = {ph[0]}'
            f'  UNION ALL'
            f'  SELECT t.* FROM {table} t'
            f'  INNER JOIN ancestors a ON t.{pk_col} = a.{parent_col}'
            f') SELECT * FROM ancestors WHERE {pk_col} != {ph[1]}'
        )

        conn = Tortoise.get_connection('default')
        _, rows = await conn.execute_query(sql, [pk, pk])
        return await self._hydrate_rows(rows)

    async def descendants(self) -> NoriCollection[Any]:
        """
        All recursive descendants (1 query via recursive CTE).
        Returns NoriCollection.
        """
        pk = self.pk
        table = self.__class__._meta.db_table
        pk_col = self.__class__._meta.pk_attr
        parent_col = self._parent_field

        for ident in (table, pk_col, parent_col):
            if not ident.replace('_', '').isalnum():
                raise ValueError(f'Invalid SQL identifier: {ident}')

        ph = _placeholders(1)
        sql = (
            f'WITH RECURSIVE descendants AS ('
            f'  SELECT * FROM {table} WHERE {parent_col} = {ph[0]}'
            f'  UNION ALL'
            f'  SELECT t.* FROM {table} t'
            f'  INNER JOIN descendants d ON t.{parent_col} = d.{pk_col}'
            f') SELECT * FROM descendants'
        )

        conn = Tortoise.get_connection('default')
        _, rows = await conn.execute_query(sql, [pk])
        return await self._hydrate_rows(rows)

    async def siblings(self) -> NoriCollection[Any]:
        """Siblings (same parent, excluding self)."""
        parent_id = getattr(self, self._parent_field, None)
        if parent_id is None:
            nodes = await self.__class__.filter(**{self._parent_field + '__isnull': True}).all()
        else:
            nodes = await self.__class__.filter(**{self._parent_field: parent_id}).all()
        return NoriCollection(n for n in nodes if n.pk != self.pk)

    async def is_leaf(self) -> bool:
        """True if the node has no children."""
        count = await self.__class__.filter(**{self._parent_field: self.pk}).count()
        return count == 0

    async def is_root(self) -> bool:
        """True if the node has no parent."""
        return getattr(self, self._parent_field, None) is None

    async def move_to(self, new_parent_id: Any) -> Self:
        """
        Move node to a new parent.
        Validates that a node cannot be moved to itself or to one of its descendants.
        """
        if new_parent_id == self.pk:
            raise ValueError('Cannot move a node to itself')

        if new_parent_id is not None:
            descendants = await self.descendants()
            descendant_ids = {d.pk for d in descendants}
            if new_parent_id in descendant_ids:
                raise ValueError('Cannot move a node to one of its descendants')

        setattr(self, self._parent_field, new_parent_id)
        await self.save(update_fields=[self._parent_field])
        return self

    @classmethod
    async def tree(cls, root_id: Any = None) -> NoriCollection[Any]:
        """
        Load the full tree in ONE query and structure it in memory.
        Returns NoriCollection of root nodes, each with ._children populated.
        """
        all_nodes = await cls.all()
        return cls._build_tree(all_nodes, root_id)

    @classmethod
    def _build_tree(cls, all_nodes: Sequence[Any], root_id: Any = None) -> NoriCollection[Any]:
        """Build tree in memory from a flat list."""
        by_id: dict[Any, Any] = {}
        for node in all_nodes:
            node._children = NoriCollection()
            by_id[node.pk] = node

        roots: NoriCollection[Any] = NoriCollection()
        parent_field = cls._parent_field

        for node in all_nodes:
            pid = getattr(node, parent_field, None)
            if pid is None:
                roots.append(node)
            elif pid in by_id:
                by_id[pid]._children.append(node)

        if root_id is not None and root_id in by_id:
            return by_id[root_id]._children

        return roots

    @classmethod
    async def _hydrate_rows(cls, rows: Sequence[dict[str, Any]]) -> NoriCollection[Any]:
        """Convert raw SQL dicts to model instances."""
        result: NoriCollection[Any] = NoriCollection()
        for row in rows:
            instance = cls(**row)
            result.append(instance)
        return result
