# Nori Invariants Catalog

> **Internal operational document. Do NOT publish.**
> Lives in the repository root so MkDocs (which only scans `docs/`) does not
> include it in https://nori.sembei.mx. Coverage gaps and detector maturity
> levels are an attack map; keep them internal.

## Purpose

A versioned catalog of every **bug class** discovered in Nori, with stable IDs,
CWE links, fix recipes, detector maturity, and coverage by area.

The catalog is the convergence mechanism for audits. Without it, every audit
re-discovers the same classes because the knowledge lives in CHANGELOG
narrative + AGENTS.md prose + maintainer memory. With it:

- Each new finding either matches an existing INV (regression — fix in code)
  or is a new class (add a new INV, decide a detector strategy).
- The next audit is split into two phases: (A) run the catalog's detectors
  against the delta since last sweep — should trend toward zero hits; (B)
  exploratory search for new classes — the only legitimate source of new INVs.
- Detector maturity tracks the cost of catching each class: L1 (manual) ⇒
  L3 (CI-enforced). Promoting L1/L2 entries to L3 is the highest-leverage
  audit follow-up.

## How to use this document

- **Before shipping a security-relevant change**: scan the catalog for
  related INVs (Ctrl-F by file path or CWE).
- **During an audit**: run all L2 detectors (grep recipes) and verify all
  L3 detectors are still active (Semgrep workflow green). New findings get
  filed as either a regression of an existing INV or a new INV.
- **After fixing a bug**: update the matching INV's coverage area and
  regression test list. If it was a new class, create a new INV entry.

## How to add a new INV

1. ID is the next integer (zero-padded to 3 digits). **IDs are stable forever**
   — never reuse, never reassign, never renumber.
2. Find the CWE at https://cwe.mitre.org/data/definitions/. If no clean match,
   use `Nori-specific` and explain why.
3. Use the template below. Keep each section short — one paragraph max.
4. If the class is mechanizable, file the Semgrep / test work as L1 → L2 → L3
   graduation in the catalog's "Roadmap" section at the bottom.

## INV template

```markdown
### INV-NNN: <Title — noun phrase>

- **CWE**: CWE-XXX (description) | Nori-specific
- **First seen**: vX.Y.Z (Round N | spot fix)
- **Status**: Active | Mitigated | Deprecated
- **Severity (max instance)**: HIGH | MED | LOW
- **Bug class**: One sentence describing the pattern (not any specific instance).
- **Fix recipe**: One sentence describing the correct pattern.
- **Detector maturity**:
  - L1 (manual review): yes/no
  - L2 (scripted): command or absent
  - L3 (mechanized): rule ID or absent
- **Coverage by area**: which framework areas have been swept against this INV.
- **Instances**: list of historical occurrences (version, file, one-line note).
- **Regression tests**: pytest IDs that pin the fix.
- **Related**: cross-links to other INV-NNN.
```

## Severity legend

- **HIGH**: exploitable security boundary (auth bypass, RCE, data leak, DoS).
- **MED**: security-adjacent hardening or correctness with security impact under stress.
- **LOW**: defense-in-depth, docs, observability.

## Detector maturity legend

- **L1** — Manual review only. Knowledge is in this catalog + reviewer memory.
- **L2** — Scripted check: a documented `rg` recipe, ad-hoc script, or test
  pattern. Run by hand during audits; not enforced in CI.
- **L3** — Mechanized in CI: Semgrep rule, custom pytest assertion,
  repo-state lint, or other automatic gate that blocks merge on regression.

Promotion path: every L1 in this catalog is technical debt. The audit
roadmap below tracks graduation candidates.

---

## Catalog

Listed in order of historical discovery (oldest first). IDs are stable.

---

### INV-001: Cache read-modify-write must be atomic (TOCTOU)

