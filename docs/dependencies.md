# Dependencies

Nori splits Python dependencies in two: a framework-owned file (`requirements.nori.txt`) and a site-owned file (`requirements.txt`). This keeps framework min-versions in sync on every `framework:update` while leaving your site's deps completely under your control.

---

## File layout

| File | Owned by | Touched on update | Purpose |
|------|----------|-------------------|---------|
| `requirements.nori.txt` | Framework | **Replaced on every `framework:update`** | Mandatory Nori deps (Starlette, Tortoise, httpx, …) |
| `requirements.txt` | You | Never replaced — only patched once to add `-r` | Your site's deps + optional Nori drivers |
| `requirements-dev.txt` | You | Never touched | Dev/test deps (pytest, etc.) |

Your `requirements.txt` starts with `-r requirements.nori.txt`, which inlines the framework's list. Everything else in the file is yours.

---

## Why split?

The previous model had a single `requirements.txt` that mixed Nori's deps with your own. Two problems with that:

1. **Silent drift**: when Nori bumped `starlette>=0.35` in a new release, your `requirements.txt` still said `starlette>=0.28` and you never knew until something crashed at runtime.
2. **Noisy upgrades**: every `framework:update` that changed a Nori dep would have to either overwrite your file (bad — kills your additions) or be invisible (bad — causes drift).

With the split, the framework owns its minimums in a file it is free to replace, and you own your additions in a file that is never touched after the initial patch. `pip` resolves both via `-r`, and your pins always win over Nori's minimums.

---

## Adding a site dependency

Edit `requirements.txt` and add the line below the marker:

```text
-r requirements.nori.txt

# Optional Nori drivers — uncomment the ones your site uses.
# redis[hiredis]
# cryptography>=42.0

# Site-specific dependencies go below.
sentry-sdk[starlette]>=2.0
stripe>=10.0
```

Then:

```bash
.venv/bin/pip install -r requirements.txt
```

---

## Activating an optional Nori driver

Optional Nori drivers are commented in the `requirements.txt` scaffold. To enable one — say, Redis-backed cache/throttle/queue — uncomment the line:

```text
redis[hiredis]
```

And re-run `pip install -r requirements.txt`. That line is yours, so future framework updates will not re-comment it.

---

## What `requirements.nori.txt` contains

Only the framework's **mandatory** deps:

```text
starlette>=0.28
uvicorn[standard]>=0.29
tortoise-orm>=0.25
aerich>=0.8
asyncmy>=0.2
asyncpg>=0.29
jinja2>=3.1
python-multipart>=0.0.6
python-dotenv>=1.0
httpx>=0.27
itsdangerous>=2.1
typing-extensions>=4.0
gunicorn>=22.0
aiosmtplib>=3.0
```

This file has a "DO NOT EDIT" notice at the top. Every `framework:update` replaces it wholesale (with a timestamped backup under `rootsystem/.framework_backups/`).

Optional drivers (`redis`, `cryptography`) are **not** in `requirements.nori.txt` — they live commented in your `requirements.txt` so you control when to enable them without losing the setting on update.

---

## Pinning stricter versions

Your `requirements.txt` wins when more specific. If Nori ships `starlette>=0.28` but you need `starlette==0.37.2` for a compatibility reason, just add it to `requirements.txt`:

```text
-r requirements.nori.txt

starlette==0.37.2   # pinned — see INC-1234
```

pip resolves to `==0.37.2`. No conflict with the framework file.

---

## Upgrading an existing site to the split

If your site was created on Nori ≤ 1.6, the upgrade to 1.7 takes care of the wiring:

1. `python3 nori.py framework:update` — brings in `requirements.nori.txt` and replaces the framework directories. On sites coming from ≤ 1.6, the `-r` injection into your `requirements.txt` happens on the next run (see [observability.md](observability.md#upgrading-an-existing-site) for the reason). Run `framework:update --force` once to apply.
2. From 1.7 onwards, patches apply automatically on the same update that ships them — the patch system reloads itself from the newly installed core before running.
3. After patching, run `pip install -r requirements.txt` to refresh your environment.

Your old `requirements.txt` keeps all its entries, including framework deps that are now also in `requirements.nori.txt`. That is safe — pip deduplicates. If you want to clean up, delete the framework entries from your file manually; nothing forces you to.

---

## Docker

If your site uses the Docker setup shipped with Nori, the `Dockerfile` copies the requirements files during the builder stage:

```dockerfile
COPY requirements.txt requirements.nori.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
```

**Both files must be copied.** `pip install -r requirements.txt` resolves `-r requirements.nori.txt` at install time, so if only `requirements.txt` is present the build fails with `ERROR: -r requirements.nori.txt not found`.

If your site predates 1.7.1 and was based on an earlier Nori `Dockerfile`, add `requirements.nori.txt` to the `COPY` line manually — it is a one-line edit. The rest of the build is unchanged.

---

## Dev dependencies

`requirements-dev.txt` is yours and is never touched by `framework:update`. The convention is to start it with `-r requirements.txt` so dev installs include prod deps, then add testing tools:

```text
-r requirements.txt
pytest>=8.0
pytest-asyncio>=1.0
```

Because `requirements.txt` now `-r`s `requirements.nori.txt`, `pip install -r requirements-dev.txt` transitively installs everything. No changes needed.
