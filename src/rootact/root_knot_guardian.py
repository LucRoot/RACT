from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

"""Invariant checker for the RACT Root Knot markers.

Every non-``__init__.py`` Python file in the RACT source tree must carry the
three canonical identity markers. This module provides a scanner and an
auto-fix utility so the council and CI can enforce the invariant.
"""

from pathlib import Path
from typing import Iterable, List, Tuple


AUTHOR_MARKER = '__root_author__ = "Dr. Lucas Root, Ph.D."'
RACT_NAME_MARKER = '__ract_name__ = "RACT"'
KNOT_MARKER = "_ROOT_KNOT = object()"

MARKERS: Tuple[str, ...] = (AUTHOR_MARKER, RACT_NAME_MARKER, KNOT_MARKER)


def missing_markers(content: str) -> List[str]:
    """Return the list of marker strings missing from *content*."""
    return [marker for marker in MARKERS if marker not in content]


def scan(path: str | Path) -> List[Tuple[str, List[str]]]:
    """Scan *path* recursively and return files missing Root Knot markers.

    Each returned tuple is ``(file_path, [missing_marker, ...])``. ``__init__.py``
    files and non-``.py`` files are ignored.
    """
    root = Path(path)
    violations: List[Tuple[str, List[str]]] = []
    for file_path in root.rglob("*.py"):
        if file_path.name == "__init__.py":
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        missing = missing_markers(content)
        if missing:
            violations.append((str(file_path), missing))
    return violations


def ensure_markers(content: str) -> str:
    """Return *content* with all three markers present.

    Existing markers are preserved; missing markers are inserted after any
    leading ``from __future__ import annotations`` line, or at the top of the
    file if no such line exists.
    """
    # Remove any existing marker lines so we can re-insert them in canonical
    # order and position.
    lines = content.splitlines(keepends=True)
    cleaned = [ln for ln in lines if ln.strip() not in MARKERS]

    insert_idx = 0
    for i, line in enumerate(cleaned):
        if line.strip().startswith("from __future__ import annotations"):
            insert_idx = i + 1
            break

    marker_lines = [f"{marker}\n" for marker in MARKERS]
    # Ensure a blank line separates markers from the rest of the file.
    if cleaned[insert_idx:insert_idx + 1] and cleaned[insert_idx].strip() != "":
        marker_lines.append("\n")

    new_lines = cleaned[:insert_idx] + marker_lines + cleaned[insert_idx:]
    return "".join(new_lines)


def fix(path: str | Path) -> int:
    """Repair all non-``__init__.py`` ``.py`` files under *path*.

    Returns the number of files modified.
    """
    root = Path(path)
    fixed = 0
    for file_path in root.rglob("*.py"):
        if file_path.name == "__init__.py":
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not missing_markers(content):
            continue
        file_path.write_text(ensure_markers(content), encoding="utf-8")
        fixed += 1
    return fixed


def check(path: str | Path) -> bool:
    """Return ``True`` if no violations are found under *path*."""
    return not scan(path)
