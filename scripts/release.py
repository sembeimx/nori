#!/usr/bin/env python3
"""Cut a Nori release.

Replaces the historical 8-step manual sequence (bump version.py, write
CHANGELOG, commit, push, tag, push tag, write release notes, gh release
create) with a single validated command. Pure stdlib so it can run from
any clone without venv activation.

Usage
-----

    scripts/release.py 1.35.0                # cut release 1.35.0
    scripts/release.py 1.35.0 --dry-run      # validate only, do not mutate
    scripts/release.py 1.35.0 --skip-tests   # skip the local CI gate
    scripts/release.py 1.35.0 --unsigned     # produce an unsigned tag

The CI workflow `.github/workflows/release.yml` consumes the same parser:

    scripts/release.py --extract-changelog 1.35.0   # prints the [1.35.0] section to stdout

Pipeline
--------

1. Pre-flight validations (no mutations yet):
   - semver shape
   - working tree clean
   - on main, up-to-date with origin/main
   - version.py distinct from target
   - CHANGELOG has a non-empty [Unreleased] section
   - tag v<version> does not exist (local or remote)
   - local CI green (ruff, mypy, pytest, semgrep) unless --skip-tests

2. Atomic mutations:
   - version.py: __version__ = '<target>'
   - CHANGELOG: rename [Unreleased] header to [<target>] — <today>,
     insert fresh empty [Unreleased] block above

3. Commit + signed tag + push:
   - git commit -m "release: v<target>"
   - git tag -s v<target> (unless --unsigned)
   - git push origin main
   - git push origin v<target>

After the tag lands on origin, .github/workflows/release.yml fires,
extracts the [<target>] section as the release body, and creates the
GitHub Release. sbom.yml then fires on release: published and attaches
the SBOM.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / 'rootsystem' / 'application' / 'core' / 'version.py'
CHANGELOG = REPO_ROOT / 'CHANGELOG.md'
VENV_PYTHON = REPO_ROOT / '.venv' / 'bin' / 'python'

SEMVER_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
VERSION_LINE_RE = re.compile(r"(__version__\s*=\s*['\"])([^'\"]+)(['\"])")
UNRELEASED_HEADER = '## [Unreleased]'
UNRELEASED_PLACEHOLDER = (
    '_Nothing accumulated yet — add entries here as they ship to '
    '`main` so the next release cut is just a rename + date stamp._'
)
FRESH_UNRELEASED_BLOCK = f'## [Unreleased]\n\n{UNRELEASED_PLACEHOLDER}\n'


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def die(msg: str, code: int = 1) -> None:
    print(f'error: {msg}', file=sys.stderr)
    sys.exit(code)


def step(msg: str) -> None:
    print(f'  {msg}')


def header(msg: str) -> None:
    print(f'\n{msg}')


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['git', *args], capture_output=True, text=True, check=check, cwd=REPO_ROOT)


# ---------------------------------------------------------------------------
# Parser / mutator helpers — pure functions, fully tested
# ---------------------------------------------------------------------------


def parse_semver(version: str) -> tuple[int, int, int]:
    """Validate the version string and return (major, minor, patch).

    Rejects v-prefixed input, pre-release/build metadata, and anything that
    is not strict MAJOR.MINOR.PATCH digits.
    """
    m = SEMVER_RE.match(version)
    if not m:
        die(f'version must be MAJOR.MINOR.PATCH (got {version!r})')
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def read_version_file(text: str) -> str:
    """Extract __version__ from a version.py source string."""
    m = VERSION_LINE_RE.search(text)
    if not m:
        raise ValueError('could not parse __version__ assignment')
    return m.group(2)


def write_version_file(text: str, new: str) -> str:
    """Return version.py source with __version__ replaced by new."""
    if not VERSION_LINE_RE.search(text):
        raise ValueError('no __version__ assignment to replace')
    return VERSION_LINE_RE.sub(rf'\g<1>{new}\g<3>', text, count=1)


def extract_section(changelog: str, header_text: str) -> tuple[str, int, int]:
    """Return (body, start_index, end_index) for a CHANGELOG section.

    The body is everything BETWEEN the header line and the next `## ` /
    `---` separator, stripped of surrounding blank lines. start_index and
    end_index span from the header line through the trailing separator.
    """
    lines = changelog.splitlines(keepends=True)
    # Find the header line.
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == header_text:
            start = i
            break
    if start is None:
        raise ValueError(f'section not found: {header_text!r}')
    # Find the next `## ` header that ends the section.
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith('## '):
            end = j
            break
    # Body: lines between header+1 and end, minus trailing horizontal rule
    # and minus surrounding blank lines.
    body_lines = lines[start + 1 : end]
    # Strip a trailing `---\n` separator if present.
    while body_lines and body_lines[-1].strip() in ('', '---'):
        body_lines.pop()
    # Strip leading blank lines.
    while body_lines and body_lines[0].strip() == '':
        body_lines.pop(0)
    return ''.join(body_lines), start, end


def is_unreleased_empty(body: str) -> bool:
    """True if the [Unreleased] body is only the placeholder paragraph."""
    return body.strip() == UNRELEASED_PLACEHOLDER


def transform_changelog(text: str, version: str, today: str) -> tuple[str, str]:
    """Rename [Unreleased] to [<version>] — <today> and insert a fresh
    [Unreleased] block above.

    Returns (new_changelog_text, released_body). released_body is the body
    of the renamed section, ready to be the GitHub Release notes.
    """
    body, start, end = extract_section(text, UNRELEASED_HEADER)
    if is_unreleased_empty(body):
        raise ValueError(
            '[Unreleased] section is empty (only the placeholder paragraph). '
            'Add at least one changelog entry before cutting a release.'
        )
    lines = text.splitlines(keepends=True)
    # Replace the [Unreleased] header line.
    lines[start] = f'## [{version}] — {today}\n'
    # Insert a fresh [Unreleased] block above the renamed section.
    insertion = f'{FRESH_UNRELEASED_BLOCK}\n---\n\n'
    lines.insert(start, insertion)
    return ''.join(lines), body


def extract_release_body(text: str, version: str) -> str:
    """For the CI workflow: get the body of the [<version>] section.

    Versioned headers carry a date suffix (`## [1.34.0] — 2026-04-30`), so
    a literal-equality match like extract_section() uses would miss them.
    This helper walks lines with startswith() instead.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(f'## [{version}]'):
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if lines[j].startswith('## '):
                    end = j
                    break
            body_lines = lines[i + 1 : end]
            while body_lines and body_lines[-1].strip() in ('', '---'):
                body_lines.pop()
            while body_lines and body_lines[0].strip() == '':
                body_lines.pop(0)
            return ''.join(body_lines)
    raise ValueError(f'section not found: [{version}]')