- **CWE**: CWE-367 (Time-of-check Time-of-use Race Condition) + CWE-362 (Race Condition)
- **First seen**: v1.18.0 (Round 4, systemic class fix)
- **Status**: Active (recurring — sweep new sites on every release)
- **Severity (max instance)**: HIGH
- **Bug class**: A function does `await cache_get(key)` → modify in Python → `await cache_set(key, ...)`. Under concurrency, two callers read the same baseline, both compute the same delta, both write the same value. The counter never advances; any security gate built on top (lockouts, rate limits, dedup) is silently disabled.
- **Fix recipe**: `cache_incr(key)` for scalar counters; `cache_atomic_update(key, fn, ttl)` for any other RMW. Both implemented in `core/cache.py` (memory: asyncio lock; Redis: Lua EVAL or WATCH/MULTI/EXEC retry).
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'cache_get|cache_set' <file>` + visual review for partner calls
  - L3: `.semgrep/nori-rules.yml::nori-toctou-cache-read-modify-write` (WARNING, since 2026-05). Scans full repo except `core/cache.py` (implementation) and tests.
- **Coverage by area**:
  - `core/auth/*`: swept Round 4 + L3 active
  - `core/http/throttle*`: swept Round 4 + L3 active
  - `core/queue*`: swept Round 4 + L3 active
  - `core/cache.py`: excluded from L3 (implementation site)
  - `core/auth/session_guard.py`: excluded from L3 (read-through accelerator pattern)
  - `services/*`: swept 2026-05-26 — zero `cache_get`/`cache_set` usages; trivially covered. L3 active going forward.
  - User code (`app/*`, `modules/*`): out of framework scope
- **Instances**:
  - v1.18.0: `login_guard.record_failed_login` — `cache_get` + `cache_set` on attempts dict
  - v1.18.0: `throttle_backends.add_timestamp` — separate `get_timestamps` + `add_timestamp`
  - v1.21.1: `login_guard` tier-escalation `>=` vs `==` — same family
  - v1.29.0: `cache.cache_incr` Memory backend TTL drift on existing no-TTL counter
  - v1.32.0: memory queue unbounded fan-out (no semaphore = no TOCTOU per se, same concurrency-hazard family)
- **Regression tests**: `test_brute_force_concurrent_attempts_trigger_lockout`, `test_attempts_above_threshold_without_lockout_do_not_re_escalate`, `test_memory_incr_does_not_apply_ttl_to_existing_no_ttl_counter`, `test_memory_queue_caps_concurrent_execution`, plus the new 50-coroutine throttle test
- **Related**: INV-021 (task GC under concurrency), INV-025 (Redis delayed-job double-execution)

---

### INV-002: Sync work must not block the asyncio event loop

- **CWE**: CWE-400 (Uncontrolled Resource Consumption — event loop starvation)
- **First seen**: v1.17.0 (Round 3) — local file upload write
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A blocking call (disk I/O, CPU-heavy crypto, network sync) runs directly inside an `async def`, freezing every other coroutine sharing that loop. Symptom: throughput collapses under load; a single slow disk or RSA refresh stalls the entire worker.
- **Fix recipe**: Wrap the blocking call in `asyncio.to_thread(...)`. Dispatch helper for callables of unknown async-ness: `inspect.iscoroutinefunction(f)` → `await f(...)` else `await asyncio.to_thread(f, ...)`.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'async def' --files-with-matches services/ | xargs rg -n 'open\(|time\.sleep|.*\.encrypt|.*\.sign'`
  - L3 (multiple rules, since 2026-05):
    - `nori-service-sync-open-in-async` (WARNING): `open()` in `services/*` async def
    - `nori-sync-time-sleep-in-async` (ERROR): `time.sleep()` in `core/* + services/*` async def (excludes tests)
    - `nori-sync-requests-import-in-services` (ERROR): `import requests` / `from requests import X` in `services/*` (httpx is the contract)
    - `nori-sync-subprocess-in-async` (ERROR): `subprocess.run/check_output/check_call/Popen` in async def in `core/* + services/*` (excludes `core/cli.py` which is a sync entry script)
  - Still L1/L2: sync crypto/hashing (`hashlib.pbkdf2_hmac`, `bcrypt.hashpw`), image decoding, `urllib.request.urlopen`. Difficult to mechanize without false positives because these calls are legitimate in non-async contexts; rely on per-PR review.
- **Coverage by area**:
  - `services/storage_gcs.py`: swept Round 4 (RSA + cred load via to_thread)
  - `services/*` (open, time.sleep, requests import, subprocess in async): L3 since 2026-05-26
  - `core/*` (time.sleep, subprocess in async): L3 since 2026-05-26
  - `core/cli.py`: excluded from subprocess rule (sync entry script — subprocess.run is correct primitive)
  - `core/http/upload.py`: swept Round 3 (`asyncio.to_thread` for disk write)
  - `core/auth/security.py`: swept v1.22.0 (PBKDF2 async)
  - `core/tasks.py`: swept v1.27.0 (background dispatcher offloads sync)
  - `core/queue_worker.py`: swept v1.30.0 (execute_payload offloads sync)
  - Other crypto callsites (JWT signing, etc.): **NOT explicitly swept** at L3
- **Instances**:
  - v1.17.0: `core/http/upload.py` write_bytes on loop
  - v1.18.0: `services/storage_gcs.py` `_load_credentials` + `_build_jwt`
  - v1.22.0: `core/auth/security.py` PBKDF2 hash_password / verify_password
  - v1.27.0: `core/tasks.py` background() sync dispatch
  - v1.30.0: `core/queue_worker.py` execute_payload sync dispatch
- **Regression tests**: `test_hash_password_does_not_block_event_loop`, `test_background_sync_callable_does_not_block_event_loop`, `test_execute_payload_offloads_sync_callable_to_thread`
- **Related**: INV-022 (httpx per-call adds latency same family)

---

### INV-003: Queue worker `func_path` must pass allow-list check (RCE defense)

- **CWE**: CWE-94 (Code Injection) + CWE-915 (Improperly Controlled Dynamic Attribute)
- **First seen**: v1.17.0 (Round 3, upgrade note 3)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: The queue payload's `func` field is used to import and invoke arbitrary Python code without restricting which modules are allowed. An attacker who can write to the queue store (compromised DB, MITM on Redis) gets RCE.
- **Fix recipe**: Three-layer defense in `core/queue_worker.py:execute_payload`: (1) `mod_path` matches a prefix in `QUEUE_ALLOWED_MODULES`; (2) the function name is a bare identifier (`^[A-Za-z_][A-Za-z0-9_]*$`); (3) post-`getattr`, recheck `func.__module__` against the allow-list to defeat re-exports.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'importlib.import_module|getattr' core/queue_worker.py`
  - L3: covered by behavior tests (no Semgrep rule; the rule would need to track that all three layers exist together — hard to express statically)
- **Coverage by area**:
  - `core/queue_worker.py`: fully covered by 3-layer test suite
  - User-supplied serializers (custom queue drivers): users must implement the same checks if they bypass `execute_payload`
- **Instances**:
  - v1.17.0: initial allow-list (prefix match)
  - v1.23.0: bare-identifier validation + `__module__` recheck to block `from os import system`
- **Regression tests**: `test_execute_payload_rejects_dotted_func_name`, `test_execute_payload_rejects_re_exported_os_system`, plus the `os.system` / `subprocess` / `builtins.exec` rejection tests
- **Related**: INV-019 (X-Request-ID injection — same family of "trust nothing from the network")

---

### INV-004: CSRF middleware must reject ambiguous request shapes

- **CWE**: CWE-352 (CSRF) + CWE-400 (DoS via body buffering)
- **First seen**: v1.17.0 (Round 3) — JSON exemption
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A condition in the CSRF middleware intended as convenience becomes a bypass — either a Content-Type exemption that browsers can satisfy cross-origin, or body buffering that creates a DoS amplifier.
- **Fix recipe**: (a) **No content-type exemptions** for browser-readable methods. JSON clients must send `X-CSRF-Token` header. (b) **Check the header before reading the body** so streaming and multipart uploads stay streamed. (c) Refuse `multipart/form-data` without the header (do NOT buffer to extract token). (d) Cap urlencoded body buffering at `CSRF_FORM_MAX_BODY_SIZE` (default 1 MiB).
- **Detector maturity**:
  - L1: yes (manual review on `core/auth/csrf.py` changes)
  - L2: pre-merge checklist for csrf.py — verify header-first, multipart refusal, body cap intact
  - L3: behavior tests + docs↔code mismatch caught by INV-015 manual checklist
- **Coverage by area**:
  - `core/auth/csrf.py`: full behavior coverage
- **Instances**:
  - v1.17.0: removed `application/json` short-circuit
  - v1.22.0: multipart-without-header refused, body cap configurable
- **Regression tests**: `test_multipart_without_header_is_refused`, `test_multipart_with_header_passes_without_buffering`, `test_form_body_cap_is_configurable`
- **Related**: INV-015 (docs↔code coherence — body cap previously documented as 10 MB while code is 1 MiB)

---

### INV-005: OAuth driver must reject unverified email

- **CWE**: CWE-290 (Authentication Bypass by Spoofing) + CWE-287 (Improper Authentication)
- **First seen**: v1.17.0 (Round 3)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: An OAuth driver returns the email from the provider without checking the verification flag. An attacker registers an OAuth identity with an unverified email matching an existing account they don't own and gets logged in as the victim.
- **Fix recipe**: Default `email = ''` when the provider reports `email_verified` is False. The raw value remains available at `profile['raw']['email']` for callers that explicitly opt in.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'email_verified|verified' services/oauth_*`
  - L3: behavior test per driver
- **Coverage by area**:
  - `services/oauth_google.py`: covered
  - `services/oauth_github.py`: GitHub returns verified-only emails by API design (`/user/emails` filters to verified); review on any provider added
  - New OAuth drivers (any future): contract: ALWAYS check verification flag, fail closed
- **Instances**:
  - v1.17.0: Google OAuth driver `email = data.get('email', '') if email_verified else ''`
- **Regression tests**: `test_get_user_profile_clears_email_when_unverified`, `test_get_user_profile_clears_email_when_verified_field_missing`
- **Related**: INV-007 (JWT optional-claim handling — same family of "third-party assertions need defensive defaults")

---

### INV-006: Search/filter user input must be escaped before DSL interpolation

- **CWE**: CWE-943 (Improper Neutralization of Special Elements in Data Query Logic)
- **First seen**: v1.17.0 (Round 3)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: User-supplied values are interpolated raw into a query DSL string without escaping, allowing operator injection (`field = "x" OR true` style) to read records the user is not authorized to see.
- **Fix recipe**: Escape backslashes and quotes in values; validate field keys against `^[A-Za-z_][A-Za-z0-9_.\-]*$`; raise `ValueError` for invalid keys.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n "f'.*\{.*\}'" services/search_meilisearch.py` (look for unescaped f-string interpolation)
  - L3: behavior test
- **Coverage by area**:
  - `services/search_meilisearch.py`: covered
  - Future search drivers (Elasticsearch, Typesense, etc.): contract enforced via test pattern
- **Instances**:
  - v1.17.0: Meilisearch `_build_filter_string` raw `f'{k} = "{v}"'`
- **Regression tests**: named in Round 3 changelog (no canonical name)
- **Related**: none

---

### INV-007: JWT/OAuth optional claims must be accessed defensively

- **CWE**: CWE-287 (Improper Authentication) + CWE-703 (Improper Check for Exceptional Conditions)
- **First seen**: v1.16.0 (spot) + v1.18.0 (Round 4)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: Two distinct shapes:
  1. A security check silently fails due to wrong abstraction access (e.g. `backend._store` introspection bypassing the cache interface, so Redis-backed revocations are silently ignored).
  2. An auth handler treats an optional spec field as required (`payload['jti']`), so a token without that claim crashes the handler — DoS path on logout/callback.
- **Fix recipe**: (a) Route all backend reads through the public cache API (`cache_get`), never the storage attribute. (b) Use `.get('claim')` for all RFC-optional fields; handle None explicitly.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n "payload\[" core/auth/`
  - L3: `.semgrep/nori-rules.yml::nori-jwt-payload-required-claim` (ERROR, since 2026-05). Restricted to `core/auth/*`. Covers `jti`, `sub`, `iss`, `aud`, `nbf`.
- **Coverage by area**:
  - `core/auth/jwt.py`: covered (revocation + claim access)
  - `core/auth/oauth.py`: covered
  - `services/oauth_*`: covered (callbacks also propagate HTTPStatusError with log — see PR #28)
  - Backend `_store` attribute access elsewhere: **NOT explicitly swept**
- **Instances**:
  - v1.16.0: `_is_blacklisted` read `backend._store` — only worked on MemoryBackend
  - v1.18.0: `revoke_token` raised `ValueError` on missing `jti` (RFC-optional)
- **Regression tests**: `test_revoke_token_blocks_verify_under_redis_backend`, plus the v1.18.0 missing-`jti` test
- **Related**: INV-005 (OAuth unverified email — same family of "defensive defaults for third-party data")

---

### INV-008: Serializers must respect `protected_fields`

- **CWE**: CWE-212 (Improper Removal of Sensitive Information) + CWE-200 (Information Exposure)
- **First seen**: v1.19.0 (Round 5)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A serialization path bypasses `protected_fields` (e.g. `NoriCollection.to_list()` falls back to `_meta.fields_map` for models without `NoriModelMixin`), emitting `password_hash`, tokens, and other secrets to JSON responses.
- **Fix recipe**: All serialization goes through `.to_dict()`. Raise `TypeError` if a Model-shaped object lacks `to_dict()` rather than silently falling back to full field dump.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'fields_map|_meta\.' core/`
  - L3: behavior test (`test_to_list_documents_popo_contract` v1.28.0 pins contract)
- **Coverage by area**:
  - `core/collection.py`: covered
  - Manual `JSONResponse({field: value, ...})` in user code: out of scope (users must use `.to_dict()`; documented)
- **Instances**:
  - v1.19.0: `NoriCollection.to_list()` raised TypeError on non-NoriModelMixin Tortoise Models
- **Regression tests**: `test_to_list_documents_popo_contract`
- **Related**: INV-019 (CR/LF in mail / log — also a sensitive-output-control invariant)

---

### INV-009: Client IP must be parsed right-to-left through trusted proxies

- **CWE**: CWE-348 (Use of Less Trusted Source for IP Address)
- **First seen**: v1.19.0 (Round 5)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: Client IP taken from leftmost `X-Forwarded-For` entry. An attacker controls that header from the browser; rate limits, audit logs, and IP-based ACLs see the spoofed value.
- **Fix recipe**: Walk `X-Forwarded-For` right-to-left, skipping each entry that matches `TRUSTED_PROXIES`. Return the first untrusted hop. Fall back to direct peer IP if all hops are trusted.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'X-Forwarded-For|x_forwarded_for|XFF' core/`
  - L3: behavior tests (spoofed-leftmost, multi-proxy chain, all-trusted fallback)
- **Coverage by area**:
  - `core/http/request_id.py` (or equivalent IP helper): covered
  - `core/audit.py`: covered (uses the helper)
  - `core/http/throttle.py`: covered (uses the helper)
- **Instances**:
  - v1.19.0: `get_client_ip()` used `split(',')[0]`
- **Regression tests**: spoofed-leftmost test (named in Round 5 changelog)
- **Related**: INV-029 (trusted-proxies misconfig warning — operator-side counterpart)

---

### INV-010: Superuser role must be configurable, not hardcoded

- **CWE**: CWE-798 (Hard-coded Credentials) + CWE-269 (Improper Privilege Management)
- **First seen**: v1.20.0 (Round 6)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: A privileged role name is hardcoded as a string literal in auth decorators. Any session containing that string gets total access; the name cannot be renamed or disabled.
- **Fix recipe**: Read role name from config: `_superuser_role()` → `config.get('SUPERUSER_ROLE', 'admin')`. Allow `''` to disable bypass entirely.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n "'admin'" core/auth/`
  - L3: behavior test on `SUPERUSER_ROLE='' disables bypass`
- **Coverage by area**:
  - `core/auth/decorators.py`: covered (3 decorators: `require_role`, `require_any_role`, `require_permission`)
  - Other hardcoded role/permission literals: **NOT explicitly swept**
- **Instances**:
  - v1.20.0: `_superuser_role()` reads config
- **Regression tests**: existing ACL tests updated
- **Related**: none

---

### INV-011: Mail headers must reject CR/LF (header injection)

- **CWE**: CWE-93 (Improper Neutralization of CRLF Sequences)
- **First seen**: v1.21.0 (Round 7)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: User-supplied strings (subject, From, recipients) flow directly into MIME header fields without sanitizing CR/LF, enabling header injection (Bcc exfiltration, reply-to hijack).
- **Fix recipe**: `_reject_header_injection(value)` raises `ValueError` on any `\r` or `\n` in header-bound strings. Applied to subject, From, To, Cc, Bcc, Reply-To.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'add_header|MIMEText|MIMEMultipart' core/mail.py services/mail_*`
  - L3: behavior test per header
- **Coverage by area**:
  - `core/mail.py`: covered
  - `services/mail_resend.py`: covered (passes through, provider rejects on its side too — defense in depth)
- **Instances**:
  - v1.21.0: `_build_message()` rejected CR/LF in all header inputs
- **Regression tests**: CR/LF-in-mail tests (Round 7 suite)
- **Related**: INV-012 (log injection — same CRLF class)

---

### INV-012: User-controlled headers must be validated before adoption into logs

- **CWE**: CWE-117 (Improper Output Neutralization for Logs)
- **First seen**: v1.21.0 (Round 7)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: A request-supplied header (e.g. `X-Request-ID`) is adopted into the log record verbatim. An attacker injects CR/LF + crafted log lines to forge audit entries or break log parsers.
- **Fix recipe**: Validate against an allow-list pattern (`^[A-Za-z0-9_\-]{1,64}$`). On mismatch, drop and generate fresh UUID.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'request.headers.get' core/http/request_id.py core/audit.py core/logger.py`
  - L3: behavior test (`test_request_id_cr_lf_rejection`)
- **Coverage by area**:
  - `core/http/request_id.py`: covered
  - Other headers adopted into logs (User-Agent, custom): **NOT explicitly swept**
- **Instances**:
  - v1.21.0: X-Request-ID validation
- **Regression tests**: `test_request_id_cr_lf_rejection`
- **Related**: INV-011, INV-029

---

### INV-013: Archive extraction must guard against zip-slip

- **CWE**: CWE-22 (Path Traversal)
- **First seen**: v1.21.0 (Round 7)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: Archive (zip/tar) member paths are extracted without validating that the resolved destination stays within the target directory. A member named `../../etc/cron.d/x` writes outside the extraction root.
- **Fix recipe**: `_safe_extract_path(target_dir, member_name)` resolves the destination and refuses any path that does not start with the resolved target. Apply per member, never `extractall()` blind.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'extractall|extract\(' core/ docs/`
  - L3: behavior test (`test_framework_update_refuses_zip_slip_member`)
- **Coverage by area**:
  - `core/cli.py:framework_update`: covered
  - `docs/install.py`: covered
  - Any future archive extraction: must use `_safe_extract` pattern
- **Instances**:
  - v1.21.0: framework:update + installer
- **Regression tests**: `test_framework_update_refuses_zip_slip_member`
- **Related**: INV-024 (framework_update non-atomic staging — adjacent)

---

### INV-014: Upload size limits must be enforced during streaming, not after

- **CWE**: CWE-400 (Uncontrolled Resource Consumption)
- **First seen**: v1.21.0 (Round 7)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: File uploads are fully buffered into memory before size checks are enforced, so a single 10 GB upload exhausts worker memory before the check fires.
- **Fix recipe**: `_read_capped(stream, max_size)` reads in 64 KB chunks, aborts on excess. Spool to `SpooledTemporaryFile(8 MB)` (rolls to disk past threshold). Storage drivers accept file-like chunked iterators, never bytes.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'await .*\.read\(\)' core/http/upload.py services/storage_*`
  - L3: behavior tests
- **Coverage by area**:
  - `core/http/upload.py`: covered
  - `services/storage_s3.py`, `storage_gcs.py`: covered (streaming protocol)
  - Future storage drivers: contract enforced via protocol tests
- **Instances**:
  - v1.21.0: `save_upload` chunked read
  - v1.23.0: full driver protocol refactor (file-like, not bytes)
- **Regression tests**: `test_save_upload_passes_file_like_to_driver`, `test_save_upload_streaming_handles_payload_above_ram_threshold`
- **Related**: INV-017 (SVG XSS — adjacent upload hardening)

---

### INV-015: Docs and code must stay coherent (manual review on high-leverage files)

- **CWE**: Nori-specific (no clean CWE — "the class of bug ruff/mypy cannot catch")
- **First seen**: v1.15.4 (CORS+SecurityHeaders middleware order)
- **Status**: Active (recurring — each release surfaces some drift)
- **Severity (max instance)**: MED (the v1.15.4 instance caused CORS preflight responses to ship without security headers — actually HIGH-impact, but the class median is MED)
- **Bug class**: A comment, docstring, or docs page describes behavior X; the code does Y. Both compile cleanly. ruff, mypy, and high coverage pass. Only manual review surfaces it.
- **Fix recipe**: Before shipping a change to high-leverage files (list below), grep `docs/**/*.md` for matching snippets, read surrounding prose, verify code comment + code body match. Determine canonical side (sometimes the docs are right and the code is the bug).
- **Detector maturity**:
  - L1: yes (manual review + exploration agent prompt)
  - L2: pre-merge grep recipe on high-leverage files (below)
  - L3: **not feasible** — the 2026-05 audit found 4 mismatches at once; a regex CI check would go stale and false-positive. The cost-effective approach is per-PR review.
- **High-leverage files** (touching these requires docs+code review in the same change):
  - `rootsystem/application/asgi.py` (middleware order, lifespan)
  - `rootsystem/application/settings.py` (defaults that affect lifecycle/ownership)
  - `rootsystem/application/core/cli.py` (CLI commands described in `docs/cli.md`)
  - `rootsystem/application/core/auth/csrf.py`, `core/http/validation.py` (rule precedence)
  - `rootsystem/application/core/queue_worker.py`, `core/queue.py` (allow-list contract)
  - `_FRAMEWORK_DIRS` / `_FRAMEWORK_FILES` in `core/cli.py` (ownership in `docs/architecture.md`)
- **Coverage by area**: covered by per-PR discipline + per-release sweep
- **Instances**:
  - v1.15.4: CORS at `insert(1, ...)` while docs documented `insert(2, ...)`
  - 2026-05 audit: 4 mismatches (CSRF JSON exemption, body cap 10MB vs 1MiB, SECRET_KEY validation claim, exempt_paths type)
- **Regression tests**: `test_middleware_order_with_cors_keeps_security_headers_outside_cors` pins the specific v1.15.4 invariant; no general lint
- **Related**: every other INV (the docs side of every INV should match the code)

---

### INV-016: Session revocation must work end-to-end (active-user gate + version counter)

- **CWE**: CWE-613 (Insufficient Session Expiration) + CWE-287 (Improper Authentication)
- **First seen**: v1.31.0 (active-user gate) + v1.33.0 (version counter)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A user is deactivated or has a session revoked, but their cookie remains valid until `max_age` expires. Stolen sessions cannot be invalidated server-side.
- **Fix recipe**: Two complementary checks: (a) `load_permissions` queries `User.is_active` before populating permissions; returns `[]` if deactivated. (b) Per-user integer version counter in DB+cache; bumped by `invalidate_session()`; all auth decorators check `session_version` against live counter before role/permission logic. Cache writes use explicit TTL.
- **Detector maturity**:
  - L1: yes
  - L2: per-decorator audit on every change to `core/auth/decorators.py`
  - L3: behavior tests for all 4 session-aware decorators (`login_required`, `require_role`, `require_any_role`, `require_permission`) — completed in PR #28
- **Coverage by area**:
  - `core/auth/decorators.py`: covered
  - `core/auth/session_guard.py`: covered (circuit breaker + TTL)
  - User session storage (Starlette default vs custom): contract documented in `docs/authentication.md`
- **Instances**:
  - v1.31.0: `load_permissions` `is_active` gate
  - v1.33.0: per-user `session_version` counter
  - v1.33.1: explicit TTL on `session_guard` cache writes
- **Regression tests**: `test_load_permissions_refuses_inactive_user`, `test_login_required_denies_when_session_version_revoked`, `test_require_role_denies_when_session_version_revoked`, `test_require_any_role_denies_when_session_version_revoked`, `test_require_permission_denies_when_session_revoked`, `test_cache_writes_respect_configurable_ttl`, plus 18 more in `test_session_guard.py`
- **Related**: INV-007 (JWT revocation — same family of "auth must support fast invalidation")

---

### INV-017: SVG uploads must be content-scanned for active content

- **CWE**: CWE-79 (Stored XSS) + CWE-434 (Unrestricted Upload of File with Dangerous Type)
- **First seen**: v1.34.0
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: SVG files are accepted by the default upload allowlist and served inline (XML media type). SVG can contain `<script>`, `<foreignObject>`, `<iframe>`, and `on*` event handlers that execute in the host origin — stored XSS.
- **Fix recipe**: Two layers: (a) SVG removed from the default `allowed_types` allowlist (`_UNSAFE_BY_DEFAULT`); users must opt in explicitly. (b) When opted in, `_validate_svg_content` scans the first 256 KB and rejects `<script>`, `<foreignObject>`, `<iframe>`, `on*` attributes (case-insensitive).
- **Detector maturity**:
  - L1: yes
  - L2: review on every change to `_MIME_MAP` or `_validate_svg_content`
  - L3: 13 behavior tests
- **Coverage by area**:
  - `core/http/upload.py`: covered
  - User code that bypasses `save_upload` (raw `request.form()`): out of framework scope; documented
- **Instances**:
  - v1.34.0: SVG removed from default + content scan when opted in
- **Regression tests**: `test_default_allowed_types_excludes_svg`, `test_svg_content_rejects_script_tag`, `test_save_upload_default_rejects_svg_extension`, `test_save_upload_svg_xss_blocked_when_opted_in`
- **Related**: INV-014 (upload size limits — same family)

---

### INV-018: Numeric validation must reject NaN and Inf

- **CWE**: CWE-704 (Incorrect Type Conversion) + CWE-20 (Improper Input Validation)
- **First seen**: v1.22.0
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: `float('nan')` and `float('inf')` satisfy `>= min` and `<= max` checks (IEEE 754 comparison semantics return False for both sides). User submitting `amount=nan` bypasses any min/max range check.
- **Fix recipe**: Explicit rejection of NaN and Inf in both `min_value` and `max_value` rules. Standard test: `math.isnan(v) or math.isinf(v)`.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'min_value|max_value|float\(' core/http/validation.py`
  - L3: behavior tests
