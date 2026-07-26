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
    """The package version must be a final release, not a pre-release.

    A final release matches ``MAJOR.MINOR.PATCH`` with no ``rc``/``a``/``b``
    suffix. The literal is not frozen to a specific number so this test tracks
    releases instead of bit-rotting at each bump.
    """
    version = ract.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"version {version!r} is not a final MAJOR.MINOR.PATCH release"
    )
    assert "rc" not in version
    assert "a" not in version
    assert "b" not in version


def test_package_version_matches_version_file() -> None:
    """__version__ must agree with the canonical VERSION file."""
    file_value = _version_file_value()
    # VERSION may carry a 'RACT vX.Y.Z - <codename>' header; extract the triplet.
    match = re.search(r"\d+\.\d+\.\d+", file_value)
    assert match, f"could not parse a version triplet from VERSION: {file_value!r}"
    assert ract.__version__ == match.group(0), (
        f"__version__ {ract.__version__!r} disagrees with VERSION file {match.group(0)!r}"
    )
