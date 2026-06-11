# Tasks: csrf-double-submit

> **Change**: `csrf-double-submit` — Replace session-bound CSRF with OWASP signed double-submit cookie.
> **Spec**: `openspec/changes/csrf-double-submit/specs/csrf/spec.md` (REQ-CSRF-001 through REQ-CSRF-017)
> **Design**: `openspec/changes/csrf-double-submit/design.md` (architectural authority)
> **Nori version bump**: v1.x → v2.0.0 (breaking change)
> **TDD mode**: STRICT — RED tests first, then implementation, refactor last.

Legend: `[x]` done, `[ ]` pending. Tasks are sequential unless noted as `(parallel)`.

---

## Phase 0 — Environment Bootstrap

> Prerequisite for everything. No tests can run without this.

### 0.1 — Create project venv and install dev dependencies

- [x] `python3 -m venv .venv` at repo root
- [x] `.venv/bin/pip install -r requirements-dev.txt` (do NOT use `pip install --user`)
- [x] Verify: `.venv/bin/pytest tests/ --co -q` exits 0 (collection succeeds)

**Refs**: Strict TDD gate; no specific REQ-CSRF-### (infrastructure only).

### 0.2 — Pin current green baseline

- [x] Run `pytest tests/` with the venv and capture the pass/fail count
- [x] Document the baseline: number of passing tests, failing tests (if any), and
  which of the ~13 session-bound CSRF tests are expected to fail after RED step
- [x] Record baseline in a comment at the top of `tests/test_core/test_csrf.py`
  (e.g. `# Baseline before csrf-double-submit: 27 tests, 27 passing`)

**Refs**: Pre-flight; no specific REQ-CSRF-### (baseline only).

---

## Phase 1 — RED Tests (write failing tests before any implementation)

> All tests in this phase MUST fail against current `main` when run with `pytest tests/`.
> Each test should fail for the RIGHT reason — not import errors, but assertion failures
> that prove the old session-bound behavior does not satisfy the new contract.

### 1.1 — Rewrite `tests/test_core/test_csrf.py`: wire-format and validation suite

- [x] Delete or comment out the ~13 tests that assert `session[_CSRF_SESSION_KEY]` behavior
  (they test the REMOVED contract; do not adapt them)
- [x] Import guard: update module-level imports — `_CSRF_SESSION_KEY` will be gone; remove it;
  keep `CsrfMiddleware`, `csrf_field`, `csrf_token` imports
- [x] Add helper `_scope_with_cookie(method, cookie_name, cookie_value, headers=None)` that
  builds an ASGI scope with the given cookie in the `Cookie` header and a minimal
  `http.cookie` dict (no `session` key — proving session independence)

Write these RED tests (each must FAIL now, GREEN after Phase 2.1 implementation):

- [x] `test_validate_accepts_raw_cookie_value`
- [x] `test_validate_accepts_masked_cookie_value`
- [x] `test_validate_rejects_signature_invalid_cookie`
- [x] `test_validate_rejects_unsigned_naive_double_submit`
- [x] `test_validate_rejects_mismatched_submission`
- [x] `test_masked_token_differs_per_render`
- [x] `test_validate_no_session_dependency`
- [x] `test_header_token_path_still_short_circuits`
- [x] `test_no_cookie_rejects`
- [x] `test_form_body_cap_default_is_10mb`
- [x] `test_form_body_cap_is_configurable`
- [x] `test_multipart_without_header_is_refused`
- [x] `test_urlencoded_form_masked_token_validates`
- [x] `test_urlencoded_form_missing_token_is_403`
- [x] `test_exempt_path_skips_validation`
- [x] `test_safe_method_passes_through`
- [x] `test_websocket_scope_passes_through`
- [x] `test_json_content_type_without_header_is_403`

### 1.2 — RED tests: cookie issuance (`tests/test_core/test_csrf.py` continued)

- [x] `test_csrf_cookie_set_when_absent`
- [x] `test_csrf_cookie_not_reissued_when_present`
- [x] `test_csrf_cookie_reissued_when_signature_invalid`
- [x] `test_host_prefix_forces_secure_path_no_domain`
- [x] `test_samesite_default_is_lax`
- [x] `test_pending_cookie_seeded_in_scope_before_handler`
- [x] `test_settings_default_cookie_name`

