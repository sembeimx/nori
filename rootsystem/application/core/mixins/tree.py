from __future__ import annotations

from typing import Any, Sequence
from typing_extensions import Self
from tortoise.models import Model
from tortoise import fields
from tortoise import Tortoise
from core.collection import NoriCollection, collect


class NoriTreeMixin(Model):
    """
    Mixin para arboles con adjacency list.
    Requiere campo parent (ForeignKey a self).

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

    # --- Configuracion ---
    # Subclases deben definir un campo ForeignKey a 'self' llamado 'parent'
    # con related_name='children_rel'
    _parent_field: str = 'parent_id'  # nombre de la columna FK en la DB

    async def children(self) -> NoriCollection[Any]:
        """Hijos directos."""
        pk = self.pk
        results = await self.__class__.filter(**{self._parent_field: pk}).all()
        return collect(results)

    async def parent_node(self) -> Self | None:
        """Nodo padre. None si es raiz."""
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
                raise ValueError(f"Invalid SQL identifier: {ident}")

        sql = (
            f"WITH RECURSIVE ancestors AS ("
            f"  SELECT * FROM {table} WHERE {pk_col} = %s"
            f"  UNION ALL"
            f"  SELECT t.* FROM {table} t"
            f"  INNER JOIN ancestors a ON t.{pk_col} = a.{parent_col}"
            f") SELECT * FROM ancestors WHERE {pk_col} != %s"
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
                raise ValueError(f"Invalid SQL identifier: {ident}")

        sql = (
            f"WITH RECURSIVE descendants AS ("
            f"  SELECT * FROM {table} WHERE {parent_col} = %s"
            f"  UNION ALL"
            f"  SELECT t.* FROM {table} t"
            f"  INNER JOIN descendants d ON t.{parent_col} = d.{pk_col}"
            f") SELECT * FROM descendants"
        )

        conn = Tortoise.get_connection('default')
        _, rows = await conn.execute_query(sql, [pk])
        return await self._hydrate_rows(rows)

    async def siblings(self) -> NoriCollection[Any]:
        """Hermanos (mismo parent, excluyendo self)."""
        parent_id = getattr(self, self._parent_field, None)
        if parent_id is None:
            nodes = await self.__class__.filter(**{self._parent_field + '__isnull': True}).all()
        else:
            nodes = await self.__class__.filter(**{self._parent_field: parent_id}).all()
        return NoriCollection(n for n in nodes if n.pk != self.pk)

    async def is_leaf(self) -> bool:
        """True si no tiene hijos."""
        count = await self.__class__.filter(**{self._parent_field: self.pk}).count()
        return count == 0

    async def is_root(self) -> bool:
        """True si no tiene padre."""
        return getattr(self, self._parent_field, None) is None

    async def move_to(self, new_parent_id: Any) -> Self:
        """
        Mover nodo a otro padre.
        Valida que no se mueva a si mismo ni a un descendiente.
        """
        if new_parent_id == self.pk:
            raise ValueError("No se puede mover un nodo a si mismo")

        if new_parent_id is not None:
            descendants = await self.descendants()
            descendant_ids = {d.pk for d in descendants}
            if new_parent_id in descendant_ids:
                raise ValueError("No se puede mover un nodo a uno de sus descendientes")

        setattr(self, self._parent_field, new_parent_id)
        await self.save(update_fields=[self._parent_field])
        return self

    @classmethod
    async def tree(cls, root_id: Any = None) -> NoriCollection[Any]:
        """
        Carga arbol completo en UNA query y lo estructura en memoria.
        Retorna NoriCollection de nodos raiz, cada uno con ._children populado.
        """
        all_nodes = await cls.all()
        return cls._build_tree(all_nodes, root_id)

    @classmethod
    def _build_tree(cls, all_nodes: Sequence[Any], root_id: Any = None) -> NoriCollection[Any]:
        """Construye arbol en memoria desde lista plana."""
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
        """Convierte dicts de raw SQL a instancias del modelo."""
        result: NoriCollection[Any] = NoriCollection()
        for row in rows:
            instance = cls(**row)
            result.append(instance)
        return result
