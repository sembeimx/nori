#!/usr/bin/env python3
"""Nori installer — creates a clean new Nori project.

Usage:
    curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project
    curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project --no-venv
    curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project --no-install
    curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project --version 1.10.0
    curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project --version 1.10.0 --checksum 3a7b...

Flags:
    --no-venv      Skip creating .venv (implies --no-install).
    --no-install   Create .venv but skip pip install.
    --version V    Install a specific Nori version. Defaults to latest.
    --checksum H   Verify the release zip's SHA-256 matches H before extracting.
                   Aborts on mismatch. Recommended for CI/CD pinning.

The release zip's SHA-256 is always printed during install — record it from
a trusted run and pass it back via --checksum on subsequent installs to
catch tag mutation, mirror compromise, or any silent change to the artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GITHUB_REPO = 'sembeimx/nori'
GITHUB_API = 'https://api.github.com'
MIN_PYTHON = (3, 10)
MIN_NORI_VERSION = '1.10.0'


def die(msg: str, code: int = 1) -> None:
    print(f'\n  Error: {msg}', file=sys.stderr)
    sys.exit(code)


def parse_args(argv: list[str]) -> dict:
    args: dict = {
        'name': None,
        'no_venv': False,
        'no_install': False,
        'version': None,
        'checksum': None,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--no-venv':
            args['no_venv'] = True
            args['no_install'] = True
        elif a == '--no-install':
            args['no_install'] = True
        elif a == '--version':
            i += 1
            if i >= len(argv):
                die('--version requires a value')
            args['version'] = argv[i].lstrip('v')
        elif a == '--checksum':
            i += 1
            if i >= len(argv):
                die('--checksum requires a SHA-256 hex value')
            args['checksum'] = argv[i].strip().lower()
        elif a in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)
        elif a.startswith('-'):
            die(f'Unknown flag: {a}')
        else:
            if args['name'] is not None:
                die('Pass only one project name')
            args['name'] = a
        i += 1
    return args


def validate_name(name: str) -> None:
    if not name:
        die('Project name required.\n  Usage: curl -fsSL https://nori.sembei.mx/install.py | python3 - my-project')
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', name):
        die('Project name must start with a letter and contain only letters, digits, hyphens, or underscores')


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        die(f'Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required (you have {sys.version.split()[0]})')


def github_api(endpoint: str) -> dict:
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/{endpoint}'
    req = Request(
        url,
        headers={
            'User-Agent': 'Nori-Installer',
            'Accept': 'application/vnd.github+json',
        },
    )
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urlopen(req) as resp:
        return json.loads(resp.read())


def download(url: str, dest: Path) -> None:
    req = Request(url, headers={'User-Agent': 'Nori-Installer'})
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urlopen(req) as resp, open(dest, 'wb') as f:
        shutil.copyfileobj(resp, f)


def resolve_release(version: str | None) -> str:
    try:
        if version:
            release = github_api(f'releases/tags/v{version}')
        else:
            release = github_api('releases/latest')
    except HTTPError as e:
        if e.code == 404:
            die(f'Version v{version} not found' if version else 'No releases found')
        raise
    except URLError as e:
        die(f'Could not reach GitHub — {e.reason}')
    return release['tag_name']


def fetch_and_extract(tag: str, tmp: Path, expected_checksum: str | None = None) -> Path:
    zip_url = f'https://github.com/{GITHUB_REPO}/archive/refs/tags/{tag}.zip'
    print(f'  URL:     {zip_url}')
    zip_path = tmp / 'release.zip'
    try:
        download(zip_url, zip_path)
    except (URLError, HTTPError) as e:
        die(f'Download failed — {e}')

    actual_checksum = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    print(f'  SHA-256: {actual_checksum}')

    if expected_checksum and expected_checksum != actual_checksum:
        die(
            f'Checksum mismatch — refusing to extract.\n'
            f'    Expected: {expected_checksum}\n'
            f'    Got:      {actual_checksum}'
        )

    extract_dir = tmp / 'extracted'
    extract_dir.mkdir()
    _safe_extract(zip_path, extract_dir)
    children = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(children) != 1:
        die('Unexpected release zip structure')
    return children[0]


def _safe_extract(zip_path: Path, dest: Path) -> None:
    """Extract a zip file member-by-member, refusing path traversal.

    A compromised release archive could ship members like
    ``nori-vX.Y.Z/../../etc/passwd`` — ``zipfile.extractall()`` does
    not protect against that on Python <3.12 and is opt-in (``filter=``)
    on 3.12+. We resolve every member's destination path and assert
    it stays inside ``dest`` before writing.
    """
    base = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (base / member.filename).resolve()
            try:
                target.relative_to(base)
            except ValueError:
                die(f'Refusing to extract member outside target directory: {member.filename!r}')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out)


def load_manifest(release_root: Path, tag: str) -> dict:
    manifest_path = release_root / '.starter-manifest.json'
    if not manifest_path.exists():
        die(
            f'Release {tag} does not include .starter-manifest.json.\n'
            f'  The installer requires Nori v{MIN_NORI_VERSION} or later.\n'
            f'  Try: --version {MIN_NORI_VERSION}'
        )
    with open(manifest_path) as f:
        return json.load(f)


def copy_starter(release_root: Path, dest: Path, manifest: dict) -> None:
    for path in manifest.get('paths', []):
        src = release_root / path
        dst = dest / path
        if not src.exists():
            die(f'Manifest references missing path in release: {path}')
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for empty in manifest.get('empty_dirs', []):
        d = dest / empty
        d.mkdir(parents=True, exist_ok=True)
        (d / '.gitkeep').touch()


def write_user_readme(dest: Path, name: str) -> None:
    if (dest / 'README.md').exists():
        return
    content = f"""# {name}

