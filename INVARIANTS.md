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
  - Still L1/L2: sync crypto/hashing (`hashlib.pbkdf2_hmac`, `bcrypt.hashpw`), image decoding, `urllib.request.urlopen`. Difficult to mechanize without false positives because these calls are legitimate in non-async contexts; rely on per-PR review. 2026-07-06 audit: the 3 new instances below (`spool.write()`, a streaming `hashlib.sha256()` loop, a Jinja `.render()` call) are also not matched by any of the 4 L3 rules above — same false-positive-risk rationale, still L1/L2.
- **Coverage by area**:
  - `services/storage_gcs.py`: swept Round 4 (RSA + cred load via to_thread)
  - `services/*` (open, time.sleep, requests import, subprocess in async): L3 since 2026-05-26
  - `core/*` (time.sleep, subprocess in async): L3 since 2026-05-26
  - `core/cli.py`: excluded from subprocess rule (sync entry script — subprocess.run is correct primitive)
  - `core/http/upload.py`: swept Round 3 (`asyncio.to_thread` for disk write) — **2026-07-06 audit found a second, unwrapped site**: see Instances (`_spool_body`)
  - `core/auth/security.py`: swept v1.22.0 (PBKDF2 async)
  - `core/tasks.py`: swept v1.27.0 (background dispatcher offloads sync)
  - `core/queue_worker.py`: swept v1.30.0 (execute_payload offloads sync)
  - `services/storage_s3.py`: **2026-07-06 audit found open** — see Instances (`_hash_and_size`)
  - `core/mail.py`: **2026-07-06 audit found open** — see Instances (`_render_template`)
  - Other crypto callsites (JWT signing, etc.): **NOT explicitly swept** at L3
- **Instances**:
  - v1.17.0: `core/http/upload.py` write_bytes on loop
  - v1.18.0: `services/storage_gcs.py` `_load_credentials` + `_build_jwt`
  - v1.22.0: `core/auth/security.py` PBKDF2 hash_password / verify_password
  - v1.27.0: `core/tasks.py` background() sync dispatch
  - v1.30.0: `core/queue_worker.py` execute_payload sync dispatch
  - 2026-07-06 audit: `core/http/upload.py` `_spool_body` — `spool.write()` (~401) rolls the multipart body to disk past the 8 MB RAM threshold (`_SPOOL_RAM_LIMIT`) unwrapped, inside an `async def`
  - 2026-07-06 audit: `services/storage_s3.py` `_hash_and_size` (~122-139, called ~208) — full-body `hashlib.sha256()` streaming loop runs unwrapped; sibling `services/storage_gcs.py` offloads its equivalent credential/JWT work via `asyncio.to_thread`
  - 2026-07-06 audit: `core/mail.py` `_render_template` (~82-85, called ~227) — sync Jinja2 `tmpl.render()` runs unwrapped on the event loop
- **Regression tests**: `test_hash_password_does_not_block_event_loop`, `test_background_sync_callable_does_not_block_event_loop`, `test_execute_payload_offloads_sync_callable_to_thread`; pending for the 3 2026-07-06 instances (see GitHub issues)
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
- **Fix recipe**: (a) **No content-type exemptions** for browser-readable methods. JSON clients must send `X-CSRF-Token` header. (b) **Check the header before reading the body** so streaming and multipart uploads stay streamed. (c) Refuse `multipart/form-data` without the header (do NOT buffer to extract token). (d) Cap urlencoded body buffering at `CSRF_FORM_MAX_BODY_SIZE` (default **10 MB**). The CSRF implementation is now a stateless **signed double-submit cookie** (v2.0.0) — request-shape rules (a)–(d) remain unchanged; see INV-030 for the cookie-signing invariant.
- **Detector maturity**:
  - L1: yes (manual review on `core/auth/csrf.py` changes)
  - L2: pre-merge checklist for csrf.py — verify header-first, multipart refusal, body cap intact, cookie = `{nonce}.{sig}` (not bare nonce)
  - L3: behavior tests + docs↔code mismatch caught by INV-015 manual checklist
- **Coverage by area**:
  - `core/auth/csrf.py`: full behavior coverage
- **Instances**:
  - v1.17.0: removed `application/json` short-circuit
  - v1.22.0: multipart-without-header refused, body cap configurable
  - v2.0.0: session-bound CSRF replaced by signed double-submit cookie; body cap aligned to 10 MB (INV-015 instance closed)
