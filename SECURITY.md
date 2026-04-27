# Security Policy

## Supported Versions

Nori is a single-track release line. Security fixes ship in the **latest minor version**. There are no LTS branches.

| Version | Supported                  |
|---------|----------------------------|
| 1.12.x  | ✅ Active                  |
| < 1.12  | ❌ Upgrade to the latest   |

If you are running an unsupported version, run `python3 nori.py framework:update` to upgrade to the latest release. Upgrades are designed to be in-place — `requirements.nori.txt` and the `core/` directory are framework-owned and refresh automatically.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, email **security@sembei.mx** with:

1. A description of the vulnerability and the affected components
2. Steps to reproduce
3. The impact you assess (information disclosure, RCE, auth bypass, etc.)
4. Any suggested mitigation or patch

### Response timeline

| Stage                              | Target          |
|-----------------------------------|-----------------|
| Acknowledgement of receipt         | 3 business days |
| Initial impact assessment          | 7 business days |
| Coordinated disclosure timeline    | 14 business days|

Public disclosure happens **only after a fix has shipped** on a tagged release. We credit reporters in the release notes and CHANGELOG unless anonymity is requested.

## Scope

### In scope

- The Nori framework code in this repository (`rootsystem/`, `core/`, CLI)
- Default middleware configurations (CSRF, security headers, rate limiting)
- Default storage / mail / search drivers shipped under `services/`
- The starter manifest and `framework:update` mechanism

### Out of scope

- Vulnerabilities in user applications built on Nori — those are the application owner's responsibility
- Third-party dependency CVEs — report to upstream; Nori's `pip-audit` CI gate tracks them automatically
- Issues requiring physical access to a host or compromised infrastructure
- Self-XSS, social engineering, denial-of-service against a specific deployment without a framework-side fix

## Hardening defaults

Nori ships with security-conscious defaults out of the box:

- **CSRF protection** — mandatory tokens on all POST/PUT/PATCH/DELETE
- **Password hashing** — PBKDF2 with per-user salt
- **Brute-force protection** — per-account lockout with escalating backoff (`core/auth/login_guard.py`)
- **JWT revocation** — cache-backed `jti` blacklist; expired tokens auto-removed
- **Security headers** — X-Frame-Options DENY, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
- **Rate limiting** — pluggable memory / Redis backends, per-route configuration
- **File upload validation** — extension + MIME + magic-byte verification on every `save_upload()`
- **Audit logging** — `audit()` helper wires sensitive actions to a queryable `audit_log` table
- **Fail-fast on misconfigured Redis** (since v1.11.0) — no silent fallback to memory cache/throttle
- **Request-ID propagation** (since v1.11.0) — every log record under a request carries a trace ID for forensic correlation
- **Deep `/health` endpoint** (since v1.12.0) — orchestrators can detect post-boot dependency failures
- **CI security gates** — `pip-audit` on every push (dependency vulnerabilities), `ruff S` rules (Bandit-equivalent SAST), `mypy` (type bugs), secrets scanning (gitleaks)

See [docs/security.md](https://nori.sembei.mx/security/) for the complete reference.
