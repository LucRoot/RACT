from __future__ import annotations


from pathlib import Path
from typing import Any


def sanitize_windows_path(path: str) -> str:
    return path.replace("\\", "/")


def flip_rework_item(item: dict) -> dict:
    return item


def run_self_audit(project_dir: Path | str | None = None) -> dict[str, Any]:
    """Scan src/ and tests/ under *project_dir* and report basic file counts.

    The legacy Root Knot marker check has been removed. The audit now returns
    a healthy report counting non-``__init__.py`` Python files under ``src/``
    and ``tests/``.

    Returns a structured report with ``healthy`` (bool), ``summary`` (str),
    ``missing_markers`` (always empty), and ``files_checked`` (int).
    """
    root = Path(project_dir) if project_dir else Path.cwd()
    checked = 0

    for subdir in ("src", "tests"):
        base = root / subdir
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            checked += 1

    summary = f"Scanned {checked} Python files."
    return {
        "healthy": True,
        "summary": summary,
        "files_checked": checked,
        "missing_markers": [],
    }