### 1.3 — RED tests: helper signatures (`tests/test_core/test_jinja.py`)

- [x] `test_csrf_field_accepts_request`
- [x] `test_csrf_field_uses_pending_cookie_when_no_cookie`
- [x] `test_csrf_token_returns_raw_cookie_value`
- [x] `test_csrf_token_returns_pending_cookie_on_first_visit`

### 1.4 — RED tests: cache safety (`tests/test_core/test_cache.py` + ASGI integration)

- [x] `test_cache_response_never_emits_cached_set_cookie`
- [x] `test_cross_visitor_cached_page_submit_with_shim_succeeds`
- [x] `test_cross_visitor_cached_page_submit_without_shim_403s`
- [x] `test_forged_cookie_writer_attack_fails`

### 1.5 — Verify RED state

- [x] Run `pytest tests/test_core/test_csrf.py tests/test_core/test_jinja.py tests/test_core/test_cache.py -v`
- [x] Confirm ALL new tests fail (not collection errors — real assertion failures)
- [x] Confirm existing passing tests that test INV-004 body-cap behavior are NOT broken

---

## Phase 2 — GREEN: Core Implementation

> Implement exactly enough to make all RED tests pass. No over-engineering.

### 2.1 — Rewrite `rootsystem/application/core/auth/csrf.py`

- [x] Module-level constants and settings helpers
- [x] HMAC helpers (`_sign_nonce`, `_cookie_signature_valid`)
- [x] BREACH masking helpers (`_mask`, `_unmask`, `_looks_masked`)
- [x] `CsrfMiddleware.__init__` (exempt_paths unchanged)
- [x] `CsrfMiddleware.__call__` full rewrite with send-wrapper and two-check validation
- [x] `_build_set_cookie_header` with `__Host-` constraints
- [x] Send-wrapper (body never buffered, INV-002)
- [x] `csrf_field(request)` — masked hidden input
- [x] `csrf_token(request)` — raw cookie value
- [x] All new tests pass; INV-004 tests preserved

### 2.2 — Update `rootsystem/application/core/jinja.py`

- [x] Add `csrf_token` to Jinja2 globals
- [x] `csrf_field` and `csrf_token` exported correctly

### 2.3 — Update `rootsystem/application/core/auth/__init__.py`

- [x] `_CSRF_SESSION_KEY` was never re-exported; confirmed clean
- [x] `CsrfMiddleware`, `csrf_field`, `csrf_token` still exported

### 2.4 — Add JS shim: `rootsystem/static/js/csrf.js`

- [x] Reads document.cookie for CSRF_COOKIE_NAME
  (judgment-day round 1: no longer hard-coded — reads window.NORI_CSRF_COOKIE_NAME
   rendered by base.html from config, falling back to 'csrftoken')
- [x] DOMContentLoaded: patches forms on submit
- [x] Patches fetch() for same-origin unsafe requests
- [x] Patches XMLHttpRequest.prototype.open/send
- [x] No HMAC, no server secrets

### 2.5 — Add `<script>` include to `rootsystem/templates/base.html`

- [x] Inserted before `</body>` using `/static/js/csrf.js` path
  (Note: used `/static/js/csrf.js` instead of `url_for(...)` to avoid breaking
  tests that use FakeRequest without url_for — consistent with how home.js is referenced)

### 2.6 — Pin cache regression test (already RED in 1.4)

- [x] `test_cache_response_never_emits_cached_set_cookie` passes without changes to cache.py
- [x] cache.py confirmed: only caches body_b64/status_code/media_type

### 2.7 — Run full new test suite

- [x] All 100 CSRF/jinja/cache tests pass; full suite 1054 passed (only pre-existing throttle failure)

---

## Phase 3 — GREEN: INVARIANTS.md and Settings

> Catalog and settings updates. (parallel) with Phase 4 docs where content does not overlap.

### 3.1 — Update `INVARIANTS.md`: INV-004 fix recipe (REQ-CSRF-015, design §10)

- [ ] Locate INV-004 entry
- [ ] Change fix recipe item (d): "Cap urlencoded body buffering at `CSRF_FORM_MAX_BODY_SIZE`
  (default 1 MiB)" → "(default 10 MB)"