- **Coverage by area**:
  - `core/http/validation.py`: covered
- **Instances**:
  - v1.22.0: explicit NaN/Inf rejection in `min_value`/`max_value`
- **Regression tests**: `test_min_value_rejects_nan`, `test_max_value_rejects_nan`, `test_min_value_rejects_inf`, `test_max_value_rejects_neg_inf`
- **Related**: none

---

### INV-019: Dependency CVE gate must block ship

- **CWE**: CWE-1035 (OWASP A06:2021 — Vulnerable and Outdated Components)
- **First seen**: v1.11.0 (Python floor bump cleared 6 CVEs)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A dependency pinned to a version with known CVEs; fix sometimes requires raising the Python floor or breaking-version migration.
- **Fix recipe**: `pip-audit` runs in CI on every push and PR. Documented `--ignore-vuln` allow-list with per-entry justification (see `.github/workflows/audit.yml`).
- **Detector maturity**:
  - L1: no
  - L2: no
  - L3: `.github/workflows/audit.yml` — `pip-audit` blocks merge on any new CVE
- **Coverage by area**:
  - `requirements.txt` + `requirements.nori.txt` + `requirements-dev.txt`: covered
  - Transitive deps: covered (pip-audit walks transitively)
- **Instances**:
  - v1.11.0: Python 3.9 floor bump + dep updates (cleared CVE-2026-24486 arbitrary file write + 5 others)
