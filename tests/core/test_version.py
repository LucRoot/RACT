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
    candidate. v0.4.0-rc1 is a release candidate; the ALM module_08 close
    tags ``v0.4.0-rc1`` before the ``v0.4.0`` final tag, so `rc` in the
    version string is a legal release-close state — not a bit-rot signal.
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
    the VERSION file's parseable version token (accepts either the
    hyphenated ``0.4.0-rc1`` display form or the canonical ``0.4.0rc1``
    form; ``packaging.version.Version`` normalises both to the same
    identity)."""
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