- [ ] Update the "Related" or "Notes" line for INV-004: change "body cap previously documented
  as 10 MB while code is 1 MiB" → "body cap aligned to 10 MB in v2.0.0 (INV-015 instance
  closed)"
- [ ] Add instance row: `v2.0.0: session-bound CSRF replaced by signed double-submit cookie;
  body cap aligned to 10 MB`

### 3.2 — Add `INVARIANTS.md`: INV-030 new entry (REQ-CSRF-015, design §10)

- [ ] Insert INV-030 after INV-029 (or at the end of the active catalog) with the full text
  from `design.md §10` verbatim (CWE-352, fix recipe, both boundaries, detector maturity,
  coverage, instances, regression tests, related)
- [ ] The entry MUST state: cookie = `{nonce}.{sig}`, bare-nonce rejected, Set-Cookie never
  cached by `cache_response`, CSRF ⟂ auth boundary, CSRF ⟂ XSS boundary

### 3.3 — Add back-reference on INV-016 (REQ-CSRF-015, design §10)

- [ ] Locate INV-016 entry in `INVARIANTS.md`
- [ ] Add to its "Related" line: `INV-030 (CSRF cookie statelessness — the deliberate CSRF
  ⟂ auth boundary)`

### 3.4 — Update `rootsystem/application/settings.py` with CSRF_COOKIE_* defaults

- [x] Added all six `CSRF_COOKIE_*` keys with documented defaults
- [x] `CSRF_COOKIE_HTTPONLY = False` with comment "MUST stay False — the shim reads document.cookie"
- [x] `CSRF_FORM_MAX_BODY_SIZE = 10 * 1024 * 1024` (10 MB)
- [x] All values satisfy INV-029

### 3.5 — Verify INV-029 compliance (REQ-CSRF-013)

- [x] `test_settings_default_cookie_name` passes — no AttributeError/KeyError when setting absent

---

## Phase 4 — GREEN: Docs Update (INV-015, REQ-CSRF-016)

> (parallel) with Phase 3 after Phase 2 is GREEN. All five files are mandatory per INV-015.

### 4.1 — Rewrite CSRF section in `docs/security.md`

- [ ] Remove all session-bound CSRF language
- [ ] Document: signed double-submit mechanism (cookie = `{nonce}.{sig}`, HMAC-SHA256),
  two-check validation flow, send-wrapper cookie issuance, dual-accept (raw + masked)
- [ ] Document cookie attributes table (all six settings with defaults)
- [ ] Document the CSRF ⟂ session-revocation boundary explicitly (REQ-CSRF-014)
- [ ] Document body cap = **10 MB** (not 1 MiB) for urlencoded forms
- [ ] Document the `__Host-` prefix opt-in recommendation
- [ ] Document the JS shim requirement for cached form pages
- [ ] Section MUST NOT contain "session" in any CSRF-token-derivation context

### 4.2 — Update `docs/middleware.md`: CsrfMiddleware block

- [ ] Remove session-bound description ("`session['_csrf_token']` is set on each GET")
- [ ] Document cookie issuance via send-wrapper
- [ ] Document HMAC validation (two checks)
- [ ] Document `exempt_paths` (unchanged)
- [ ] Document the `X-CSRF-Token` header path and body-cap behavior
- [ ] Update body cap value: **10 MB**

### 4.3 — Update `docs/architecture.md`: middleware table row

- [ ] Update the CSRF row to reflect: "stateless cookie-based approach (signed double-submit)"
  — remove "session-bound" language

### 4.4 — Update `docs/controllers.md`: csrf_field comment

- [ ] Find `csrf_field(request.session)` reference (line ~137 per exploration)
- [ ] Replace with `csrf_field(request)` and update surrounding comment to reflect new signature

### 4.5 — Update `CLAUDE.md`: boilerplate block

- [ ] Change `{{ csrf_field(request.session)|safe }}` → `{{ csrf_field(request)|safe }}`
  in the Controller Method boilerplate (and anywhere else `csrf_field(request.session)`
  appears in boilerplate examples)

### 4.6 — Verify body-cap coherence across docs (INV-015)

- [ ] Search for "1 MiB" or "1 MB" in `docs/security.md`, `docs/middleware.md`,
  `docs/architecture.md` — must be absent or replaced with "10 MB"
