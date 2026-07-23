from __future__ import annotations


"""Project health/status dashboard helpers."""

from pathlib import Path
from typing import Any


def run_status(project_path: Path | None = None) -> dict[str, Any]:
    """Return a structured health check dict for a RACT project."""
    project_dir = Path(project_path) if project_path else Path.cwd()
    config_path = project_dir / "ract.yaml"
    py_files = list(project_dir.glob("*.py")) if project_dir.is_dir() else []

    checks: list[dict[str, Any]] = [
        {
            "name": "config_present",
            "passed": config_path.exists(),
            "detail": "ract.yaml found"
            if config_path.exists()
            else "ract.yaml missing",
        },
        {
            "name": "python_sources",
            "passed": len(py_files) > 0,
            "detail": f"{len(py_files)} Python file(s) in project directory",
        },
        {
            "name": "project_dir_readable",
            "passed": project_dir.is_dir(),
            "detail": f"project directory: {project_dir}",
        },
    ]

    healthy = all(c["passed"] for c in checks)
    summary = "All checks passed" if healthy else "Some checks failed"

    return {
        "healthy": healthy,
        "summary": summary,
        "checks": checks,
    }