- **Regression tests**: covered by CI gate (no pytest needed)
- **Related**: none

---

### INV-020: In-flight async background work must be tracked for graceful shutdown

- **CWE**: CWE-778 (Insufficient Logging) — for audit case; CWE-362 (Race / data loss) more broadly
- **First seen**: v1.24.0 (audit task loss)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: An `async def` operation is launched via `asyncio.create_task` but the returned Task reference is discarded. The event loop holds only a weak reference; the task can be garbage-collected mid-await, or dropped on SIGTERM/lifespan teardown. Symptoms: silent audit log gaps; silent dropped background jobs.
- **Fix recipe**: Module-level `set[asyncio.Task]`. Every `create_task` is added; `task.add_done_callback(_set.discard)` cleans up. `flush_pending(timeout=N)` registered with ASGI lifespan to await all pending before teardown.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'asyncio\.create_task|asyncio\.ensure_future' core/`
  - L3: behavior tests per site (audit, memory queue)
- **Coverage by area**:
  - `core/audit.py`: covered (audit task loss)
  - `core/queue.py:_memory_handler`: covered (memory queue task GC)
  - Other create_task sites: **NOT systematically swept**
- **Instances**:
  - v1.24.0: `core/audit.py` flush_pending on lifespan
  - v1.30.0: `_memory_tasks` set + add_done_callback in core/queue.py
- **Regression tests**: `test_audit_registers_pending_task_for_lifespan_flush`, `test_flush_pending_awaits_in_flight_audit_writes`, `test_memory_handler_holds_strong_reference_to_task`
- **Related**: INV-001 (cache TOCTOU — both are concurrency invariants)

---

### INV-021: httpx clients must be reused per service driver

- **CWE**: CWE-400 (Uncontrolled Resource Consumption — socket exhaustion + TLS handshake cost)
- **First seen**: v1.18.0 (Round 4)
- **Status**: Active
- **Severity (max instance)**: MED (performance-with-security-impact: fd exhaustion DoSes other requests)
- **Bug class**: A new `httpx.AsyncClient` is constructed per request (`async with httpx.AsyncClient() as c:`). Every constructor opens a fresh TCP+TLS handshake (~100-200ms over WAN), exhausts socket descriptors under load.
- **Fix recipe**: One module-level `_client: httpx.AsyncClient | None` per service driver. Lazy `_get_client()` initializes once and registers `shutdown()` with `core.lifecycle.register_shutdown(...)` so the ASGI lifespan closes the pool cleanly.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'httpx\.AsyncClient\(' services/`
  - L3: `.semgrep/nori-rules.yml::nori-service-httpx-per-call-asyncclient` (ERROR, since 2026-05). Restricted to `services/*`.
