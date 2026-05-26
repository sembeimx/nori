"""Tests for scripts/release.py.

Scope: the pure parser/mutator helpers (parse_semver, version-file
read/write, CHANGELOG section extraction and transformation). The git
and subprocess layer is NOT tested here — the script's --dry-run path
covers that at the integration level on every real release.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load scripts/release.py as a module without installing it. Plain importlib
# keeps the test file in the existing tests/ tree without any path hack.
_RELEASE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'release.py'
_spec = importlib.util.spec_from_file_location('nori_release_script', _RELEASE_PATH)
assert _spec is not None and _spec.loader is not None
release = importlib.util.module_from_spec(_spec)
sys.modules['nori_release_script'] = release
_spec.loader.exec_module(release)


# ---------------------------------------------------------------------------
# parse_semver
# ---------------------------------------------------------------------------


def test_parse_semver_accepts_strict_major_minor_patch():
    assert release.parse_semver('1.35.0') == (1, 35, 0)
    assert release.parse_semver('0.0.1') == (0, 0, 1)
    assert release.parse_semver('10.20.30') == (10, 20, 30)


def test_parse_semver_rejects_v_prefix(capsys):
    with pytest.raises(SystemExit):
        release.parse_semver('v1.35.0')
    err = capsys.readouterr().err
    assert 'MAJOR.MINOR.PATCH' in err


def test_parse_semver_rejects_prerelease(capsys):
    with pytest.raises(SystemExit):
        release.parse_semver('1.35.0-rc1')


def test_parse_semver_rejects_garbage(capsys):
    with pytest.raises(SystemExit):
        release.parse_semver('not-a-version')


def test_parse_semver_rejects_two_segments(capsys):
    with pytest.raises(SystemExit):
        release.parse_semver('1.35')


# ---------------------------------------------------------------------------
# version.py read/write
# ---------------------------------------------------------------------------


def test_read_version_file_single_quoted():
    src = "__version__ = '1.34.0'\n"
    assert release.read_version_file(src) == '1.34.0'


def test_read_version_file_double_quoted():
    src = '__version__ = "2.0.0"\n'
    assert release.read_version_file(src) == '2.0.0'


def test_read_version_file_with_other_lines():
    src = '"""docstring."""\n\nfrom __future__ import annotations\n\n__version__ = \'1.34.0\'\n'
    assert release.read_version_file(src) == '1.34.0'


def test_read_version_file_raises_when_missing():
    with pytest.raises(ValueError):
        release.read_version_file('no version here\n')


def test_write_version_file_replaces_value_only():
    src = "__version__ = '1.34.0'\n"
    out = release.write_version_file(src, '1.35.0')
    assert out == "__version__ = '1.35.0'\n"


def test_write_version_file_preserves_double_quotes():
    src = '__version__ = "1.34.0"\n'
    out = release.write_version_file(src, '1.35.0')
    assert out == '__version__ = "1.35.0"\n'


def test_write_version_file_replaces_exactly_once():
    """If someone added a stray '__version__' literal in a comment, we must
    not rewrite it. Only the first canonical assignment changes.
    """
    src = (
        '"""Module doc mentions __version__ in passing."""\n'
        "__version__ = '1.34.0'\n"
        '# trailing comment about __version__ should not be touched\n'
    )
    out = release.write_version_file(src, '1.35.0')
    assert "__version__ = '1.35.0'" in out
    # The comment line is untouched.
    assert '# trailing comment about __version__ should not be touched' in out


# ---------------------------------------------------------------------------
# CHANGELOG section extraction
# ---------------------------------------------------------------------------


SAMPLE_CHANGELOG = """# Changelog

Header text.

---

## [Unreleased]

### Added

- Thing A
- Thing B

### Fixed

- Bug C

---

## [1.34.0] — 2026-04-30

### Fixed (BREAKING)

- SVG XSS hardening.

---

## [1.33.0] — 2026-04-25

### Added

