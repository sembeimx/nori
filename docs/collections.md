# Collections and Listings

In Nori, iterating over the Database is simple. However, to manipulate complex business logic in multivariable lists, `NoriCollection` provides an ergonomic superpowers wrapper heavily based on Laravel Collection.

## Collections

If you need to wrap a list and chain list flow manipulation in a few lines of code, simply invoke `collect()`.

```python
from core.collection import collect

base_list = await User.all() # General Tortoise return (flat List)
nori_collection = collect(base_list)
```

### Exploring Options

You can chain requests without interfering with or mutating your base asynchronous primitive list.

**Pluck / Sum / Max:**
Value extraction in a native list or absolute counters for sums and extremes.

```python
names = collect(users).pluck('name')
# ['ellery', 'foo', 'bar']
total_score = collect(games).sum('score')
highest_score = collect(games).max('score')
```

**Where:**
In-memory algorithmic filters without hitting or wearing down the DB.
Acceptable logical operators: `=`, `!=`, `>`, `<`, `>=`, `<=`.

```python
admins = collect(users).where('role', 'admin')           # Returns Collection
expensive = collect(products).where('price', '>', 500)   # Returns Collection
```

**GroupBy / Chunk / Sorted:**
Structured groupers and multidimensional arrays in memory: 

```python
by_role = collect(users).group_by('role')
# {'admin': [User1], 'guest': [User2, User3]}

by_rows_of_three = collect(users).chunk(3)
# [[1, 2, 3], [4, 5, 6], [7]]
```

### Iterable Mutations

**Map / Each:**

```python
# Map (Modifies and reforms a new dictionary/value for each iteration of the Collection)
prices_with_tax = collect(products).map(lambda p: p.price * 1.16)

# Each (Linear and transversal mutation or execution)
collect(users).each(lambda u: notify_admin(u))
```

At the end of the chaining, or when sending it serialized to the API, you can close it with `to_list()` (native array) or `to_dict()` in the case of ORM models.

---

## Asynchronous Pagination

Any list logic should never exceed local computational limits or bottleneck a frontend; this reason always urges the use of `paginate()` as a turnkey solution for list-view pages and APIs.

```python
from core.pagination import paginate

async def product_list(self, request):
    current_page = int(request.query_params.get('page', 1))
    
    # 1. Create base async query
    queryset = Product.filter(status=True).order_by('-id')

    # 2. Invoke dict paginator (limit=20)
    result = await paginate(queryset, page=current_page, per_page=20)
    
    # [JSON / HTML Return, Injecting Paginator into templates]
```

### Paginated Return

The returned dictionary has the following unified and leap-limit shielded structure:

```python
{
    'data': NoriCollection([Product, Product...]),  # Resulting iterative NoriCollection
    'total': 455,                    # Absolute total of available indexed records
    'page': 3,                       # Validated current page int state
    'per_page': 20,                  # Per-page ratio used in chunking
    'last_page': 23,                 # Asymptotic calculation of the last available active slot
}
```

Using Jinja2 templates and `range()` you can dynamically forge an aesthetic bottom Paginator over this dict structure.
