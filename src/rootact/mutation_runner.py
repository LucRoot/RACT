# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Mutation-testing runner for RACT.

mutmut does not run natively on Windows, so the project ships a WSL fallback
script. This module wraps that script (or any mutmut-compatible runner),
executes it, and parses ``mutmut results`` output into a structured report.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rootact.rooted import Rooted


@dataclass(frozen=True)
class MutationReport:
    """Structured result from a mutmut run."""

    killed: int
    survived: int
    timeout: int
    error: int

    @property
    def total(self) -> int:
        return self.killed + self.survived + self.timeout + self.error

    @property
    def mutation_score(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.killed / self.total * 100, 2)

    def __str__(self) -> str:
        return (
            f"mutation score: {self.mutation_score:.1f}% "
            f"({self.killed}/{self.total} killed, "
            f"{self.survived} survived, {self.timeout} timeout, {self.error} error)"
        )


def _parse_mutmut_results(text: str) -> MutationReport | None:
    """Parse ``mutmut results`` text into a MutationReport.

    The parser is intentionally tolerant: it looks for category lines such as
    ``Survived 🙁 (5)`` and falls back to zero for any missing category.
    """
    killed = 0
    survived = 0
    timeout = 0
    error_count = 0

    # Match lines like "Survived 🙁 (5)" or "Killed 😎 (45)" or "Timed out ⏰ (0)".
    # Also accept "Error" variants that older mutmut versions emit.
    category_pattern = re.compile(
        r"^(Survived|Killed|Timed out|Errors?)\b.*?\((\d+)\)",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in category_pattern.finditer(text):
        category = match.group(1).lower()
        count = int(match.group(2))
        if category == "killed":
            killed = count
        elif category == "survived":
            survived = count
        elif category.startswith("timed"):
            timeout = count
        elif category.startswith("error"):
            error_count = count

    if killed == survived == timeout == error_count == 0:
        # mutmut sometimes emits "All mutations are killed! ✔" with no table.
        if re.search(r"all mutations are killed", text, re.IGNORECASE):
            return MutationReport(killed=1, survived=0, timeout=0, error=0)
        return None

    return MutationReport(
        killed=killed,
        survived=survived,
        timeout=timeout,
        error=error_count,
    )


def _default_script_path(project_dir: Path) -> Path:
    return project_dir / "scripts" / "run_mutation_tests_wsl.sh"


def _detect_wsl_distro() -> str | None:
    """Return a running Linux distro name, or None if detection fails.

    The default WSL distro may be Docker Desktop or another non-Linux
    appliance. This function prefers an explicitly configured distro via the
    ``RACT_WSL_DISTRO`` environment variable, then scans ``wsl -l --running``
    for a Linux distro, and finally returns None so the caller can fall back
    to ``wsl -e bash``.
    """
    env_distro = os.environ.get("RACT_WSL_DISTRO")
    if env_distro:
        return env_distro
    try:
        result = subprocess.run(
            ["wsl", "-l", "--running"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    # wsl -l output uses OEM code page and may contain trailing nulls/whitespace.
    for line in result.stdout.splitlines():
        line = line.strip().rstrip("\x00")
        if not line or line.startswith("NAME"):
            continue
        # Default marker is an asterisk prefix, e.g. "* Ubuntu-24.04".
        distro = (
            line.lstrip("* ").split()[0]
            if line.lstrip().startswith("*")
            else line.split()[0]
        )
        if distro and distro not in {"docker-desktop", "docker-desktop-data"}:
            return distro
    return None


def _to_wsl_path(path: Path) -> str:
    """Convert a Windows path to a WSL ``/mnt/<drive>/...`` path.

    WSL bash cannot interpret backslash-separated Windows paths. This helper
    maps ``C:\\foo\\bar`` to ``/mnt/c/foo/bar`` so scripts can be invoked
    directly inside WSL.
    """
    drive = path.drive
    if drive and len(drive) == 2 and drive[1] == ":":
        drive_letter = drive[0].lower()
        rest = path.as_posix().split("/", 1)[1] if "/" in path.as_posix() else ""
        if rest:
            return f"/mnt/{drive_letter}/{rest}"
        return f"/mnt/{drive_letter}"
    return path.as_posix()


def _resolve_runner_command(
    script_path: Path, *, wsl_distro: str | None = None
) -> list[str]:
    """Return the command to execute the mutation script on this platform."""
    if sys.platform == "win32":
        distro = wsl_distro or _detect_wsl_distro()
        wsl_script = _to_wsl_path(script_path)
        if distro:
            return ["wsl", "-d", distro, "-e", "bash", wsl_script]
        return ["wsl", "-e", "bash", wsl_script]
    return ["bash", str(script_path)]


def run_mutation_tests(
    project_dir: Path | str,
    *,
    script_path: Path | str | None = None,
    timeout: float = 900.0,
    wsl_distro: str | None = None,
) -> Rooted[MutationReport]:
    """Run the mutation-testing script and return a parsed report.

    On Windows the script is invoked through WSL; elsewhere it runs under
    ``bash``. Callers who want a different runner can pass a custom script.
    """
    project_dir = Path(project_dir)
    script = Path(script_path) if script_path else _default_script_path(project_dir)
    if not script.is_file():
        return Rooted(
            value=None,
            assumption=f"Mutation script exists: {script}",
            confidence=0.0,
            provenance=["mutation_runner.run_mutation_tests"],
            error=f"Mutation script not found: {script}",
        )

    cmd = _resolve_runner_command(script, wsl_distro=wsl_distro)
    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Rooted(
            value=None,
            assumption="Mutation test run completes within timeout.",
            confidence=0.0,
            provenance=["mutation_runner.run_mutation_tests"],
            error="Mutation testing timed out.",
        )
    except FileNotFoundError as exc:
        return Rooted(
            value=None,
            assumption="Mutation runner executable is available.",
            confidence=0.0,
            provenance=["mutation_runner.run_mutation_tests"],
            error=f"Mutation runner not found: {exc}",
        )

    combined = result.stdout + "\n" + result.stderr
    report = _parse_mutmut_results(combined)
    if report is None:
        stdout_tail = result.stdout[-500:] if result.stdout else ""
        stderr_tail = result.stderr[-500:] if result.stderr else ""
        return Rooted(
            value=None,
            assumption="mutmut results output contains parseable counts.",
            confidence=0.0,
            provenance=["mutation_runner.run_mutation_tests"],
            error=(
                f"Could not parse mutmut results.\n"
                f"exit code: {result.returncode}\n"
                f"stdout tail: {stdout_tail}\n"
                f"stderr tail: {stderr_tail}"
            ),
        )

    return Rooted(
        value=report,
        assumption="Mutation test output parsed successfully.",
        confidence=1.0,
        provenance=["mutation_runner.run_mutation_tests"],
    )


# RACT 0.1.0 - Initial Public Release