- **Coverage by area**:
  - `services/*`: all 6 drivers covered (mail_resend, storage_gcs, storage_s3, oauth_github, oauth_google, search_meilisearch)
  - Future drivers: L3 catches at PR time
- **Instances**:
  - v1.18.0: Round 4 finding + defensive sweep across all 6 drivers
- **Regression tests**: lifecycle registry tests in v1.27.0 (`test_run_shutdown_handlers_invokes_each_in_order`)
- **Related**: INV-002 (sync I/O hygiene — both are "service driver performance discipline")

---

### INV-022: Sync `validate()` must fail loud on async-only rules

- **CWE**: CWE-20 (Improper Input Validation — constraint unenforced)
- **First seen**: v1.16.0
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: Calling sync `validate()` with a rule that requires database I/O (e.g. `unique:table,column`) silently no-ops the rule. The constraint is unenforced; duplicate emails/usernames slip through to the DB unique-index error or worse.
- **Fix recipe**: Sync `validate()` raises `ValueError` listing offending async-rule fields with explicit direction: "call `validate_async()` instead".
- **Detector maturity**:
  - L1: yes
  - L2: review on every change to `core/http/validation.py:_check_rule`
  - L3: behavior tests
- **Coverage by area**:
  - `core/http/validation.py`: covered