- Session revocation channel.
"""


def test_extract_unreleased_section_returns_body_and_indices():
    body, start, end = release.extract_section(SAMPLE_CHANGELOG, '## [Unreleased]')
    assert '### Added' in body
    assert '- Thing A' in body
    assert '### Fixed' in body
    assert '- Bug C' in body
    # body must not include the next section's header
    assert '## [1.34.0]' not in body
    # start indexes the [Unreleased] header line itself
    lines = SAMPLE_CHANGELOG.splitlines(keepends=True)
    assert lines[start].rstrip() == '## [Unreleased]'
    # end indexes the next ## header
    assert lines[end].startswith('## [1.34.0]')


def test_extract_section_raises_when_header_missing():
    with pytest.raises(ValueError, match='section not found'):
        release.extract_section(SAMPLE_CHANGELOG, '## [9.9.9]')


def test_extract_section_strips_trailing_horizontal_rule():
    body, _, _ = release.extract_section(SAMPLE_CHANGELOG, '## [1.34.0] — 2026-04-30')
    # The body must NOT include the trailing `---` separator.
    assert not body.rstrip().endswith('---')
    assert '- SVG XSS hardening.' in body


def test_is_unreleased_empty_true_for_placeholder_only():
    body = release.UNRELEASED_PLACEHOLDER
    assert release.is_unreleased_empty(body) is True


def test_is_unreleased_empty_false_for_content():
    assert release.is_unreleased_empty('### Added\n- something\n') is False


def test_is_unreleased_empty_handles_surrounding_whitespace():
    body = f'\n\n{release.UNRELEASED_PLACEHOLDER}\n\n'
    assert release.is_unreleased_empty(body) is True


# ---------------------------------------------------------------------------
# transform_changelog — the heart of the release flow
# ---------------------------------------------------------------------------


def test_transform_changelog_renames_unreleased_with_date():
    new_text, body = release.transform_changelog(SAMPLE_CHANGELOG, '1.35.0', '2026-06-01')
    assert '## [1.35.0] — 2026-06-01' in new_text
    # The original [Unreleased] header should no longer be sitting where
    # the version 1.35.0 header now is, but a NEW fresh one must exist.
    assert '## [Unreleased]' in new_text  # the fresh one we inserted
    # The fresh Unreleased must come BEFORE the renamed 1.35.0
    fresh_idx = new_text.index('## [Unreleased]')
    released_idx = new_text.index('## [1.35.0]')
    assert fresh_idx < released_idx, 'fresh [Unreleased] must precede the renamed section'


def test_transform_changelog_fresh_unreleased_contains_placeholder():
    new_text, _ = release.transform_changelog(SAMPLE_CHANGELOG, '1.35.0', '2026-06-01')
    assert release.UNRELEASED_PLACEHOLDER in new_text


def test_transform_changelog_preserves_older_sections():
    new_text, _ = release.transform_changelog(SAMPLE_CHANGELOG, '1.35.0', '2026-06-01')
    assert '## [1.34.0] — 2026-04-30' in new_text
    assert '## [1.33.0] — 2026-04-25' in new_text


def test_transform_changelog_returned_body_matches_renamed_section():
    new_text, body = release.transform_changelog(SAMPLE_CHANGELOG, '1.35.0', '2026-06-01')
    # The returned body is the content under the renamed [1.35.0] section,
    # which is the same content that was under [Unreleased] in the input.
    assert '### Added' in body
    assert '- Thing A' in body
    assert '- Bug C' in body
    # The returned body must be a substring of the new CHANGELOG.
    assert body.strip() in new_text


def test_transform_changelog_refuses_empty_unreleased():
    empty_input = SAMPLE_CHANGELOG.replace(
        '### Added\n\n- Thing A\n- Thing B\n\n### Fixed\n\n- Bug C\n',
        release.UNRELEASED_PLACEHOLDER + '\n',
    )
    with pytest.raises(ValueError, match='empty'):
        release.transform_changelog(empty_input, '1.35.0', '2026-06-01')


# ---------------------------------------------------------------------------
# extract_release_body — what the CI workflow consumes
# ---------------------------------------------------------------------------


def test_extract_release_body_returns_section_content_after_release_cut():
    """End-to-end: cut a release, then read the released body back. This
    is exactly the path .github/workflows/release.yml runs against the
    tag.
    """
    new_text, _ = release.transform_changelog(SAMPLE_CHANGELOG, '1.35.0', '2026-06-01')
    body = release.extract_release_body(new_text, '1.35.0')
    assert '### Added' in body
    assert '- Thing A' in body
    assert '- Bug C' in body
    # Must not include the next older section's header.
    assert '## [1.34.0]' not in body


def test_extract_release_body_works_on_pre_existing_section():
    """The function also has to work on sections that were already on
    disk before the release script existed (any historical release).
    """
    body = release.extract_release_body(SAMPLE_CHANGELOG, '1.34.0')
    assert '- SVG XSS hardening.' in body
    assert '## [1.33.0]' not in body


def test_extract_release_body_raises_for_unknown_version():
    with pytest.raises(ValueError, match='not found'):
        release.extract_release_body(SAMPLE_CHANGELOG, '9.9.9')
