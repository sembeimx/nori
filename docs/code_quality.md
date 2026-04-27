# Code Quality

Nori ships pre-configured with [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. The configuration lives in `pyproject.toml` at your project root and is yours to customize. CI runs the same checks locally, so style and obvious bugs are caught at PR time, not at runtime.

Quality is not optional. Lint catches real bugs (unused imports, missing exception chains, type comparisons that look right but aren't), and format keeps the codebase consistent across contributors. Both run in milliseconds — there's no excuse to skip them.

---

## What ships configured

A single `pyproject.toml` at the project root holds the lint and format setup:

```toml
[tool.ruff]
line-length = 120
target-version = "py39"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "single"
indent-style = "space"
```

| Rule group | What it catches |
|------------|-----------------|
| `E`, `W` | pycodestyle errors and warnings (indentation, whitespace, comparisons) |
| `F` | pyflakes — unused imports, undefined names, redefined-while-unused |
| `I` | isort — import ordering (auto-fixable) |
| `UP` | pyupgrade — modernize syntax to your declared `target-version` |
| `B` | flake8-bugbear — likely bugs (mutable defaults, misuse of `assert`, etc.) |

`E501` (line-too-long) is delegated to the formatter. The format defaults are `single` quotes (matching the dominant convention in framework code) and 4-space indentation.

---

## Running locally

After `pip install -r requirements-dev.txt`, ruff is on your venv's `PATH`.

### Lint

```bash
ruff check .                  # report all violations
ruff check . --fix            # apply auto-fixes (imports, unused, whitespace, modernizations)
ruff check . --statistics     # tally by rule code
ruff check . --select F841    # only one rule
```

Auto-fixes are conservative — only changes that ruff guarantees are semantics-preserving are applied. Anything ruff considers risky is shown but not modified, and you can opt in with `--unsafe-fixes` after reviewing.

### Format

```bash
ruff format .                 # rewrite files in place
ruff format --check .         # verify formatting; non-zero exit if any file would change
ruff format --diff .          # preview what would change
```

`ruff format` is intentionally narrow — it never moves code, only reformats whitespace, line breaks, quotes, and trailing commas. It's safe to run repeatedly.

---

## CI gate

Every push and pull request to `main` runs the `Lint` workflow at `.github/workflows/lint.yml`:

```yaml
- uses: astral-sh/ruff-action@v3
- run: ruff check .
- run: ruff format --check .
```

Two separate steps so failures categorize cleanly: a lint failure says "fix the rule", a format failure says "run `ruff format`". The CI uses the same `pyproject.toml` you use locally, so passing locally implies passing in CI.

---

## Per-file-ignores

Sometimes a rule has to break for architectural reasons — a bootstrap hook that legitimately needs imports out of order, a settings module that loads `.env` before reading vars, a test that patches `sys.path` before importing the module under test.

For these cases, document the exception once in `pyproject.toml` rather than scattering `# noqa` comments across many lines:

```toml
[tool.ruff.lint.per-file-ignores]
# Bootstrap hook MUST run before framework/third-party imports so observability
# SDKs (Sentry, OTel, Datadog) can patch instrumentable libraries at load time.
"rootsystem/application/asgi.py" = ["E402"]

# warnings.filterwarnings must precede framework imports — suppresses the
# Tortoise "Module 'X' has no models" RuntimeWarning fired during registration.
"rootsystem/application/core/__init__.py" = ["E402"]

# load_dotenv() must run before any module that reads env vars at import time.
"rootsystem/application/settings.py" = ["E402"]

# Test setup commonly needs sys.path edits, env var injection, or importlib
# patches before importing the module under test.
"tests/**/*.py" = ["E402"]
```

The comment above each entry is non-negotiable. A per-file-ignore without a justification is a bug being hidden, not a deliberate exception. If a future contributor can't tell why the rule is silenced, the rule should not be silenced.

For a one-off line that genuinely needs to break a rule (rare), use `# noqa: <code>` with an inline comment:

```python
import bad_practice  # noqa: F401 — re-exported for backward compatibility, see CHANGELOG 1.4.0
```

---

## Customizing for your project

The `pyproject.toml` is yours after install — `framework:update` does not replace it. Tighten or relax the configuration as your project matures.

### Adding stricter rules

```toml
[tool.ruff.lint]
select = [
    "E", "W", "F", "I", "UP", "B",
    "S",    # flake8-bandit — security checks
    "SIM",  # flake8-simplify — code simplification suggestions
    "RET",  # flake8-return — return-statement consistency
    "TCH",  # flake8-type-checking — move type-only imports to TYPE_CHECKING
]
```

Run `ruff check . --statistics` after enabling new rule groups to see the impact, then either fix them or selectively ignore the ones that don't fit your project.

### Relaxing for tests

Test code often violates rules that make sense in production code (long functions, magic numbers, fixture imports). Add a per-file-ignore:

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["E402", "S101"]  # imports after sys.path setup, asserts are fine in tests
```

### Custom line length

```toml
[tool.ruff]
line-length = 100  # default is 88; Nori ships with 120 to match existing code
```

---

## Adopting in existing Nori projects

`framework:update` does not retrofit `pyproject.toml` or `requirements-dev.txt` — both are user-owned files that the framework never replaces after the first install. To adopt ruff in a project created on Nori ≤ 1.10.6:

1. Add `ruff>=0.6` to your `requirements-dev.txt`.
2. Copy [`pyproject.toml`](https://github.com/sembeimx/nori/blob/main/pyproject.toml) from the framework repo to your project root, or write your own.
3. Run `.venv/bin/pip install -r requirements-dev.txt`.
4. Run `ruff check . --fix` to apply auto-fixes — review the diff, commit if you're happy.
5. Run `ruff format .` to apply formatting in a separate commit. Add the commit's hash to a `.git-blame-ignore-revs` file at the repo root so `git blame` skips it:

   ```
   <full-sha>  # style: ruff format pass
   ```

   Activate locally with `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

6. Optionally, copy `.github/workflows/lint.yml` to gate future PRs.

---

## Pre-commit hooks

Nori ships with `.pre-commit-config.yaml` so ruff runs on every `git commit`. CI catches violations after the push, but pre-commit catches them before — saving the round trip.

### Activate once per clone

```bash
.venv/bin/pip install -r requirements-dev.txt   # installs pre-commit
.venv/bin/pre-commit install                    # writes .git/hooks/pre-commit
```

After that, every `git commit` runs:

- `ruff check --fix` — lint and auto-fix
- `ruff format` — format

If either modifies files, the commit is aborted so you can review the changes and re-stage. The first run downloads ruff into pre-commit's isolated environment; subsequent runs are fast (~100ms).

### Run against all files manually

Useful before opening a PR or after pulling someone else's changes:

```bash
.venv/bin/pre-commit run --all-files
```

### Bump the ruff version

```bash
.venv/bin/pre-commit autoupdate
```

Updates `rev:` in `.pre-commit-config.yaml` to the latest stable tag of `astral-sh/ruff-pre-commit`. Commit the resulting diff so other contributors pick up the same version.

### Skipping hooks

`git commit --no-verify` bypasses the hooks. **Avoid it.** If a hook is firing on something you believe is wrong, fix the rule (per-file-ignore or pyproject.toml change) rather than the symptom.

---

## Test coverage

Nori ships pre-configured with [`pytest-cov`](https://pytest-cov.readthedocs.io/) so every test run measures how much of `rootsystem/application` was exercised. The `Tests` workflow in CI reports coverage on every push and fails the build if the project drops below the configured threshold.

### Running locally

```bash
pytest tests/ --cov                    # coverage report at the end of the run
pytest tests/ --cov --cov-report=html  # HTML report at htmlcov/index.html
pytest tests/ --cov --cov-report=xml   # XML for external dashboards
```

Coverage configuration lives in `pyproject.toml` under `[tool.coverage]`. Branch coverage is enabled — both lines and conditional branches must be covered.

### Threshold

`fail_under = 75` is the floor. Drops below 75% fail CI. The threshold is intentionally below today's baseline so room to refactor exists, but it should rise as the project grows. Bump it any time the project sustains a higher number for a few releases.

### What is excluded

- `migrations/` — engine-specific SQL generated by aerich, not framework logic
- `seeders/example_seeder.py` and `commands/_example.py` — templates meant to be edited by users
- Lines marked `# pragma: no cover` (use sparingly, only where coverage truly cannot reach)
- `if TYPE_CHECKING:` blocks (imports for static type checkers, not runtime)

### Adding it to your project

Existing Nori projects can opt in with the same setup:

1. Add `pytest-cov>=5.0` to `requirements-dev.txt`.
2. Copy the `[tool.coverage.run]` and `[tool.coverage.report]` sections from the framework's `pyproject.toml` into your own.
3. Run `pytest --cov` locally and tune the `omit` list and `fail_under` threshold for your code.

---

## See also

- [Ruff documentation](https://docs.astral.sh/ruff/)
- [Coverage.py documentation](https://coverage.readthedocs.io/)
- [Dependencies](dependencies.md) — how `requirements-dev.txt` works alongside framework deps
- [Testing](testing.md) — pytest setup for Nori projects