- **Instances**:
  - v1.16.0: `unique` rule raises in sync `validate()`
- **Regression tests**: `test_unique_raises_in_sync_validate`, `test_validate_lists_all_async_violations`
- **Related**: none

---

### INV-023: `framework:update` must be atomic (stage-and-swap)

- **CWE**: CWE-367 (TOCTOU on framework install) + CWE-400 (availability loss on mid-update failure)
- **First seen**: v1.23.0
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: Update performs `rmtree(target) → copytree(new)` sequentially. A mid-copy failure (disk full, signal, network blip on remote source) leaves the framework directory empty, breaking the next import system-wide.
- **Fix recipe**: Stage-and-swap: copy to `<dir>.new`, then `os.replace(<dir>.new, <dir>)` atomically after all stages succeed. Keep `<dir>.old` until end for rollback.
- **Detector maturity**:
  - L1: yes
  - L2: review on every change to `core/cli.py:framework_update`
  - L3: behavior test
- **Coverage by area**:
  - `core/cli.py:framework_update`: covered
- **Instances**:
  - v1.23.0: stage-and-swap implementation
- **Regression tests**: `test_framework_update_rolls_back_when_staging_fails`
- **Related**: INV-013 (zip-slip — same framework_update path)

---

### INV-024: Redis multi-step operations must be wrapped in Lua