- [ ] Search for `_DEFAULT_FORM_BODY_SIZE` and `1 * 1024 * 1024` in code — must be gone
  (replaced by `10 * 1024 * 1024`)

---

## Phase 5 — GREEN: Upgrade Guide

> New file — migration content for v2.0.0 users.

### 5.1 — Create `docs/upgrade-2.0.md`

- [ ] Copy migration guide content from `design.md §8` as the authoritative starting point
- [ ] Sections required:
  - **Breaking change summary** (v2.0.0 — CSRF is now stateless cookie-based)
  - **Quick path** (5 steps from design.md §8)
  - **Find-and-replace commands** (`rg` + `sd` one-liners for template migration)
  - **Shim include snippet** for non-`base.html` sites
  - **Settings block** (all six `CSRF_COOKIE_*` with defaults)
  - **What you do NOT need to do** (no DB migration, no controller changes)
  - **Migration checklist** (5 checkboxes from design.md §8)
  - **Verification step** (submit form on cached page from two browsers)

### 5.2 — Add version bump strategy note

- [ ] Create or update a `CHANGELOG.md` or `[Unreleased]` section entry:
  - Entry under `[Unreleased]` or `[2.0.0]`:
    - `feat!: replace session-bound CSRF with OWASP signed double-submit cookie (closes #29)`
    - `feat!: bump default CSRF form body cap from 1 MiB to 10 MB (INV-015 fix)`
    - `docs: add v2.0.0 upgrade guide for CSRF migration`
    - `invariants: add INV-030 (signed cookie + Set-Cookie never cached); update INV-004`
- [ ] Note: version bump to `2.0.0` happens at release time; do not hard-code version in
  implementation files (read from `pyproject.toml` or equivalent)

---

## Phase 6 — Refactor

> Clean up after all tests are green. No new behavior.

### 6.1 — Code cleanup in `core/auth/csrf.py`

- [ ] Ensure all module-level docstrings reflect the new body-buffering contract
  (update the module docstring to remove the "1 MiB" mention, reflect "10 MB")