# ---------------------------------------------------------------------------
# Pre-flight validations
# ---------------------------------------------------------------------------


def assert_working_tree_clean() -> None:
    if run_git('diff', '--quiet', check=False).returncode != 0:
        die('working tree has unstaged changes — commit or stash first')
    if run_git('diff', '--cached', '--quiet', check=False).returncode != 0:
        die('working tree has staged changes — commit or unstage first')


def assert_on_main_up_to_date() -> None:
    branch = run_git('branch', '--show-current').stdout.strip()
    if branch != 'main':
        die(f'must be on main to cut a release (currently on {branch!r})')
    run_git('fetch', 'origin', 'main')
    local = run_git('rev-parse', 'main').stdout.strip()
    remote = run_git('rev-parse', 'origin/main').stdout.strip()
    if local != remote:
        die('local main is not up-to-date with origin/main — pull (or push) first')


def assert_version_distinct(current: str, target: str) -> None:
    if current == target:
        die(f'version.py already says {target} — nothing to cut')


def assert_tag_absent(tag: str) -> None:
    local = run_git('tag', '-l', tag).stdout.strip()
    if local:
        die(f'tag {tag} already exists locally — delete it or choose a new version')
    remote = run_git('ls-remote', '--tags', 'origin', tag).stdout.strip()
    if remote:
        die(f'tag {tag} already exists on origin — choose a new version')


def assert_local_ci_green() -> None:
    """Run ruff, mypy, pytest, semgrep against the working tree. Each
    step echoes its progress; the first non-zero exit aborts.
    """
    venv_bin = REPO_ROOT / '.venv' / 'bin'

    def venv_or_path(tool: str) -> str:
        candidate = venv_bin / tool
        if candidate.exists():
            return str(candidate)
        found = shutil.which(tool)
        if not found:
            die(f'{tool} not found — install dev dependencies or pass --skip-tests')
        return found

    env_for_tests = {
        'DEBUG': 'true',
        'DB_ENGINE': 'sqlite',
        'DB_NAME': ':memory:',
        'SECRET_KEY': 'release-script-test-key',
    }

    checks: list[tuple[str, list[str], dict[str, str] | None]] = [
        ('ruff check', [venv_or_path('ruff'), 'check', '.'], None),
        ('ruff format --check', [venv_or_path('ruff'), 'format', '--check', '.'], None),
        ('mypy', [venv_or_path('mypy')], None),
        (
            'pytest',
            [venv_or_path('pytest'), 'tests/', '-q', '--no-header'],
            env_for_tests,
        ),
        (
            'semgrep (custom rules)',
            [
                venv_or_path('semgrep'),
                'scan',
                '--config',
                '.semgrep/nori-rules.yml',
                '--metrics=off',
                '--disable-version-check',
                '--error',
            ],
            None,
        ),
    ]
    import os as _os

    for name, cmd, extra_env in checks:
        step(f'running {name} …')
        env = dict(_os.environ)
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
        if result.returncode != 0:
            die(f'{name} failed — fix or pass --skip-tests')
    step('local CI suite green')


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def apply_mutations(target: str, today: str) -> str:
    """Write version.py + CHANGELOG. Return the released section body
    (used downstream by the CI workflow via --extract-changelog).
    """
    version_text = VERSION_FILE.read_text()
    new_version_text = write_version_file(version_text, target)
    changelog_text = CHANGELOG.read_text()
    new_changelog_text, released_body = transform_changelog(changelog_text, target, today)
    VERSION_FILE.write_text(new_version_text)
    CHANGELOG.write_text(new_changelog_text)
    return released_body


