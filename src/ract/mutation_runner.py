from __future__ import annotations


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

from ract.rooted import Rooted


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
            ["wsl", "-l", "--running", "--quiet"],
            capture_output=True,
            timeout=10.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        print(f"[mutation] WSL distributions were not listed: {exc}", flush=True)
        return None
    for distro in wsl_distributions(result.stdout):
        if distro not in {"docker-desktop", "docker-desktop-data"}:
            return distro
    return None


def wsl_distributions(out: bytes | str) -> list[str]:
    """The names in ``wsl -l`` output (B-231).

    LR:: ``wsl.exe`` writes UTF-16LE (a NUL after every ASCII character) and,
    without ``--quiet``, a header line ("Windows Subsystem for Linux
    Distributions:"). Read as text, the header was taken for a distribution
    and passed to ``wsl -d``. Decoded as ``other_backends._text`` does it; the
    header, blank lines and the default marker (``*`` or ``(Default)``) are
    dropped.
    """
    from ract.security.other_backends import _text

    names: list[str] = []
    for line in _text(out).splitlines():
        line = line.strip().strip("\x00").strip()
        if not line or line.endswith(":") or line.upper().startswith("NAME"):
            continue
        line = line.lstrip("*").strip()
        line = line.replace("(Default)", "").strip()
        if line:
            names.append(line.split()[0])
    return names


def _to_wsl_path(path: Path) -> str:
    """Convert a Windows path to a WSL ``/mnt/<drive>/...`` path.

    WSL bash cannot interpret backslash-separated Windows paths. This helper
    maps ``C:\\foo\\bar`` to ``/mnt/c/foo/bar`` so scripts can be invoked
    directly inside WSL.

    It works even when ``pathlib`` is running on a POSIX host and therefore
    does not parse Windows drive letters natively.
    """
    # Normalize backslashes first; POSIX pathlib may treat them as literal chars.
    posix = str(path).replace("\\", "/")
    # B-231: an extended-length path (\\?\C:\...) is a drive path with a prefix;
    # a network path (\\server\share) has no /mnt form, so it is refused.
    if posix.startswith(("//?/", "//./")):
        posix = posix[4:]
        if posix.upper().startswith("UNC/"):
            posix = "//" + posix[4:]
    if posix.startswith("//"):
        raise ValueError(
            f"{path} is a network path, and WSL has no /mnt form for it; "
            "run the mutation tests from a drive letter path"
        )
    if posix.startswith("/"):
        return posix
    # Drive-letter form: X:/... or X:\... (after normalization).
    if len(posix) >= 2 and posix[1] == ":" and posix[0].isalpha():
        drive_letter = posix[0].lower()
        rest = posix[2:].lstrip("/")
        if rest:
            return f"/mnt/{drive_letter}/{rest}"
        return f"/mnt/{drive_letter}"
    return posix


def _resolve_runner_command(
    script_path: Path, *, wsl_distro: str | None = None
) -> list[str]:
    """Return the command to execute the mutation script on this platform."""
    if sys.platform == "win32":
        distro = wsl_distro or _detect_wsl_distro()
        wsl_script = _to_wsl_path(script_path)
        if not distro:
            # B-231: an empty or unreadable list is no reason to guess.
            raise ValueError(
                "WSL lists no running Linux distribution; start one, or name it "
                "in RACT_WSL_DISTRO"
            )
        return ["wsl", "-d", distro, "-e", "bash", wsl_script]
    return ["bash", str(script_path)]


def run_mutation_tests(
    project_dir: Path | str,
    *,
    script_path: Path | str | None = None,
    timeout: float = 7200.0,
    wsl_distro: str | None = None,
    targets: list[str] | None = None,
    test_runner: str | None = None,
) -> Rooted[MutationReport]:
    """Run the mutation-testing script and return a parsed report.

    On Windows the script is invoked through WSL; elsewhere it runs under
    ``bash``. Callers who want a different runner can pass a custom script.

    ``targets`` restricts mutation to a specific list of source paths and is
    passed to the script via ``RACT_MUTATION_TARGETS``. ``test_runner``
    overrides the test command via ``RACT_TEST_RUNNER``. These are used by
    per-file mutation floors in the harness.
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

    try:
        cmd = _resolve_runner_command(script, wsl_distro=wsl_distro)
    except ValueError as exc:
        return Rooted(
            value=None,
            assumption="The mutation runner can start.",
            confidence=0.0,
            provenance=["mutation_runner.run_mutation_tests"],
            error=str(exc),
        )
    env = os.environ.copy()
    if targets:
        env["RACT_MUTATION_TARGETS"] = ",".join(targets)
    if test_runner:
        env["RACT_TEST_RUNNER"] = test_runner
    if sys.platform == "win32":
        # B-231: a Windows variable reaches WSL only when WSLENV names it. The
        # targets are paths relative to the project and the runner is a
        # command, so neither takes the /p path flag.
        names = [n for n in ("RACT_MUTATION_TARGETS", "RACT_TEST_RUNNER") if n in env]
        if names:
            kept = [n for n in env.get("WSLENV", "").split(":") if n]
            env["WSLENV"] = ":".join(dict.fromkeys([*kept, *names]))
    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
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

    combined = (result.stdout or "") + "\n" + (result.stderr or "")
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


# RACT 0.1.1 - Trust and tooling