- [x] Ensure `_looks_masked` is deterministic and has a clear comment explaining the
  sentinel (length/charset of the mask envelope vs. `{hex}.{hex}`)
  (judgment-day round 1: corrected the comment — no dot-position check; raw len 129
   is never ≡ 0 mod 4 so it can't be a base64 envelope, making the sets disjoint)
- [ ] Remove any dead code or leftover session-related logic

### 6.2 — Final full test run

- [ ] `pytest tests/ -v --tb=short` — full suite
- [ ] Coverage must be >= 86% (project gate per `openspec/config.yaml`)
- [ ] Zero regressions on non-CSRF tests
- [ ] New CSRF suite fully green

### 6.3 — Semgrep check (if applicable)

- [ ] Run `semgrep --config .semgrep/ .` (or equivalent) — confirm no new rule violations
- [ ] The change should not trigger any existing Semgrep rules; new INV-030 has no L3
  Semgrep rule (noted as not feasible statically in exploration.md)

---

## Phase 7 — Work-Unit Commits (pre-PR)

> Each commit is a reviewable work unit. Tests ship with the behavior they verify.
> Sequence: RED tests → GREEN implementation → docs → invariants → guide.

Planned commit sequence (maps to PR slices — see Review Workload Forecast):

- [x] **WU-1** `test(csrf): RED suite for signed double-submit validation + cookie issuance`
  — Adds all Phase 1 failing tests. Repo intentionally RED after this commit.
- [x] **WU-2** `feat!(csrf): rewrite CsrfMiddleware for signed double-submit cookie`
  — Phase 2.1–2.3 + 2.6; makes WU-1 tests GREEN. Removes `_CSRF_SESSION_KEY`.
  WU-4 (body cap) bundled here (trivial — single constant change).
- [x] **WU-3** `feat(csrf): add JS shim and base.html include`
  — Phase 2.4–2.5; ships `csrf.js` and the `<script>` tag.
- [x] **WU-4** `fix(csrf): bump form body cap 1 MiB → 10 MB (INV-015)`
  — Bundled with WU-2 (trivial single-constant change, as tasks.md allows).
- [ ] **WU-5** `docs(invariants): add INV-030, update INV-004, back-reference INV-016`
  — Phase 3.1–3.3.
- [ ] **WU-6** `docs(security,middleware,architecture,controllers): CSRF rewrite (INV-015)`
  — Phase 4.1–4.6.
- [ ] **WU-7** `docs(upgrade): add v2.0.0 migration guide + CHANGELOG entry`
  — Phase 5.1–5.2.
- [ ] **WU-8** `refactor(csrf): cleanup docstrings and dead code`
  — Phase 6.1; no behavior change.

---

## Review Workload Forecast

### Line estimate breakdown

| Area | Files touched | Estimated changed lines |
|---|---|---|
| `core/auth/csrf.py` rewrite | 1 | ~200 (full rewrite: +220, -100) |
| `tests/test_core/test_csrf.py` rewrite | 1 | ~300 (delete 13 tests, add 25+ new) |
| `tests/test_core/test_jinja.py` updates | 1 | ~60 |
| `tests/test_core/test_cache.py` additions | 1 | ~80 |
| `rootsystem/static/js/csrf.js` new | 1 | ~50 |
| `rootsystem/templates/base.html` | 1 | ~5 |
| `docs/security.md` CSRF section rewrite | 1 | ~80 |
| `docs/middleware.md` CsrfMiddleware block | 1 | ~40 |
| `docs/architecture.md` row update | 1 | ~5 |
| `docs/controllers.md` comment | 1 | ~3 |
| `CLAUDE.md` boilerplate | 1 | ~3 |
| `INVARIANTS.md` INV-030 + INV-004 + INV-016 | 1 | ~80 |
| `docs/upgrade-2.0.md` new | 1 | ~80 |
| `CHANGELOG.md` entry | 1 | ~10 |
| `rootsystem/application/settings.py` | 1 | ~15 |
| `rootsystem/application/core/jinja.py` | 1 | ~5 |
| `rootsystem/application/core/auth/__init__.py` | 1 | ~3 |
| **TOTAL** | **17 files** | **~1 020 lines** |

> **Code + tests alone** (csrf.py + test files): ~640 lines.
> **Docs alone** (security + middleware + architecture + controllers + CLAUDE + invariants + upgrade + changelog): ~316 lines.

### Forecast

| Metric | Value |
|---|---|
| **Estimated total changed lines** | ~1 020 |
| **Code / tests split** | ~640 lines |
| **Docs / invariants split** | ~316 lines |
| **Other (settings, templates, js)** | ~64 lines |
| **Chained PRs recommended** | **Yes** |
| **400-line budget risk** | **High** |
| **Decision needed before apply** | **Yes** |

### Natural PR slice boundaries (if chaining chosen)

These slices are independently green and reviewable. Each PR's test suite passes in isolation.

**PR #1 — Core: RED tests + implementation + JS shim** (~640 lines)

Commits: WU-1, WU-2, WU-3, WU-4 (if not bundled)
Files: `core/auth/csrf.py`, `tests/test_core/test_csrf.py`, `tests/test_core/test_jinja.py`,
`tests/test_core/test_cache.py`, `rootsystem/static/js/csrf.js`,
`rootsystem/templates/base.html`, `rootsystem/application/core/jinja.py`,
`rootsystem/application/core/auth/__init__.py`, `rootsystem/application/settings.py`

Verification gate: `pytest tests/test_core/test_csrf.py tests/test_core/test_jinja.py tests/test_core/test_cache.py -v` — all green; overall suite no regressions; coverage >= 86%.

**PR #2 — Docs: INVARIANTS + security docs + upgrade guide** (~380 lines)

Commits: WU-5, WU-6, WU-7, WU-8
Files: `INVARIANTS.md`, `docs/security.md`, `docs/middleware.md`, `docs/architecture.md`,
`docs/controllers.md`, `CLAUDE.md`, `docs/upgrade-2.0.md`, `CHANGELOG.md`

Verification gate: docs coherence check (no "1 MiB" or "request.session" CSRF language
remaining); `pytest tests/` still green (no code changed).

> **Note**: If the orchestrator and user choose `single-pr` with `size:exception`, all WUs
> ship in one PR and the slice boundaries above serve as internal review checkpoints only.
> If `stacked-to-main`, PR #1 merges first; PR #2 targets main after PR #1 lands.
> If `feature-branch-chain`, create a tracker branch; PR #1 targets the tracker; PR #2
> targets PR #1's branch; tracker merges to main after both land.
