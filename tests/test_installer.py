"""Tests for docs/install.py — the curl-piped installer.

The installer ships verbatim to nori.sembei.mx via mkdocs and is not on the
package import path, so we load it via importlib.spec_from_file_location.
Network calls (resolve_release, fetch_and_extract) and venv creation are
stubbed by replacing them with fakes that point at a fixture-built
release_root mirroring the real .starter-manifest.json.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def installer():
    spec = importlib.util.spec_from_file_location(
        'install',
        REPO_ROOT / 'docs' / 'install.py',
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_release(tmp_path):
    """Build a release_root that mirrors the real .starter-manifest.json.

    Each declared path is created as a stub: directories get a sentinel file,
    regular files get a one-line marker. Tests that follow manifest evolution
    automatically because we read the real manifest from the repo root.
    """
    manifest = json.loads((REPO_ROOT / '.starter-manifest.json').read_text())

    release = tmp_path / '_fake_release'
    release.mkdir()
    (release / '.starter-manifest.json').write_text(json.dumps(manifest))

    for path in manifest.get('paths', []):
        real = REPO_ROOT / path
        fake = release / path
        if real.is_dir():
            fake.mkdir(parents=True)
            (fake / '.fake-sentinel').write_text('')
        else:
            fake.parent.mkdir(parents=True, exist_ok=True)
            fake.write_text(f'# fake {path}\n')

    return release, manifest


@pytest.fixture
def stub_installer(installer, fake_release, tmp_path, monkeypatch):
    release, _ = fake_release
    monkeypatch.setattr(installer, 'resolve_release', lambda v: 'v1.17.0')
    monkeypatch.setattr(installer, 'fetch_and_extract', lambda tag, tmp: release)
    monkeypatch.setattr(installer, 'create_venv', lambda dest: None)
    monkeypatch.setattr(installer, 'install_deps', lambda dest: None)
    monkeypatch.chdir(tmp_path)
    return installer


def test_scaffolds_into_nonexistent_dir(stub_installer, tmp_path):
    stub_installer.main(['my-project', '--no-venv'])

    dest = tmp_path / 'my-project'
    assert (dest / 'nori.py').exists()
    assert (dest / 'rootsystem').is_dir()
    assert 'Built with [Nori]' in (dest / 'README.md').read_text()


def test_scaffolds_into_empty_existing_dir(stub_installer, tmp_path):
    (tmp_path / 'my-project').mkdir()

    stub_installer.main(['my-project', '--no-venv'])

    assert (tmp_path / 'my-project' / 'nori.py').exists()


def test_preserves_unrelated_files(stub_installer, tmp_path):
    dest = tmp_path / 'my-project'
    dest.mkdir()
    (dest / 'TEMPLATE_USAGE.md').write_text('template owns this')
    (dest / '.github').mkdir()
    (dest / '.github' / 'CODEOWNERS').write_text('@team')

    stub_installer.main(['my-project', '--no-venv'])

    assert (dest / 'TEMPLATE_USAGE.md').read_text() == 'template owns this'
    assert (dest / '.github' / 'CODEOWNERS').read_text() == '@team'
    assert (dest / 'nori.py').exists()


def test_aborts_on_manifest_conflict(stub_installer, tmp_path, capsys):
    dest = tmp_path / 'my-project'
    dest.mkdir()
    (dest / 'nori.py').write_text("# user's existing nori.py")

    with pytest.raises(SystemExit) as exc:
        stub_installer.main(['my-project', '--no-venv'])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert 'Cannot scaffold' in err
    assert 'nori.py' in err
    assert (dest / 'nori.py').read_text() == "# user's existing nori.py"


def test_preserves_existing_readme(stub_installer, tmp_path):
    dest = tmp_path / 'my-project'
    dest.mkdir()
    (dest / 'README.md').write_text('# my own readme\n')

    stub_installer.main(['my-project', '--no-venv'])

    assert (dest / 'README.md').read_text() == '# my own readme\n'


def test_preserves_existing_git_dir(stub_installer, tmp_path, monkeypatch):
    dest = tmp_path / 'my-project'
    dest.mkdir()
    (dest / '.git').mkdir()
    (dest / '.git' / 'config').write_text('# user existing git\n')

    subprocess_calls = []
    monkeypatch.setattr(
        stub_installer.subprocess,
        'run',
        lambda *args, **kwargs: subprocess_calls.append(args),
    )

    stub_installer.main(['my-project', '--no-venv'])

    assert subprocess_calls == []
    assert (dest / '.git' / 'config').read_text() == '# user existing git\n'


def test_failure_cleanup_preserves_user_files(stub_installer, tmp_path, monkeypatch):
    dest = tmp_path / 'my-project'
    dest.mkdir()
    (dest / 'TEMPLATE_USAGE.md').write_text('survive me')

    def boom(d):
        raise RuntimeError('simulated mid-run failure')

    monkeypatch.setattr(stub_installer, 'setup_env', boom)

    with pytest.raises(RuntimeError, match='simulated mid-run failure'):
        stub_installer.main(['my-project', '--no-venv'])

    assert (dest / 'TEMPLATE_USAGE.md').read_text() == 'survive me'
    assert not (dest / 'nori.py').exists()
    assert not (dest / 'rootsystem').exists()


def test_manifest_is_consistent_with_source_tree():
    """Repo-state lint per CLAUDE.md §7.4: every path declared in the manifest
    must exist in the source tree, otherwise the next release zip will be
    missing files and the installer will die with 'manifest references
    missing path'."""
    manifest = json.loads((REPO_ROOT / '.starter-manifest.json').read_text())
    missing = [p for p in manifest['paths'] if not (REPO_ROOT / p).exists()]
    assert not missing, f'Manifest references paths missing from source tree: {missing}'