- **CWE**: CWE-362 (Race Condition — silent double-execution)
- **First seen**: v1.17.0 (Round 3) — delayed job promotion
- **Status**: Active
- **Severity (max instance)**: MED (silent double-execution: double charges, double notifications)
- **Bug class**: A "promotion" or "atomic shift" against Redis is implemented as multiple round-trips (`ZRANGEBYSCORE` → `LPUSH` → `ZREM`). Two concurrent workers both promote the same job before either removes it from the sorted set.
- **Fix recipe**: Single `EVAL` with a Lua script holding the entire critical section. Redis guarantees single-threaded Lua execution.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'redis_client\.[a-z]+\(.*\).*\n.*redis_client' core/` (look for sequential Redis ops)
  - L3: behavior test (lupa-backed for fakeredis)
- **Coverage by area**:
  - `core/queue_worker.py:_work_redis`: covered (single EVAL)
  - `core/cache.py:cache_atomic_update`: covered (WATCH/MULTI/EXEC retry; alternative to Lua for general RMW)
  - Other multi-step Redis sites: **NOT explicitly swept**
- **Instances**:
  - v1.17.0: Redis delayed-job promotion via Lua
- **Regression tests**: lupa-backed Redis tests (v1.18.0 batch)
- **Related**: INV-001 (TOCTOU cache — same concurrency family, different layer)

---

### INV-025: Installer must verify checksum of downloaded archive

- **CWE**: CWE-494 (Download of Code Without Integrity Check)
- **First seen**: v1.17.0 (Round 3)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: Installer downloads a release archive without verifying integrity, vulnerable to tag mutation, mirror compromise, or re-tag attacks.
- **Fix recipe**: `--checksum H` CLI flag accepts SHA-256; installer always prints computed SHA-256 of downloaded archive; aborts on mismatch.
- **Detector maturity**:
  - L1: yes
  - L2: review on every change to `docs/install.py`
  - L3: documented in `docs/installation.md`; no pytest (installer is one-shot)
- **Coverage by area**:
  - `docs/install.py`: covered
  - `core/cli.py:framework_update`: future opportunity — currently relies on GitHub TLS but does not verify
- **Instances**:
  - v1.17.0: `--checksum` flag added
- **Regression tests**: none (installer one-shot; manual end-to-end on release)
- **Related**: INV-013, INV-023

---

### INV-026: CLI subprocess scripts must call `configure(settings)` before importing user code

- **CWE**: Nori-specific
- **First seen**: v1.10.5 (routes_list fix)
- **Status**: Active
- **Severity (max instance)**: MED (broken command on launch; not exploit)
- **Bug class**: A CLI command spawns a Python subprocess (`python -c "<script>"` or `python -m asyncio` with PYTHONSTARTUP) that imports user `routes`/`modules`/`models`. Without `configure(settings)` first, any user module that touches `config.X` / `templates.env` / framework state at import time crashes with `RuntimeError: Nori config not initialised`.
- **Fix recipe**: Every subprocess script starts with:
  ```python
  import sys
  sys.path.insert(0, '.')
  import settings
  from core.conf import configure
  configure(settings)
  # ... then user imports
  ```
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'subprocess\.run.*python' core/cli.py` then inspect script body
  - L3: per-command behavior test (`test_routes_list_configures_settings_before_importing_routes`, `test_migrate_fresh_drop_subprocess_calls_configure`, `test_shell_pythonstartup_configures_and_imports_models_before_init`)
