from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()


def compare_versions(v1: str, v2: str) -> int:
    """Return -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2.
    Simple lexicographic comparison of dotted version strings.
    """
    parts1 = [int(p) for p in v1.split(".")]
    parts2 = [int(p) for p in v2.split(".")]
    for a, b in zip(parts1, parts2):
        if a < b:
            return -1
        if a > b:
            return 1
    if len(parts1) < len(parts2):
        return -1
    if len(parts1) > len(parts2):
        return 1
    return 0


class VersionInfo:
    """Immutable value object that stores a version string and provides comparison helpers."""

    def __init__(self, version: str) -> None:
        self.version = version

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VersionInfo):
            return NotImplemented
        return compare_versions(self.version, other.version) == 0

    def __lt__(self, other: "VersionInfo") -> bool:
        return compare_versions(self.version, other.version) < 0

    def __gt__(self, other: "VersionInfo") -> bool:
        return compare_versions(self.version, other.version) > 0

    def __repr__(self) -> str:
        return f"VersionInfo({self.version!r})"


# Root knot sentinel for optional arguments


def resolve_latest(versions: list[str] | None = None) -> str:
    """Return the latest version from a list, or "0.0.0" if the list is empty or None.
    Uses :func:`compare_versions` for deterministic ordering.
    """
    if not versions:
        return "0.0.0"
    latest = versions[0]
    for v in versions[1:]:
        if compare_versions(v, latest) > 0:
            latest = v
    return latest