- **Regression tests**: `test_multipart_without_header_is_refused`, `test_multipart_with_header_passes_without_buffering`, `test_form_body_cap_is_configurable`, `test_form_body_cap_default_is_10mb`
- **Related**: INV-015 (docs↔code coherence — body cap aligned to 10 MB in v2.0.0), INV-030 (signed double-submit cookie — the CSRF wire-format invariant)

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
  - `services/oauth_*`: covered (callbacks also propagate HTTPStatusError with log — see PR #28) — **2026-07-06 audit found a regression**: see Instances (`oauth_github.py`)
  - Backend `_store` attribute access elsewhere: **NOT explicitly swept**
- **Instances**:
  - v1.16.0: `_is_blacklisted` read `backend._store` — only worked on MemoryBackend
  - v1.18.0: `revoke_token` raised `ValueError` on missing `jti` (RFC-optional)
  - 2026-07-06 audit: `services/oauth_github.py` (~148) `token_resp.json()['access_token']` — bare subscript crashes with `KeyError` on GitHub's documented 200-OK-with-error-body response shape (no HTTP 4xx status, so `raise_for_status_logged` never fires to catch it first). The existing test only mocks a 400 status, giving false confidence that this path is covered. Fix recipe (a) above applies unchanged.
- **Regression tests**: `test_revoke_token_blocks_verify_under_redis_backend`, plus the v1.18.0 missing-`jti` test; pending for the oauth_github 2026-07-06 instance — needs a 200-OK-with-error-body test case (see GitHub issues)
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
  - `core/ws.py`: **2026-07-06 audit found open** — see Instances (per-message size cap)
- **Instances**:
  - v1.21.0: `save_upload` chunked read
  - v1.23.0: full driver protocol refactor (file-like, not bytes)
  - 2026-07-06 audit: `core/ws.py` per-message size cap — `await websocket.receive_text()` (~87-90) fully buffers the frame before `len(data) > self.max_message_size` (~95) ever runs, so the buffer-then-check anti-pattern this INV was named for recurs on a different transport. The code comment (~33-36) frames `_MAX_MESSAGE_SIZE = 1 MiB` as the real ceiling ("generous... rejects the obvious DoS"), but the actual ceiling on what gets buffered before Nori's check runs is uvicorn's `ws_max_size` default of 16 MiB — a frame between 1 MiB and 16 MiB is fully accepted and buffered by uvicorn, handed to Nori as `data`, and only then rejected. Filed as a new instance of this INV rather than a new class: the pattern (fully buffer, then check size) is identical to the upload case, just on a different transport.
- **Regression tests**: `test_save_upload_passes_file_like_to_driver`, `test_save_upload_streaming_handles_payload_above_ram_threshold`; pending for the `core/ws.py` 2026-07-06 instance (see GitHub issues)
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
  - 2026-05-25 audit: 4 mismatches (CSRF JSON exemption, body cap 10MB vs 1MiB, SECRET_KEY validation claim, exempt_paths type)
  - 2026-05-26 git/release flow review: 4 more — `mkdocs.yml` declared `provider: mike` with mike never installed anywhere; `docs/deployment.md` "Documentation site" section described a VPS+rsync+Apache+Certbot pipeline while the actual deploy is Firebase Hosting + GitHub Actions; `docs/code_quality.md:129` linked to `cli.md#framework-check-config` while the real slug is `#frameworkcheck-config`; `docs/dependencies.md:111` linked to `observability.md#upgrading-an-existing-site` which never existed.
  - 2026-07-06 full-spectrum audit — MED-ish (doc-only) regressions: CSP report-only default (`core/http/security_headers.py`) is documented in `docs/security.md` but not cross-referenced from `docs/middleware.md` or `docs/architecture.md`, where a reader auditing middleware defaults would also look for it; `docs/logging.md` (~92-98) and `docs/deployment.md` (~401) document three phantom loggers — `nori.throttle`, `nori.upload`, `nori.cache` — that no module actually creates (`get_logger()` prefixes with `nori.`, but no callsite passes `'throttle'`, `'upload'`, or `'cache'`); `docs/dependencies.md` is stale on two axes — the `cryptography>=42.0` example (~39, ~142) should read `>=47.0.0` per `requirements-dev.txt`, and it never mentions `tomlkit` even though `requirements.nori.txt` now declares it for aerich; `docs/code_quality.md`'s per-module mypy strict example (~337-340) lists 3 modules while `pyproject.toml`'s actual `[[tool.mypy.overrides]]` list (~135-141) has 6 (`core.auth.csrf`, `core.auth.jwt`, `core.auth.oauth` are undocumented).
  - 2026-07-06 full-spectrum audit — LOW-severity (doc-only) regressions found in the same pass: `docs/code_quality.md` states the coverage floor is 82% without noting the actual baseline is ~86% (the floor number is correct, the "current" framing reads as if 82 were current); `docs/cli.md`'s `make:model` example shows `table = 'products'` (plural) while the generator (`core/cli.py` ~182) emits `table = '{name.lower()}'` (singular); `CLAUDE.md` §5 "Validation Rules" list is missing `password_strength` even though it's a fully implemented rule (`core/http/validation.py`); `docs/code_quality.md`'s Dependabot excerpt (~419) lists `hypothesis` in the `dev-tooling` group and `mypy` (no wildcard), while the real `.github/dependabot.yml` (~26-33) has no `hypothesis` entry and uses `mypy*`; `docs/code_quality.md`'s SBOM excerpt (~456-460, ~471-473) is stale against `.github/workflows/sbom.yml` (venv name, install location of `cyclonedx-bom`, invocation form, and output filename all differ); `docs/authentication.md`'s login example (line 51) calls `Security.verify_password(...)` without `await` — since `verify_password` is `async def`, `not <coroutine>` is always `False`, so that exact snippet never rejects a wrong password.
- **Regression tests**: `test_middleware_order_with_cors_keeps_security_headers_outside_cors` pins the specific v1.15.4 invariant. `mkdocs build --strict` in CI (since 2026-05-26) catches the WARNING-level subset (unknown nav entries, theme overrides). Dead anchors remain at INFO level — caught only by manual sweep until a separate link-checker is added. The 2026-07-06 instances above are all doc-only fixes pending (see GitHub issues) — this INV's L3-infeasibility conclusion (per Detector maturity) holds; they were only caught by the per-PR/per-release manual sweep.
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
- **Related**: INV-007 (JWT revocation — same family of "auth must support fast invalidation"), INV-030 (CSRF cookie statelessness — the deliberate CSRF ⟂ auth boundary)

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
  - `core/cli.py:framework_update`: future opportunity — currently relies on GitHub TLS but does not verify (**re-confirmed still open 2026-07-06** — the `framework:update` subparser still has no `--checksum` flag)
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
  - `core/_patches.py`: **2026-07-06 audit found open** — see Instances (`_APP_DIR`)
  - `core/`, `services/` more broadly: L2 only
- **Instances**:
  - Multiple historical CLI fixes per AGENTS.md §7
  - 2026-05 audit flagged `_APP_DIR` and `_BACKUP_DIR` in `cli.py` as CWD-relative `os.path.join('rootsystem', ...)` literals — **both fixed 2026-06-11**, anchored to `__file__` (`_APP_DIR = str(pathlib.Path(__file__).resolve().parent.parent)`; `_BACKUP_DIR` derived from it)
  - `_REQUIREMENTS_NORI_FILE = 'requirements.nori.txt'` stays intentionally project-root-relative (lives next to `nori.py`); revisit only if a non-root-CWD failure surfaces
  - 2026-07-06 audit: `core/_patches.py` (~24-26) has its own `_APP_DIR = os.path.join('rootsystem', 'application')` — a separate CWD-relative constant from the one fixed in `cli.py` 2026-06-11 (same name, different variable, never anchored). `framework_update()` invokes `_patches.apply()` in-process after the framework directories are replaced on disk; on a wrong-CWD invocation, `_ASGI_FILE` (derived from `_APP_DIR`) resolves to a nonexistent path, and each patcher's `if not os.path.exists(...): return False` guard makes the patch silently no-op instead of failing loud. This is exactly the gap the roadmap entry below ("extend to `os.path.join`, broaden to `core/`, `services/`") predicted.
- **Regression tests**: `test_app_dir_is_absolute_and_cwd_independent`, `test_backup_dir_is_absolute_and_cwd_independent` (chdir to a temp dir; assert the constant stays absolute and unchanged) — dedicated path-resolution coverage as of 2026-06-11; pending for the `core/_patches.py` 2026-07-06 instance (see GitHub issues)
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

### INV-030: CSRF cookie must be a signed structure; Set-Cookie must never be cached

- **CWE**: CWE-352 (CSRF)
- **First seen**: v2.0.0
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class (two coupled forms)**:
  1. *Unsigned double-submit*: a scheme where the submitted token equals (or is trivially derivable from) the cookie value with **no internal signature**. An attacker who can WRITE a cookie on the target domain (subdomain XSS, MITM on a sibling host, cookie-tossing) sets cookie=X and field=X and bypasses CSRF entirely.
  2. *Cached `Set-Cookie`*: caching the CSRF `Set-Cookie` header (e.g. via `cache_response`) shares one cookie value across every visitor for the cache TTL. An attacker harvests the shared value and a valid (replayable, even if masked) token from the cached page and forges a cross-site request that every co-visitor's auto-sent shared cookie matches → site-wide CSRF bypass for the full TTL.
- **Fix recipe**:
  - The cookie value MUST be the **signed structure** `{nonce}.{sig}` where `nonce = secrets.token_hex(32)` and `sig = HMAC-SHA256(SECRET_KEY, nonce)` hexdigest. The submitted value is the cookie value, accepted **raw or BREACH-masked** (server unmasks then compares). Validation is two constant-time checks: (1) recompute the sig over the cookie's nonce and `compare_digest` → reject forged cookies; (2) `compare_digest` the (unmasked) submission to the cookie value. A bare-nonce (unsigned) cookie MUST be rejected at check (1). `SECRET_KEY` is read via `core.conf.config`.
  - **`Set-Cookie` MUST be per visitor and MUST NEVER be cached.** `cache_response` MUST cache only body/status/media_type — it does today (`core/cache.py` caches `{'body_b64', 'status_code', 'media_type'}` only). This property is **load-bearing** for CSRF correctness; protect it with a regression test (`test_cache_response_never_emits_cached_set_cookie`). The `CsrfMiddleware` send-wrapper sets the CSRF `Set-Cookie` on the **live** response only, never via the cache value.
- **Boundary (CSRF ⟂ auth)**: The CSRF cookie is stateless and cannot be server-invalidated. A user with a revoked session (INV-016) still holds a valid CSRF cookie — this is acceptable because the auth decorators (`login_required`, `require_role`, `require_any_role`, `require_permission`) reject the request at the authorization layer before any handler runs. CSRF proves origin, not identity. Do NOT file "CSRF cookie outlives session revocation" as a finding.
- **Boundary (CSRF ⟂ XSS)**: An XSS-capable attacker reads the live cookie and the DOM, defeating **any** CSRF wire format. This is out of scope for CSRF; mitigate XSS via CSP and escaping. Do NOT use read-leak/XSS scenarios to argue a CSRF token shape.
- **Detector maturity**:
  - L1: yes (manual review on `core/auth/csrf.py` cookie structure + `core/cache.py` header caching)
  - L2: pre-merge checklist — cookie = `{nonce}.{sig}`, sig verified before match, unsigned cookie rejected, masking present, `cache_response` caches no headers
  - L3: behavior tests (`test_validate_rejects_signature_invalid_cookie`, `test_validate_rejects_unsigned_naive_double_submit`, `test_masked_token_differs_per_render`, `test_cache_response_never_emits_cached_set_cookie`, `test_forged_cookie_writer_attack_fails`)
- **Coverage by area**:
  - `core/auth/csrf.py`: full behavior coverage (cookie structure + dual-accept validation)
  - `core/cache.py`: regression pin that `Set-Cookie` is never cached
- **Instances**:
  - v2.0.0: signed double-submit cookie replaces session-bound synchronizer token; `Set-Cookie` confirmed uncached and pinned with regression test
- **Regression tests**: `test_validate_accepts_raw_cookie_value`, `test_validate_accepts_masked_cookie_value`, `test_validate_rejects_signature_invalid_cookie`, `test_validate_rejects_unsigned_naive_double_submit`, `test_cache_response_never_emits_cached_set_cookie`, `test_forged_cookie_writer_attack_fails`
- **Related**: INV-004 (CSRF request-shape rejection), INV-016 (session revocation — the auth-layer counterpart to this cookie's statelessness), INV-029 (CSRF_COOKIE_* defaults via config.get)

---

### INV-031: ORM structural-invariant mutation must be atomic (check-then-write race)

- **CWE**: CWE-362 (Race Condition) + CWE-835 (Loop with Unreachable Exit Condition — the non-terminating-query consequence)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: An ORM method reads current state, validates a structural invariant (e.g. "not a cycle", "not a duplicate"), then writes — with no transaction or row lock spanning the check and the write. Concurrent callers each observe a pre-write state that individually passes validation, so their interleaved writes jointly violate the invariant the check existed to enforce.
- **Fix recipe**: Wrap the check and the write in `in_transaction()` with `select_for_update()` on the row(s) being validated, so a concurrent mutator blocks until the first transaction commits or rolls back; as defense in depth, bound any recursive traversal that assumes the invariant holds (visited-set or depth cap) so a violation degrades to a wrong answer instead of a hang.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/mixins/tree.py`: swept 2026-07-06 — found open (`move_to`, `ancestors`/`descendants`)
  - Other ORM mixins with structural invariants (if any are added): **NOT swept**
- **Instances**:
  - 2026-07-06 audit: `core/mixins/tree.py` `move_to()` (~184-200) checks that `new_parent_id` is not in the current `descendant_ids` set, then `setattr` + `save(update_fields=...)` with no `atomic()`/`select_for_update` around the span — two concurrent `move_to()` calls each pass the check against the pre-move tree and jointly form a parent cycle (reproduced via `asyncio.gather` on first attempt). Downstream, `ancestors()` (~90-132) and `descendants()` (~134-164) build `WITH RECURSIVE ... UNION ALL` queries with no visited-set or depth cap, so once a cycle exists the recursive CTE never terminates (observed hang >4s) — a DB-level DoS stacked on top of the corrupted tree.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-001 (cache read-modify-write race — same TOCTOU family, different layer: cache value vs. ORM structural invariant)

---

### INV-032: Serializers must not emit unfetched ORM relations

- **CWE**: Nori-specific (correctness; breaks the most common serialization path)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A `to_dict()`-style serializer iterates the model's full declared field set instead of its actual DB columns, so any unfetched relation on the instance yields a live `QuerySet`/`ReverseRelation`/related-model object — a value that is not JSON-serializable and was never opted into by the caller.
- **Fix recipe**: Iterate `self._meta.db_fields` (or explicitly skip `self._meta.fetch_fields`) instead of `_meta.fields_map`, so only actual column values are serialized; relations become opt-in via an explicit include mechanism, never emitted implicitly.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/mixins/model.py`: swept 2026-07-06 — found open (`to_dict`)
  - Other serialization paths (`core/collection.py` `to_list`, see INV-008): not re-swept for this specific failure mode
- **Instances**:
  - 2026-07-06 audit: `core/mixins/model.py` `to_dict()` (~70-78) iterates `self._meta.fields_map` instead of `_meta.db_fields`; a plain `.get()` followed by `JSONResponse(model.to_dict())` raises `TypeError: Object of type QuerySet is not JSON serializable` for any model with a foreign key. `prefetch_related` does not fix it — the value becomes a raw model instance instead, still not serializable. The bare `except Exception` around the field access (~77-78) never fires here because `getattr` on an unfetched relation returns an object rather than raising.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-008 (`protected_fields` must be respected — same serializer, adjacent failure mode)

---

### INV-033: A global request-body size ceiling must exist

- **CWE**: CWE-400 (Uncontrolled Resource Consumption)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: Size caps applied only to specific parsers (file upload, CSRF form-body extraction) leave the general-purpose `request.json()` / `request.form()` entry points unbounded, so any handler that reads the body directly is an unauthenticated memory-exhaustion DoS.
- **Fix recipe**: Add a `MaxBodySizeMiddleware` early in the ASGI stack that rejects on an oversized `Content-Length` and enforces a running cap while draining `receive()`, independent of what any downstream parser does; default it via `config.get('MAX_BODY_SIZE', default)` per INV-029.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/auth/csrf.py`: header-token path swept 2026-07-06 — found open (passes the body through untouched)
  - ASGI middleware stack: no global body-size middleware exists
- **Instances**:
  - 2026-07-06 audit: no `MAX_BODY_SIZE` middleware or setting exists anywhere in `core/`. `core/auth/csrf.py` (~392-398) takes the header-token path whenever `X-CSRF-Token` is present and passes the body through completely untouched, and every JSON request must use that path (there is no form-encoded token to extract from JSON) — so an anonymous client, which can self-serve the non-HttpOnly CSRF cookie via any GET, POSTs a multi-GB JSON body and `request.json()` buffers it unbounded. No uvicorn/gunicorn default cap or documented nginx cap exists in the shipped deploy path either.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-014 (upload streaming cap — same class, different entry point), INV-004 (CSRF body cap — the form-encoded sibling of this gap), INV-029 (settings-default contract for the new `MAX_BODY_SIZE` key)

---

### INV-034: Rate-limit keys must use the route template, not the literal path

- **CWE**: CWE-770 (Allocation of Resources Without Limits or Throttling) + CWE-799 (Improper Control of Interaction Frequency)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A throttle bucket keyed on the literal request path gives every distinct path-parameter value its own independent bucket, so a client bypasses the intended per-endpoint limit simply by enumerating the parameter; if the backing store has no key-count ceiling, that same enumeration also grows it unbounded.
- **Fix recipe**: Key the bucket on the matched route pattern (e.g. `request.scope['route'].path_format`), never the literal path; give any in-memory throttle store a `max_keys`/LRU eviction ceiling, mirroring the pattern already used by the cache backend.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/http/throttle.py`: swept 2026-07-06 — found open (key construction)
  - `core/http/throttle_backends.py`: swept 2026-07-06 — found open (`MemoryBackend` has no key ceiling)
- **Instances**:
  - 2026-07-06 audit: `core/http/throttle.py` (~51) builds the key as `f'{ip}:{request.url.path}'`; reproduced 500/500 requests allowed against a configured 5-per-60s limit by varying a path parameter. `core/http/throttle_backends.py` `MemoryBackend` (~76-83) has no `max_keys`/LRU cap, unlike `MemoryCacheBackend` (`core/cache.py` ~138-141, default cap 10,000) — the same enumeration that defeats the limit also grows the backing dict without bound.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-001 (cache RMW atomicity — `MemoryCacheBackend`'s `max_keys` is the pattern to mirror), INV-009 (client-IP parsing — the other half of the throttle key)

---

### INV-035: Cache backends must have identical value semantics

- **CWE**: Nori-specific (portability/correctness)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: Pluggable cache backends that (de)serialize cached values differently make application code silently backend-dependent — logic tested against one backend changes shape, or breaks outright, when deployed against another.
- **Fix recipe**: Route the in-memory backend's values through the same serialize/deserialize step the Redis backend uses (or assert at the API boundary that only JSON-safe values are accepted), so both backends round-trip identically regardless of which one is configured.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/cache.py`: swept 2026-07-06 — found open (`MemoryCacheBackend` vs `RedisCacheBackend` divergence)
- **Instances**:
  - 2026-07-06 audit: `core/cache.py` — `MemoryCacheBackend` stores live object references (a cached `tuple`/`datetime`/`Decimal`/`UUID` round-trips exactly, but a later mutation of the original object aliases the cached entry), while `RedisCacheBackend` serializes via `json.dumps`/`json.loads` (~297, ~303) (a `tuple` comes back a `list`; `datetime`/`Decimal`/`UUID` come back `str`; a raw `set()` raises `TypeError`). Code written and tested against `CACHE_BACKEND=memory` silently changes shape — or breaks — under `CACHE_BACKEND=redis`. `docs/caching.md` documents only the `set()` `TypeError` case, not the tuple-to-list shape change or the memory-aliasing hazard.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-015 (docs↔code coherence — the doc gap on this same divergence)

---

### INV-036: Declarative type coercion must special-case bool

- **CWE**: CWE-704 (Incorrect Type Conversion)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: Coercing a string request parameter to a `bool`-annotated type via the type's own constructor (`bool(s)`) inverts almost every falsy-looking input, because in Python only the empty string is falsy for `bool(str)` — `bool('false')`, `bool('0')`, and `bool('no')` are all `True`.
- **Fix recipe**: Special-case `bool` before the generic `param.annotation(val)` constructor call — accept a fixed truthy set (e.g. `{'true','1','yes','on'}`, case-insensitive) and treat everything else as `False`; log a warning when a required parameter with no default cannot be resolved instead of silently injecting `None`.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/http/inject.py`: swept 2026-07-06 — found open (`_SAFE_COERCE_TYPES` bool handling)
- **Instances**:
  - 2026-07-06 audit: `core/http/inject.py` (~14, 74-91) — `_SAFE_COERCE_TYPES` includes `bool` and coerces path/query params via `param.annotation(val)`, so `?active=false`, `?active=0`, and `?active=no` all become `True` (reproduced through the real `@inject()` decorator). Secondary instance in the same fix scope: when a required parameter (no default, not resolved from path/query/form) can't be resolved, it is silently set to `None` (~79, ~90) instead of logging or raising — a caller relying on the annotation being non-optional gets a silent `None` instead of a clear error.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-018 (numeric validation footguns — same family of "declarative input handling has an untested corner")

---

### INV-037: Cache-population races must be coalesced (thundering herd on TTL expiry)

- **CWE**: CWE-400 (Uncontrolled Resource Consumption — thundering herd / cache stampede)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: MED
- **Bug class**: A cache-aside read path (`cache_get` miss → recompute → `cache_set`) has no single-flight/coalescing guard, so every request that arrives while the key is missing or mid-recompute independently repeats the same expensive work. This is distinct from INV-001 (an RMW that corrupts a value derived from the read): here each concurrent writer computes and stores the same correct value, so the result is not wrong — the hazard is redundant work, not corruption — but a hot key's TTL expiry can still trigger N simultaneous executions of the wrapped handler, which is its own resource-exhaustion / latency-spike risk.
- **Fix recipe**: Add a per-key single-flight guard (an in-process/distributed lock keyed on `cache_key`, or a short-TTL "recompute in progress" sentinel) around the miss path, so only one caller recomputes while concurrent callers wait for the result or briefly serve the stale value (stale-while-revalidate).
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/cache.py` `cache_response`: swept 2026-07-06 — found open
  - Other cache-aside call sites (any hand-rolled `cache_get`/`cache_set` pair outside `cache_response`): not swept for this specific failure mode
- **Instances**:
  - 2026-07-06 audit: `core/cache.py` `cache_response` decorator (~518-578) — the miss path (~541-576: `cache_get` → `func()` → `cache_set`) has no lock or in-flight marker between the read and the write; concurrent requests arriving during the same TTL-expiry window each independently execute the full wrapped handler.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-001 (cache RMW atomicity — same file, adjacent but distinct concurrency hazard: correctness-breaking RMW vs. redundant-work stampede)

---

### INV-038: Public collection APIs must resolve element fields consistently for dicts and objects

- **CWE**: Nori-specific (correctness / silent API footgun)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A collection/data-structure helper that accepts both mapping (`dict`) and object elements but resolves a field via `getattr(item, key, ...)`-first (or with no `dict` branch at all) silently mishandles `dict` elements: `getattr` returns a bound method when `key` collides with a `dict` method name (`items`, `keys`, `get`, ...), and a missing `dict` branch degrades ordering/grouping/dedup to a no-op or a single `None` bucket instead of raising. The API looks like it supports dicts but produces wrong results with no error.
- **Fix recipe**: Route every element-field access through a single `dict`-first accessor (check `isinstance(item, Mapping)` before `getattr`), reusing the one correct helper rather than re-implementing access per method.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `core/collection.py`: swept 2026-07-06 — found open (`pluck`/`where`/`sort_by`/`group_by`/`unique`/`to_dict`)
- **Instances**:
  - 2026-07-06 audit: `core/collection.py` — `_get_field()` resolves `dict`-first correctly but is used only by `sum`/`avg`/`min`/`max`; `pluck`/`where` use `getattr(item, key, ...)`-first (returns a bound method on a key like `'items'`); `sort_by`/`group_by`/`unique` have no `dict` branch at all (reproduced on `[{'price': ...}]`: `sort_by` silently no-ops, `group_by` collapses every element under a `None` key, `unique` collapses to one survivor); `to_dict(key)` hard-crashes with `AttributeError` (its `getattr` has no default). The class docstring and `pluck`'s doctest promise `dict` support.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-032 (serializer relation-leak — sibling `to_dict` correctness), INV-008 (protected_fields serialization)

---

### INV-039: Driver URL path segments must be validated or encoded before interpolation into outbound requests

- **CWE**: CWE-22 (Improper Limitation of a Pathname — path traversal into an outbound request URL)
- **First seen**: v2.1.0 (2026-07-06 audit)
- **Status**: Active
- **Severity (max instance)**: HIGH
- **Bug class**: A service driver that interpolates caller-supplied identifiers (index name, document id, object key) directly into an outbound HTTP client's URL **path** — with no allow-list validation or percent-encoding — lets `../` segments escape the intended resource scope and reach other endpoints of the backend, authenticated with the app's own API credentials. httpx collapses dot-segments before the request goes on the wire, so the traversal is real, not cosmetic. Distinct from INV-006, which escapes user input inside a backend query/filter **DSL string**: this is the URL path structure of the request itself.
- **Fix recipe**: Validate path-segment inputs against a strict allow-list (e.g. `^[A-Za-z0-9_-]+$`) at the public API boundary (`core/search.py`), and/or percent-encode each segment with `urllib.parse.quote(safe='')` in the driver before interpolation.
- **Detector maturity**:
  - L1: yes
  - L2: absent
  - L3: absent (fix pending)
- **Coverage by area**:
  - `services/search_meilisearch.py`: swept 2026-07-06 — found open (`index`/`doc_id` path interpolation)
  - `core/search.py`: swept 2026-07-06 — found open (public API passes `index`/`doc_id` through unvalidated)
  - Storage drivers (`services/storage_s3.py`, `storage_gcs.py`) build request paths from object keys similarly — not yet swept for this specific class
- **Instances**:
  - 2026-07-06 audit: `services/search_meilisearch.py` (~212, 245, 269) interpolate `index`/`doc_id` into the REST URL path (`f'{base}/indexes/{index}/documents/{doc_id}'`) with no validation; `core/search.py` applies none either. Wire-captured: `DELETE .../documents/../../../keys/<x>` is sent as `DELETE /keys/<x>` with the `Authorization: Bearer {MEILISEARCH_API_KEY}` master key attached — reaching Meilisearch's key-management endpoints. Reachability requires the app to pass request-controlled input as `doc_id`/`index` (the documented pattern uses `model.id`); the driver already validates filter-dict keys via `_SAFE_KEY` but not path segments — an inconsistency indicating accidental omission. Severity HIGH (not CRITICAL) because no shipped Nori code wires request input into these calls; it is a framework defense-in-depth gap the app can trip.
- **Regression tests**: pending — fix tracked in audit 2026-07-06 (see GitHub issues)
- **Related**: INV-006 (search filter DSL value escaping — same driver, different injection surface)

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
| 2026-06-11 | Audit Highs closure (from the 2026-05-25 cycle) | none | INV-027 (`_APP_DIR` + sibling `_BACKUP_DIR` CWD-relative literals in `cli.py`), INV-015 (`deployment.md` SECRET_KEY claim vs code — added the `change-me-in-production` placeholder check, corrected the doc) | 0 new bug classes — every fix was an instance of a catalogued class in previously-unswept code. Also hardened: HSTS no longer emitted in DEBUG (security-default scope creep; no existing INV — candidate class if it recurs). CSRF body-cap (INV-015) closed earlier in v2.0.0. Convergence holds. |
| 2026-05-26 | iter 3 graduation: INV-002 + INV-001 to L3 full | none | none | Added 3 new Semgrep rules: `nori-sync-time-sleep-in-async`, `nori-sync-requests-import-in-services`, `nori-sync-subprocess-in-async`. `services/*` swept manually for INV-001 partner calls — zero usages. Full repo scan: 8 rules × 71 files = 0 findings. Convergence metric: 0 new classes, 0 regressions — pure mechanization work. |
| 2026-05-26 | git/release/docs flow review | none | INV-015 (4 new instances: mike fiction in `mkdocs.yml`, VPS+rsync fiction in `docs/deployment.md`, 2 dead anchors in code_quality.md + dependencies.md) | Cleanup PR: pinned `mkdocs-material>=9.7.6` in deploy workflow, added `--strict` to `mkdocs build`, removed unused `extra.version: mike` stanza, rewrote `docs/deployment.md` Documentation site section to describe the actual Firebase + GH Actions pipeline, fixed both dead anchors, added `[Unreleased]` section to CHANGELOG. Convergence metric: 0 new classes, 4 INV-015 regressions caught manually — confirms that L3 for INV-015 remains infeasible (would have needed a docs-vs-real-infra check that no static tool can do). |
| 2026-06-11 | csrf-double-submit v2.0.0 docs slice | INV-030 (signed cookie + Set-Cookie never cached) | INV-004 (body cap updated to 10 MB, signed-cookie context added), INV-016 (added cross-reference to INV-030 per CSRF ⟂ auth boundary) | CSRF rewrite: stateless signed double-submit cookie replaces session-bound synchronizer token. INV-004 fix recipe updated (10 MB body cap, signed double-submit context). INV-016 "Related" gains INV-030 back-reference. New INV-030 covers both unsigned-cookie and cached-Set-Cookie bypass forms with L3 regression tests. |
| 2026-07-06 | full-spectrum audit (code + docs + tests), post-v2.1.0 — 6 lenses + 2 adversarial verifiers | INV-031 (ORM structural-invariant TOCTOU), INV-032 (serializer relation-leak), INV-033 (missing global body cap), INV-034 (throttle key granularity), INV-035 (cache backend value-semantics parity), INV-036 (declarative bool coercion), INV-037 (cache-population stampede), INV-038 (collection dict/object field-access footgun), INV-039 (driver URL path-segment injection) | INV-002 (3 new sync-on-loop sites: upload spool, storage_s3 hash, mail render), INV-007 (oauth_github 200-OK-with-error-body KeyError), INV-014 (WebSocket per-message cap buffers before checking — filed as a new instance of this class rather than a new INV), INV-015 (CSP report-only cross-doc gap, 3 phantom loggers, stale dependencies.md, mypy strict-list undercount, plus 6 lower-severity doc mismatches), INV-025 (re-confirmed open — `framework:update` still has no `--checksum`), INV-027 (`core/_patches.py` separate CWD-relative `_APP_DIR`) | Convergence: 9 genuinely new classes (INV-031..039) vs 6 existing INVs regressed/reconfirmed across ~17 individual unswept-site instances — high new-class ratio holds (older classes are mostly mechanized/L3, so the fresh crop skews new). Cross-cutting heuristic surfaced by this audit, worth watching for in future sweeps: "Nori hardens the code path it wrote but the general-purpose entry point one layer up/sideways is unguarded" (uploads capped but not `request.json()`; cache RMW atomic per INV-001 but tree mutation per INV-031 is not; WS size comment claims 1 MiB but the real ceiling is uvicorn's 16 MiB). One false positive caught by adversarial verify and dropped: validation `_check_unique`'s `$1`/`$2` placeholders are fine as-is — SQLite's grammar natively supports `$NNN` markers; the "broken on SQLite" claim from one lens tested raw `sqlite3`, not Tortoise's backend. All fixes tracked in GitHub issues #42–#47 (pending): #42 public-API correctness (INV-032/036/038), #43 availability/DoS (INV-002/033/034/037), #44 tree TOCTOU (INV-031), #45 security hardening (INV-007/025/027/035/039), #46 docs coherence (INV-015), #47 test-quality gaps (INV-004/011/017). |
