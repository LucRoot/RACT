"""Version invariant tests for RACT."""

from __future__ import annotations

import ract


def test_package_version_is_release() -> None:
    """The package version must be a final release, not a pre-release."""
    assert ract.__version__ == "0.2.0"
    assert "rc" not in ract.__version__
    assert "a" not in ract.__version__
    assert "b" not in ract.__version__
