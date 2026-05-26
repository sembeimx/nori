# Semgrep — Nori custom rules

Versioned catalogue of Nori-specific invariants that are detectable statically.
Each rule in `nori-rules.yml` corresponds to a **class of bug** already found
in at least one previous audit.

The goal is that no class mechanised here ever reappears as an audit finding:
if it does, it is a regression, and CI should catch it on the PR — not on
the next manual sweep.

## Public rulesets enabled in CI

Configured in `.github/workflows/semgrep.yml`:

| Ruleset | Why | Severity gate |
|---------|-----|---------------|
| `p/python` | General language coverage (asyncio, pickle, deserialisation) | ERROR breaks CI |
| `p/security-audit` | Common security baseline (eval, exec, shell subprocess) | ERROR breaks CI |
| `p/owasp-top-ten` | OWASP categories — complements ruff bandit with cross-line analysis | ERROR breaks CI |

`p/cwe-top-25` is omitted due to high overlap with `p/security-audit`. Re-evaluate
at each audit whether any unique rules are worth including.

## Adding a new rule

1. Identify the **class** of bug (not the instance). A custom rule is only
   justified if you expect the pattern to recur in the future.
2. Look up the matching CWE at https://cwe.mitre.org/data/definitions/.
   If none applies, the rule is probably framework-specific correctness —
   that is fine, document why.
3. Write the rule in `nori-rules.yml` following the template:

   ```yaml
   - id: nori-<kebab-case-descriptor>
     message: |
       <what was wrong>. <why it matters>. <how to fix>.
       See CLAUDE.md §<section> + <relevant doc>.
       [CWE-XXX] (if applicable)
     severity: WARNING  # promote to ERROR once stabilised
     languages: [python]
     paths:
       include: ["rootsystem/application/<scope>"]
       exclude: ["tests/**"]
     patterns:
       - pattern: <Semgrep pattern>
     metadata:
       cwe: "CWE-XXX: <description>"
       category: security|correctness
   ```

4. **Start at WARNING.** Promote to ERROR only after:
   - Running `semgrep scan --config .semgrep/` against the full repo and
     verifying 0 false positives (or silencing the known ones with `# nosem`
     + justification).
   - Surviving 1–2 PRs without causing unnecessary friction.

5. If the rule includes paths with persistent legitimate false positives,
   list them under `paths.exclude` with a comment explaining why they are
   excluded (the same way `core/cache.py` is excluded from the TOCTOU rule —
   it IS the implementation of the primitive).

## Silencing an individual finding

```python
result = await cache_get(key)  # nosem: nori-toctou-cache-read-modify-write  -- intentional circuit breaker; DB is authoritative
```

The justification after `--` is mandatory. PRs without justification should be
sent back in review. Same pattern as the `--ignore-vuln` documented in
`.github/workflows/audit.yml`.

## Running locally

```bash
pip install semgrep
semgrep scan --config p/python --config p/security-audit --config .semgrep/
```

For custom rules only (fast, no remote pulls):

```bash
semgrep scan --config .semgrep/nori-rules.yml
```

To validate that a custom rule fires correctly (positive + negative cases):

```bash
semgrep --test --config .semgrep/nori-rules.yml .semgrep/tests/nori-rules.py
```

The annotations are inline:

- `# ruleid: name` — the next line MUST trigger that rule
- `# ok: name` — the next line MUST NOT trigger that rule
- `# nosem: name -- justification` — silence a finding (also honoured by `--test`)

The test file is listed in `.semgrepignore` so the main scan does not flag the
synthetic patterns as real findings.

## Roadmap

- **Iteration 1 (shipped)**: 3 custom rules (TOCTOU cache, JWT subscript, CLI
  CWD path). Workflow breaks CI on ERROR. WARNs are reported without breaking.
- **Iteration 2 (shipped)**: 2 more custom rules — httpx per-call AsyncClient
  in services/ (ERROR) and synchronous open() inside async def in services/
  (WARNING). Test suite at `.semgrep/tests/nori-rules.py` with `# ruleid` /
  `# ok` annotations, validated via `semgrep --test`.
- **Iteration 3 (shipped 2026-05-26)**: graduate INV-002 (sync I/O in async)
  to L3 full. Added 3 rules: `nori-sync-time-sleep-in-async` (ERROR, core/ +
  services/), `nori-sync-requests-import-in-services` (ERROR, services/),
  `nori-sync-subprocess-in-async` (ERROR, core/ + services/ except cli.py
  which is a sync entry script). INV-001 (TOCTOU) `services/*` swept
  manually — zero usages, trivially covered. Total: 8 custom rules.
- **Iteration 4 (next)**: integrate Semgrep custom rules into pre-commit
  hook (custom rules only — public rulesets are too slow for local).
- **Iteration 5**: add CodeQL as a second layer for real data-flow analysis
  (free on GitHub Actions for OSS).
- **Iteration 6**: queue allow-list bypass detection. Hard to express
  statically because `push()`'s func_path is often dynamic; would need a
  taint rule or a manual review checklist instead.

Next graduation candidates (see INVARIANTS.md roadmap table):

- INV-007 to L3 full — add `cache_get` `_store` backend bypass detection
- INV-027 to L3 full — extend CWD-path rule to `os.path.join` + broaden scope
- INV-020 to L3 — detect `asyncio.create_task` without `add_done_callback`
- INV-013 to L3 (rule) — generalize zip-slip detector