def commit_and_tag(target: str, *, signed: bool) -> None:
    run_git('add', str(VERSION_FILE), str(CHANGELOG))
    run_git('commit', '-m', f'release: v{target}')
    tag_args = ['tag']
    if signed:
        tag_args.append('-s')
    tag_args += ['-m', f'v{target}', f'v{target}']
    run_git(*tag_args)


def push_main_and_tag(target: str) -> None:
    run_git('push', 'origin', 'main')
    run_git('push', 'origin', f'v{target}')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cli_extract_changelog(version: str) -> int:
    """--extract-changelog: print the [<version>] section body to stdout.

    Called by .github/workflows/release.yml. Exits 1 if the section is
    missing so the workflow fails loudly rather than creating an empty
    GitHub Release.
    """
    parse_semver(version)
    try:
        body = extract_release_body(CHANGELOG.read_text(), version)
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    sys.stdout.write(body)
    return 0


def cli_cut_release(args: argparse.Namespace) -> int:
    target = args.version
    parse_semver(target)
    tag = f'v{target}'
    today = dt.date.today().isoformat()

    header('Pre-flight checks')
    step(f'semver: {target}')

    assert_working_tree_clean()
    step('working tree clean')

    assert_on_main_up_to_date()
    step('on main, up-to-date with origin/main')

    current = read_version_file(VERSION_FILE.read_text())
    assert_version_distinct(current, target)
    step(f'version.py is {current} — will bump to {target}')

    body, _start, _end = extract_section(CHANGELOG.read_text(), UNRELEASED_HEADER)
    if is_unreleased_empty(body):
        die('[Unreleased] section is empty — add changelog entries before cutting')
    step(f'CHANGELOG [Unreleased] has {len(body.splitlines())} lines of content')

    assert_tag_absent(tag)
    step(f'tag {tag} does not exist (local + remote)')

    if args.skip_tests:
        step('skipping local CI suite (--skip-tests)')
    else:
        assert_local_ci_green()

    if args.dry_run:
        header('Dry run — no mutations, no push')
        return 0

    header('Mutations')
    apply_mutations(target, today)
    step(f'version.py → {target}')
    step(f'CHANGELOG: [Unreleased] renamed to [{target}] — {today} + fresh [Unreleased] inserted')

    commit_and_tag(target, signed=not args.unsigned)
    step(f'commit: release: v{target}')
    step(f'{"signed " if not args.unsigned else ""}tag {tag}')

    header('Push')
    push_main_and_tag(target)
    step('pushed main + tag')
    step(f'.github/workflows/release.yml will now create the GitHub Release for {tag}')

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Cut a Nori release. See module docstring for the full pipeline.',
    )
    parser.add_argument(
        '--extract-changelog',
        metavar='VERSION',
        help='Print the body of CHANGELOG section [VERSION] to stdout, then exit. '
        'Used by the release workflow to seed GH Release notes.',
    )
    parser.add_argument('version', nargs='?', help='Target version, MAJOR.MINOR.PATCH')
    parser.add_argument('--dry-run', action='store_true', help='Validate only, do not mutate')
    parser.add_argument(
        '--skip-tests',
        action='store_true',
        help='Skip the local CI suite gate (ruff, mypy, pytest, semgrep)',
    )
    parser.add_argument(
        '--unsigned',
        action='store_true',
        help='Produce an unsigned tag. Default is `git tag -s` (GPG-signed).',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.extract_changelog:
        return cli_extract_changelog(args.extract_changelog)
    if not args.version:
        parser.error('version is required (or pass --extract-changelog VERSION)')
    return cli_cut_release(args)


if __name__ == '__main__':
    sys.exit(main())
