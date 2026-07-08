# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import List

from rootact.manager import Plan, Step


@dataclass
class GitMode:
    _enabled: bool = False

    def enable(self) -> None:
        """Enable Git mode."""
        self._enabled = True

    def disable(self) -> None:
        """Disable Git mode."""
        self._enabled = False

    def is_enabled(self) -> bool:
        """Return whether Git mode is enabled."""
        return self._enabled

    def stage(self, paths: List[str]) -> Plan:
        """Stage files and return a Plan describing the action."""
        if not self._enabled:
            raise RuntimeError("Git mode is not enabled")
        return Plan(
            assumption="Stage files for commit",
            confidence=0.95,
            steps=[
                Step(
                    action="git add",
                    provider_hint="subprocess",
                    expected_artifact="staged files",
                )
            ],
        )

    def commit(self, message: str = "Automated commit") -> Plan:
        """Commit staged changes with a message and return a Plan."""
        if not self._enabled:
            raise RuntimeError("Git mode is not enabled")
        return Plan(
            assumption=f"Commit with message: {message}",
            confidence=0.97,
            steps=[
                Step(
                    action="git commit",
                    provider_hint="subprocess",
                    expected_artifact="commit",
                )
            ],
        )

    def _run_git(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run a git command and return the completed process."""
        return subprocess.run(args, capture_output=True, text=True)

    def commit_files(
        self,
        paths: List[str],
        message: str = "Automated commit by RootAct",
    ) -> subprocess.CompletedProcess:
        """Stage *paths* and commit them with *message*.

        Raises RuntimeError if git mode is not enabled, if no paths are provided,
        or if the commit fails.
        """
        if not self._enabled:
            raise RuntimeError("Git mode is not enabled")
        if not paths:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="No paths provided; nothing to commit."
            )

        existing = [p for p in paths if Path(p).exists()]
        if not existing:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"None of {len(paths)} path(s) exist; nothing to commit.",
            )

        self._run_git(["git", "add", *existing])
        commit_result = self._run_git(["git", "commit", "-m", message, *existing])
        if commit_result.returncode != 0:
            self._run_git(["git", "reset", "HEAD", *existing])
            raise RuntimeError(
                f"Git commit failed: {commit_result.stderr or commit_result.stdout}"
            )
        return commit_result


# RACT 0.1.0 - Initial Public Release
