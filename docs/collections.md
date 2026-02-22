# Colecciones y Listados

En Nori, iterar sobre la Base de Datos es simple. Sin embargo, para manipular lógica empresarial compleja en listas multivariables, `NoriCollection` provee un Wrapper de superpoderes ergonómico basado fuertemente en Laravel Collection.

## Colecciones

Si requieres envolver una lista y encadenar manipulación de flujos de listas en pocos strings de código, simplemente invoca `collect()`.

```python
from core.collection import collect

lista_base = await User.all() # Retorno general Tortoise (Lista plana)
nori_collection = collect(lista_base)
```

### Explorando Opciones

Puedes encadenar peticiones sin interferir o dañar tu lista primitiva asincrónica base.

**Pluck / Sum / Max:**
Extracción de valores en lista nativa o contadores absolutos de sumatorias y extremos.

```python
nombres = collect(usuarios).pluck('name')
# ['ellery', 'foo', 'bar']
total_score = collect(juegos).sum('score')
highest_score = collect(juegos).max('score')
```

**Where:**
Filtros algoritmicos de in-memory sin ir o desgastar a la BD.
Operadores lógicos aceptables: `=`, `!=`, `>`, `<`, `>=`, `<=`.

```python
admins = collect(usuarios).where('role', 'admin')           # Retorna Colección
caros = collect(productos).where('price', '>', 500)         # Retorna Colección
```

**GroupBy / Chunk / Sorted:**
Agrupadores estructurados y matrices multidimensionales en memoria: 

```python
por_rol = collect(usuarios).group_by('role')
# {'admin': [User1], 'guest': [User2, User3]}

por_filas_de_tres = collect(usuarios).chunk(3)
# [[1, 2, 3], [4, 5, 6], [7]]
```

### Mutaciones en Iterables

**Map / Each:**

```python
# Map (Modifica y reforma un nuevo diccionario/valor por cada iteración del Collection)
precios_con_iva = collect(productos).map(lambda p: p.price * 1.16)

# Each (Mutación o ejecución lineal y transversal)
collect(usuarios).each(lambda u: notificar_admin(u))
```

Al final del encadenamiento, o al enviarlo serializado al API, puedes cerrar con `to_list()` (array nativo) o `to_dict()` en caso de modelos ORM.

---

## Paginación Asíncrona

Toda lógica en listado no debería jamás superar límites computacionales locales ni estrangular a un frontend; este motivo insta siempre a utilizar `paginate()` como solución llave-en-mano para las páginas list-view y APIs.

```python
from core.pagination import paginate

async def product_list(self, request):
    page_act = int(request.query_params.get('page', 1))
    
    # 1. Creamos base query asíncrono
    queryset = Product.filter(status=True).order_by('-id')

    # 2. Invocamos paginador dict (limit=20)
    result = await paginate(queryset, page=page_act, per_page=20)
    
    # [Retorno JSON / HTML Inyectando Paginador a plantillas]
```

### Retorno Paginado

El diccionario devuelto posee la siguiente estructura unificada y blindada de validaciones de límites de salto:

```python
{
    'data': NoriCollection([Product, Product...]),  # NoriCollection iterativa resultante
    'total': 455,                    # Absoluto total registros indexados disponibles
    'page': 3,                       # Estado int página actual validada
    'per_page': 20,                  # Ratio per-page utilizado en chunking
    'last_page': 23,                 # Calculo asintótico último slot activo disponible
}
```

Usando plantillas Jinja2 y `range()` puedes forjar dinámicamente un Paginador inferior estético sobre esta estructura dict.
