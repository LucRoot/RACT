"""Version invariant tests for RACT."""

from __future__ import annotations

import re
from pathlib import Path

import ract


def _version_file_value() -> str:
    """Read the canonical version string from the VERSION file."""
    path = Path(__file__).resolve().parents[2] / "VERSION"
    return path.read_text(encoding="utf-8").strip()


def test_package_version_is_release() -> None:
    """The package version must be a PEP 440 release identifier — a final
    ``MAJOR.MINOR.PATCH`` triplet OR a ``MAJOR.MINOR.PATCHrcN`` release
    candidate. v0.4.1 is a final release (no rc suffix); prior tag
    ``v0.4.0-rc1`` was a release candidate. Both spellings pass this
    predicate, and PEP 440 normalization keeps identity holding.
    """
    version = ract.__version__
    # Final MAJOR.MINOR.PATCH OR MAJOR.MINOR.PATCHrcN (PEP 440 canonical).
    assert re.fullmatch(r"\d+\.\d+\.\d+(rc\d+)?", version), (
        f"version {version!r} is not a PEP 440 final release or release candidate"
    )
    # Alpha/beta pre-releases still refused — we only ship 'final' and 'rc'.
    assert re.search(r"\d+a\d+$", version) is None, "alpha pre-releases refused"
    assert re.search(r"\d+b\d+$", version) is None, "beta pre-releases refused"


def test_package_version_matches_version_file() -> None:
    """``__version__`` must resolve to the same PEP 440 version identity as
    the VERSION file's parseable version token. v0.4.1 carries the
    literal string ``0.4.1`` across VERSION, pyproject.toml, and
    ``__init__.py`` (no rc suffix, no normalization needed). The regex
    still accepts an optional ``rcN`` token so prior tag-close forms
    like ``0.4.0-rc1`` remain parseable when the harness is exercised
    on historical tags."""
    from packaging.version import Version

    file_value = _version_file_value()
    # VERSION may carry 'RACT vX.Y.Z[-rcN] - <codename>' header; extract the
    # full semver-plus-optional-pre-release token.
    match = re.search(r"v?(\d+\.\d+\.\d+(?:[-.]?rc\d+)?)", file_value)
    assert match, f"could not parse a version token from VERSION: {file_value!r}"
    file_version = Version(match.group(1))
    module_version = Version(ract.__version__)
    assert module_version == file_version, (
        f"__version__ {ract.__version__!r} disagrees with VERSION file "
        f"{match.group(1)!r} (as identities: {module_version!r} vs {file_version!r})"
    )
