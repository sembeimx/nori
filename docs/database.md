# Base de Datos (Tortoise ORM)

En Nori el mapeo asíncrono hacia base de datos (ORM) se gestiona gracias a **Tortoise ORM**. Es altamente inspirado en el ORM de Django pero 100% no bloqueante (`async/await`).

## Conexión y Configuración

Los motores (MySQL, PostgreSQL, SQLite) se definen en el archivo `.env`. El framework parsea el motor solicitado en el archivo de configuración base central `rootsystem/application/settings.py`.

Asegúrate de documentar y registrar tus Modelos dentro de `settings.py` (en el diccionario `TORTOISE_ORM['apps']['models']['models']`) para que Tortoise los localice de inmediato y permita su inter-relación.

## Definición de un Modelo

Los modelos se localizan dentro del directorio `rootsystem/application/models/`. Deben heredar de `Model` y, opcionalmente, de los Mixins de Nori que desees otorgar.

```python
from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin

class User(NoriModelMixin, Model):
    id = fields.IntField(pk=True)
    slug = fields.CharField(max_length=50, unique=True)
    name = fields.CharField(max_length=100)
    level = fields.IntField(default=0)
    status = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'user'  # Recomendado: Explicitar exactamente la tabla SQL
```

### NoriModelMixin (`to_dict`)
Heredar este mixin junto con el Modelo de Tortoise añade una funcionalidad vital para despachar respuestas JSON puras. Exclusivamente inyecta el método `.to_dict(self, exclude=[])` eliminando rastro de metadatos o instancias ORM internas y resolviendo automáticamente todo en variables primitivas.

```python
user = await User.get(id=1)
# Dump de JSON rápido omitiendo campos sensibles:
data = user.to_dict(exclude=['id', 'level']) 
```

## Búsquedas, Inserción y Modificación Básica

```python
# Create
nuevo = await User.create(name='Ellery', slug='ellery-1')

# Update
user = await User.get(id=1)
user.name = 'Ellery Modificado'
await user.save()

# Select y Filtro
activos = await User.filter(status=True).all()
el_primero = await User.filter(slug='foo').first()

# Select de registros específicos y exclusiones
mayores_a_5 = await User.filter(level__gt=5).all()
no_activos = await User.exclude(status=True).all()
```

*(Consulta la documentación general de Tortoise ORM en caso de buscar comportamientos avanzados como `Q()`, `F()`, prefetching o raw SQL).*

## Mixins Avanzados Nativos

Nori posee capas abstraídas pre-construidas en forma de mixins de Python para resolver tareas repetitivas modernas.

### NoriSoftDeletes (Eliminación Lógica)
Protege la entropía transaccional previniendo eliminaciones `DROP` o `DELETE` contundentes de SQL. Requiere previamente inyectar a la base de datos una columna en dicho modelo denominada `deleted_at (TIMESTAMP NULL)`.

```python
from core.mixins.soft_deletes import NoriSoftDeletes

class Post(NoriSoftDeletes):  # <--- Sustituir "Model" por "NoriSoftDeletes"
    title = fields.CharField()
```

Funciones habilitadas:
* `await post.delete()` -> Seteará silenciosamente el status y actualizará *deleted_at* con `NOW()`. Al lanzar un `filter()` sobre objetos en DB, estarán pre-filtrados omitiéndolos automáticamente.
* `await post.restore()` -> Cambiará *deleted_at* de nuevo a Null retornándolo al pre-filtro activo.
* `await post.force_delete()` -> Saltará el override disparando la purga DELETE a la DB.
* `await Post.with_trashed().all()` -> Trae todos en masa.
* `await Post.only_trashed().all()` -> Excluye activos, mostrando exclusivamente papeleras purgas virtuales.

### NoriTreeMixin (Recursión Adjacente Avanzada CTE)
Convierte una tabla en un ecosistema auto-referenciable recursivo. Útil en categorías infinitas, permisos anidados o jerarquías corporativas. Requiere explícitamente tener la Foreign Key registrada de título `"parent"`.

```python
from core.mixins.tree import NoriTreeMixin

class Category(NoriTreeMixin):
    name = fields.CharField(max_length=100)
    parent = fields.ForeignKeyField('models.Category', related_name='children_rel', null=True, default=None)
```

Funciones inyectadas nativamente:
* `await node.children()`
* `await node.ancestors()` (Resolución CTE en una query, desde el item hasta el abuelo de la raíz).
* `await node.descendants()` (Resolución CTE vertical total al vacío en la sola query).
* `await node.move_to(new_parent_id=5)`
