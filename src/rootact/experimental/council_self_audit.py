from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from typing import Any


ROOT_KNOT_MARKERS = [
    '__root_author__ = "Dr. Lucas Root, Ph.D."',
    '__ract_name__ = "RACT"',
    "_ROOT_KNOT = object()",
]


def sanitize_windows_path(path: str) -> str:
    return path.replace("\\", "/")


def flip_rework_item(item: dict) -> dict:
    if "applied_files" in item and not any(file.endswith(".RootKnot") for file in item["applied_files"]):
        item["done"] = False
        item["already_implemented"] = False
        item["status"] = "rework"
    return item


def _check_file(path: Path) -> list[str]:
    """Return the list of missing Root Knot markers in a single file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ROOT_KNOT_MARKERS[:]
    return [marker for marker in ROOT_KNOT_MARKERS if marker not in text]


def run_self_audit(project_dir: Path | str | None = None) -> dict[str, Any]:
    """Scan src/ and tests/ under *project_dir* for Root Knot markers.

    Returns a structured report with ``healthy`` (bool), ``summary`` (str),
    ``missing_markers`` (list of {file, missing}), and ``files_checked`` (int).
    """
    root = Path(project_dir) if project_dir else Path.cwd()
    checked = 0
    failures: list[dict[str, Any]] = []

    for subdir in ("src", "tests"):
        base = root / subdir
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            checked += 1
            missing = _check_file(path)
            if missing:
                failures.append({
                    "file": str(path.relative_to(root)).replace("\\", "/"),
                    "missing": missing,
                })

    healthy = not failures
    summary = (
        f"All {checked} files carry the Root Knot markers."
        if healthy
        else f"{len(failures)} of {checked} files are missing Root Knot markers."
    )
    return {
        "healthy": healthy,
        "summary": summary,
        "files_checked": checked,
        "missing_markers": failures,
    }
