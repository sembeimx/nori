"""Test fixtures for Nori custom Semgrep rules.

This file is intentionally excluded from the main Semgrep scan (see
.semgrepignore) so the rules do not flag these synthetic cases as real
findings. It is used only via `semgrep --test --config .semgrep/`.

Each block below uses Semgrep's inline test annotations:

    "ruleid: NAME"  - the next line MUST trigger that rule (positive case)
    "ok: NAME"      - the next line MUST NOT trigger that rule (negative case)

Run with:

    semgrep --test --config .semgrep/nori-rules.yml .semgrep/tests/nori-rules.py

The harness compares the actual findings against these annotations and
fails if any rule under- or over-fires. This is the cheapest possible
regression test for the rules themselves.
"""

import asyncio
import pathlib
from pathlib import Path

import httpx


# ===========================================================================
# nori-toctou-cache-read-modify-write
# ===========================================================================

async def toctou_bug():
    # ruleid: nori-toctou-cache-read-modify-write
    current = await cache_get('counter', 0)
    await cache_set('counter', current + 1)


async def safe_atomic():
    # ok: nori-toctou-cache-read-modify-write
    await cache_incr('counter')


# ===========================================================================
# nori-jwt-payload-required-claim
# ===========================================================================

def jwt_unguarded_read(payload):
    # ruleid: nori-jwt-payload-required-claim
    token_id = payload['jti']
    return token_id


def jwt_unguarded_subject(payload):
    # ruleid: nori-jwt-payload-required-claim
    sub = payload['sub']
    return sub


def jwt_assignment(payload):
    # ok: nori-jwt-payload-required-claim
    payload['jti'] = 'new-id'


def jwt_guarded_read(payload):
    if 'jti' in payload:
        # ok: nori-jwt-payload-required-claim
        return payload['jti']
    return None


def jwt_safe_get(payload):
    # ok: nori-jwt-payload-required-claim
    return payload.get('jti')


# ===========================================================================
# nori-cli-cwd-relative-path
# ===========================================================================

def bad_cli_path():
    # ruleid: nori-cli-cwd-relative-path
    p = pathlib.Path("rootsystem/application")
    return p


def bad_cli_path_short():
    # ruleid: nori-cli-cwd-relative-path
    p = Path("commands")
    return p


def safe_cli_path():
    # ok: nori-cli-cwd-relative-path
    p = pathlib.Path(__file__).resolve().parent
    return p


# ===========================================================================
# nori-service-httpx-per-call-asyncclient
# ===========================================================================

async def bad_per_call_client():
    # ruleid: nori-service-httpx-per-call-asyncclient
    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.get('https://example.com')


async def bad_per_call_client_no_args():
    # ruleid: nori-service-httpx-per-call-asyncclient
    async with httpx.AsyncClient() as client:
        await client.get('https://example.com')


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # ok: nori-service-httpx-per-call-asyncclient
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def safe_reuses_singleton():
    client = _get_client()
    # ok: nori-service-httpx-per-call-asyncclient
    await client.get('https://example.com')


# ===========================================================================
# nori-service-sync-open-in-async
# ===========================================================================

async def bad_sync_open_in_async():
    # ruleid: nori-service-sync-open-in-async
    with open('/etc/secrets.json') as f:
        return f.read()


async def safe_open_via_to_thread():
    def _load():
        # The nested sync helper IS the pattern — the surrounding async
        # invokes via to_thread. Semgrep cannot distinguish nested sync
        # def from the outer async def, so the rule fires here and we
        # silence it with the documented marker.
        # nosem: nori-service-sync-open-in-async  -- nested in sync helper invoked via to_thread
        with open('/etc/secrets.json') as f:
            return f.read()

    return await asyncio.to_thread(_load)
