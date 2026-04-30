# Collections and Listings

In Nori, iterating over the database is simple. For advanced list manipulation, `NoriCollection` provides a chainable wrapper with filtering, sorting, grouping, and aggregation methods.

A chain like `collect(users).where('role', 'admin').pluck('name')` reads like the business logic you are expressing. Chains are composable, readable, and don't mutate the original data.

## Collections

If you need to wrap a list and chain list flow manipulation in a few lines of code, simply invoke `collect()`.

```python
from core.collection import collect

base_list = await User.all() # General Tortoise return (flat List)
nori_collection = collect(base_list)
```

### Method Reference

All methods return a new `NoriCollection` unless noted otherwise, so you can chain them freely.

#### Accessors

| Method | Returns | Description |
|--------|---------|-------------|
| `first()` | item or `None` | First element of the collection |
| `last()` | item or `None` | Last element of the collection |
| `is_empty()` | `bool` | `True` if the collection has no items |

#### Filtering

```python
admins = collect(users).where('role', 'admin')           # equality (default)
expensive = collect(products).where('price', '>', 500)    # with operator
```

`where(key, operator_or_value, value)` supports operators: `=`, `!=`, `>`, `<`, `>=`, `<=`.

#### Extraction

```python
names = collect(users).pluck('name')
# ['ellery', 'foo', 'bar']
```

`pluck(key)` returns a plain `list` of values extracted from each item.

#### Transformation

```python
# Map — returns a new collection with transformed items
prices_with_tax = collect(products).map(lambda p: p.price * 1.16)

# Each — applies a function to each item and returns self (for side effects)
collect(users).each(lambda u: notify_admin(u))

# Sort — returns a new sorted collection (None values sort to the end)
by_name = collect(users).sort_by('name')
by_name_desc = collect(users).sort_by('name', reverse=True)

# Unique — deduplicate by field or entire items
unique_roles = collect(users).unique('role')
unique_items = collect(items).unique()  # by identity
```

#### Aggregation

```python
total_score = collect(games).sum('score')
average = collect(games).avg('score')
lowest = collect(games).min('score')
highest = collect(games).max('score')
```

`sum()` returns `0` for empty collections. `avg()` returns `None` for empty collections. `min()` and `max()` return `None` when no non-null values exist.

#### Grouping & Chunking

```python
by_role = collect(users).group_by('role')
# {'admin': NoriCollection([User1]), 'guest': NoriCollection([User2, User3])}

by_rows_of_three = collect(users).chunk(3)
# [NoriCollection([1, 2, 3]), NoriCollection([4, 5, 6]), NoriCollection([7])]
```

`group_by(key)` returns a `dict` of `NoriCollection` instances. `chunk(size)` returns a `list` of `NoriCollection` instances.

#### Serialization

```python
# to_list() — converts each item via to_dict() if available, else uses the raw item
json_ready = collect(users).to_list()

# to_dict(key_field) — indexes items by a key field
users_by_id = collect(users).to_dict('id')
# {1: User1, 2: User2, 3: User3}
```

---

## Asynchronous Pagination

Any list logic should never exceed local computational limits or bottleneck a frontend; this reason always urges the use of `paginate()` as a turnkey solution for list-view pages and APIs.

```python
from core.pagination import paginate

async def product_list(self, request):
    current_page = int(request.query_params.get('page', 1))

    # 1. Create base async query
    queryset = Product.filter(status=True).order_by('-id')

    # 2. Invoke dict paginator (limit=20, max=500)
    result = await paginate(queryset, page=current_page, per_page=20)

    # [JSON / HTML Return, Injecting Paginator into templates]
```

`per_page` is capped at a maximum of **500** to prevent memory exhaustion from malicious or accidental large page requests. Values below 1 default to 20.

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

---

## When NOT to use `NoriCollection`

`NoriCollection` is designed for in-memory results that have already been bounded — typically a paginated page or a small cohort returned by a deliberate query. Each chained method (`where`, `sort_by`, `map`) returns a new collection, the same convention as Laravel Collections, lodash, and pandas DataFrames. That immutability is intentional and reads cleanly, but it means every step allocates.

For datasets too large to comfortably hold in memory (thousands of rows or more), reach for these instead:

- **`paginate()`** (above) — the turnkey solution for list views and APIs. Caps at 500 per page.
- **Tortoise QuerySet** directly — push the work to the database rather than hydrating model instances. Prefer `await User.filter(status=True).count()` over `len(collect(await User.filter(status=True)))`, and aggregate fields with `await Order.filter(...).values_list('total', flat=True)` instead of `collect(...).pluck('total')`.
- **Tortoise [`values_list()`](https://tortoise.github.io/query.html#tortoise.queryset.QuerySet.values_list)** — returns plain tuples instead of model instances, which is dramatically lighter for read-only aggregation.

Rule of thumb: if the question is *"can `NoriCollection` handle 50k records?"* the answer is *"it can, but you almost certainly shouldn't be loading 50k records into a Python process to begin with — push the work to the database."*