- **Coverage by area**:
  - `core/cli.py`: `routes_list`, `migrate_init`, `migrate_upgrade`, `migrate_fresh`, `db_seed`, `queue_work`, `shell` — all covered
  - aerich subprocesses (which don't run inline Python): use `env=_quiet_env()` to suppress warnings
- **Instances**:
  - v1.10.5: routes_list fix
  - v1.22.0: migrate:fresh drop subprocess
  - 2026-05 (PR #28): `nori shell` (also added `import models` + dropped `asyncio.get_event_loop()`)
- **Regression tests**: see L3 above
- **Related**: INV-027 (CWD-independent paths — adjacent CLI hygiene)

---

### INV-027: File and module path resolution must be CWD-independent

- **CWE**: Nori-specific (correctness; potential CWE-22 adjacent in some cases)
- **First seen**: AGENTS.md §7 — codified after several similar incidents
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: `pathlib.Path('something')` or `os.path.join('rootsystem', '...')` resolves relative to the caller's CWD. `nori.py` adds `rootsystem/application/` to `sys.path` but does NOT `chdir` into it. Invoking `python3 /abs/path/nori.py migrate:upgrade` from `/tmp` breaks with FileNotFoundError.
- **Fix recipe**: Anchor all paths to the module file:
  ```python
  pathlib.Path(__file__).resolve().parent.parent / 'something'
  ```
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n "Path\(['\"][a-z]" core/ services/` (literal-string Path arguments)
  - L3: `.semgrep/nori-rules.yml::nori-cli-cwd-relative-path` (ERROR, since 2026-05). Restricted to `core/cli.py`. Does NOT catch `os.path.join('literal', ...)`.
- **Coverage by area**:
  - `core/cli.py`: L3 active for `Path(...)`; `os.path.join` form still L1
  - `core/`, `services/` more broadly: L2 only
- **Instances**:
  - Multiple historical CLI fixes per AGENTS.md §7
  - 2026-05 audit flagged `_APP_DIR = os.path.join('rootsystem', 'application')` in `cli.py:20` as still CWD-relative — pending fix
- **Regression tests**: indirectly covered by per-command tests; no dedicated path-resolution test
- **Related**: INV-026

---

### INV-028: Repo state itself can be a bug (ship-time invariants)

- **CWE**: Nori-specific
- **First seen**: v1.10.3 (`.gitkeep` incident)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: Some bugs are not in code but in committed files (the v1.8.0 → v1.10.2 incident: leftover `.gitkeep` files silently broke `migrate:init` for two releases). Unit tests of the affected function passed because the test env didn't have the bad files.
- **Fix recipe**: When fixing "the repo shouldn't ship X", add a static repo-state assertion alongside the function fix.
- **Detector maturity**:
  - L1: no
  - L2: no
  - L3: repo-state pytest assertions (see `test_repo_does_not_ship_migrations_dir`)
- **Coverage by area**:
  - `rootsystem/application/migrations/` non-existence: L3 active
  - Other ship-time invariants (mkdocs nav valid, CLI commands documented, `.env` not committed): **NOT YET covered** — see audit roadmap
- **Instances**:
  - v1.10.3: `migrations/` dir not shipped
- **Regression tests**: `test_repo_does_not_ship_migrations_dir`
- **Related**: INV-015 (docs↔code coherence — adjacent)

---

### INV-029: New settings must default via `config.get(key, default)`

- **CWE**: Nori-specific (backwards-compatibility)
- **First seen**: codified after multiple add-setting commits
- **Status**: Active
- **Severity (max instance)**: LOW (breakage on upgrade for users who haven't set the new key)
- **Bug class**: Code accesses a new user-overridable setting via `config.SETTING` (attribute access). Existing projects that haven't added the key to `settings.py` crash on upgrade.
- **Fix recipe**: Read with `config.get('SETTING', default_value)`. Default must match the previous hardcoded behavior so existing projects keep working.
- **Detector maturity**:
  - L1: yes
  - L2: `rg -n 'config\.[A-Z_]+' core/` and compare against documented settings
  - L3: not feasible (false positives on settings that ARE always present)
- **Coverage by area**:
  - All new settings since v1.10.x: discipline maintained per AGENTS.md §7
- **Instances**:
  - LOGIN_URL, FORBIDDEN_URL, PERMISSIONS_TTL (multiple v1.x releases)
- **Regression tests**: per-feature tests assert the default kicks in when the setting is absent
- **Related**: none

---

## Roadmap — L1/L2 entries to graduate to L3

These are the highest-leverage Semgrep/test mechanizations remaining. Sorted by impact × frequency.

| Priority | INV | Current | Target | Why |
|----------|-----|---------|--------|-----|
| ~~HIGH~~ | ~~INV-002~~ | ~~L3 partial~~ | ✅ L3 full (open + time.sleep + requests + subprocess) | **Done 2026-05-26 — iter 3.** Crypto/hashing still L1/L2 (low FP value). |
| ~~HIGH~~ | ~~INV-001~~ | ~~L3 partial (services/* not swept)~~ | ✅ L3 full | **Done 2026-05-26 — iter 3.** `services/*` swept manually; zero usages. Rule already scans the path. |
| MED | INV-007 | L3 partial (subscript only, jti/sub/iss/aud/nbf) | L3 full | Add `cache_get` `_store` backend bypass detection |
| MED | INV-027 | L3 partial (Path() in cli.py only) | L3 full | Extend to `os.path.join` and broaden to `core/`, `services/` |
| MED | INV-020 | L1/L2 | L3 | Detect `asyncio.create_task` without `add_done_callback` |
| MED | INV-013 | L3 (per site) | L3 (rule) | Generalize zip-slip pattern detection rule |
| LOW | INV-019 (audit reflex) | L3 already (pip-audit) | — | Already complete |

## Roadmap — new ship-time lints (INV-028 family)

- Each `mkdocs.yml` nav entry maps to an existing `.md` file (regression for nav rot)
- Each `add_parser(...)` in `cli.py main()` has a corresponding entry in `docs/cli.md`
- `rootsystem/application/.env` is not committed
- `rootsystem/static/.gitkeep` content is exactly empty (catches accidental contents)

## Audit log

When you complete an audit pass, append here:

| Date | Scope | New INVs | Regressions of existing INVs | Notes |
|------|-------|----------|------------------------------|-------|
| 2026-05-25 | full sweep (code + docs + tests) | none (all 4 Criticals matched existing INVs: INV-004 docs side, INV-026 shell, INV-016 require_role/any_role test gap, INV-007 OAuth subscript propagation) | INV-015 (4 doc mismatches), INV-027 (cli.py:20 `_APP_DIR`) | Shipped Semgrep CI (PR #28) — 5 custom rules across INV-001, INV-002, INV-007, INV-021, INV-027 |
| 2026-05-26 | iter 3 graduation: INV-002 + INV-001 to L3 full | none | none | Added 3 new Semgrep rules: `nori-sync-time-sleep-in-async`, `nori-sync-requests-import-in-services`, `nori-sync-subprocess-in-async`. `services/*` swept manually for INV-001 partner calls — zero usages. Full repo scan: 8 rules × 71 files = 0 findings. Convergence metric: 0 new classes, 0 regressions — pure mechanization work. |