Built with [Nori](https://nori.sembei.mx).

## Run

```bash
source .venv/bin/activate
python3 nori.py migrate:init
python3 nori.py serve
```

Open http://localhost:8000.
"""
    (dest / 'README.md').write_text(content)


def init_git(dest: Path) -> None:
    if (dest / '.git').exists():
        return
    if not shutil.which('git'):
        print('  Skipping git init (git not on PATH)')
        return
    subprocess.run(['git', 'init', '-q'], cwd=dest, check=True)


def setup_env(dest: Path) -> None:
    src = dest / '.env.example'
    target = dest / 'rootsystem' / 'application' / '.env'
    if src.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)


def create_venv(dest: Path) -> None:
    subprocess.run([sys.executable, '-m', 'venv', '.venv'], cwd=dest, check=True)


def install_deps(dest: Path) -> None:
    pip = dest / '.venv' / ('Scripts' if os.name == 'nt' else 'bin') / 'pip'
    subprocess.run([str(pip), 'install', '-q', '-r', 'requirements.txt'], cwd=dest, check=True)


def main(argv: list[str]) -> None:
    check_python()
    args = parse_args(argv)
    validate_name(args['name'] or '')
    name: str = args['name']

    dest = Path.cwd() / name

    print(f'Creating Nori project: {name}')
    tag = resolve_release(args['version'])
    print(f'  Using release: {tag}')

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        print('  Downloading release...')
        release_root = fetch_and_extract(tag, tmp, args.get('checksum'))
        manifest = load_manifest(release_root, tag)

        # Refuse only when manifest paths would clobber existing files.
        # Anything else at dest is outside Nori's declared territory.
        conflicts = [p for p in manifest.get('paths', []) if (dest / p).exists()]
        if conflicts:
            die(
                f"Cannot scaffold into '{name}' — these paths already exist:\n"
                + '\n'.join(f'  - {p}' for p in conflicts)
            )

        dest_pre_existed = dest.exists()
        print('  Copying starter files...')
        dest.mkdir(exist_ok=True)
        try:
            copy_starter(release_root, dest, manifest)
            write_user_readme(dest, name)
            setup_env(dest)
            init_git(dest)

            if not args['no_venv']:
                print('  Creating .venv...')
                create_venv(dest)
                if not args['no_install']:
                    print('  Installing dependencies (this can take a minute)...')
                    install_deps(dest)
        except Exception:
            if dest_pre_existed:
                # Only remove paths Nori claims via the manifest; leave the
                # user's pre-existing files alone.
                for p in manifest.get('paths', []):
                    target = dest / p
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    elif target.exists():
                        target.unlink()
            else:
                shutil.rmtree(dest, ignore_errors=True)
            raise

    print()
    print(f'Done — project ready at ./{name}')
    print()
    print('Next steps:')
    print(f'  cd {name}')
    if args['no_venv']:
        print('  python3 -m venv .venv && source .venv/bin/activate')
        print('  pip install -r requirements.txt')
    elif args['no_install']:
        print('  source .venv/bin/activate')
        print('  pip install -r requirements.txt')
    else:
        print('  source .venv/bin/activate')
    print('  python3 nori.py migrate:init')
    print('  python3 nori.py serve')
    print()
    print('Docs: https://nori.sembei.mx')


if __name__ == '__main__':
    main(sys.argv[1:])
