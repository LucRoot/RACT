# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Chesterton's Fence subagent for RACT.

Before removing or bypassing a legacy pattern, the subagent reads the file,
recent commits, and (optionally) blame for the target lines, then produces a
plausible reason the pattern exists. If it cannot find one, the change is
flagged for operator review.

LR:: This is the anti-rot guard against "AI cleans up load-bearing weirdness."
The fence does not veto changes; it makes uninformed changes expensive.
"""

import subprocess
from pathlib import Path
from typing import Any

from rootact.providers.base import ProviderAdapter
from rootact.rooted import Rooted


class ChestertonsFence:
    """Produce a plausible reason legacy code exists before it is changed."""

    def __init__(
        self,
        project_dir: Path | str,
        provider: ProviderAdapter,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.provider = provider
        self.config = config or {}

    def _run_git(self, *args: str) -> str:
        """Run a git command in the project directory and return stdout."""
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""
        if proc.returncode != 0:
            return ""
        return proc.stdout

    def _relative_path(self, path: Path) -> Path:
        """Return *path* relative to the project directory.

        Accepts both absolute and project-relative paths.
        """
        if not path.is_absolute():
            path = self.project_dir / path
        return path.relative_to(self.project_dir)

    def _recent_commits(self, path: Path) -> list[str]:
        """Return recent commit messages for *path*."""
        rel = self._relative_path(path)
        output = self._run_git("log", "-n10", "--pretty=format:%h %s", "--", str(rel))
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _blame(self, path: Path, lines: tuple[int, int] | None) -> list[str]:
        """Return blame lines for the requested range, or the whole file."""
        rel = self._relative_path(path)
        args = ["blame", "--date=short", "-l"]
        if lines is not None:
            args.append(f"-L{lines[0]},{lines[1]}")
        args.extend(["--", str(rel)])
        output = self._run_git(*args)
        return [line.strip() for line in output.splitlines() if line.strip()]

    def inspect(
        self, path: Path | str, lines: tuple[int, int] | None = None
    ) -> Rooted[str]:
        """Return a plausible reason the code at *path* exists."""
        target = Path(path)
        if not target.is_absolute():
            target = self.project_dir / target
        if not target.is_file():
            return Rooted(
                value="",
                assumption="Target file exists.",
                confidence=0.0,
                provenance=["chestertons_fence.inspect"],
                error=f"File not found: {target}",
            )

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return Rooted(
                value="",
                assumption="Target file is readable.",
                confidence=0.0,
                provenance=["chestertons_fence.inspect"],
                error=f"Failed to read {target}: {exc}",
            )

        content_lines = content.splitlines()
        if lines is not None:
            start, end = lines
            excerpt_lines = content_lines[start - 1 : end]
            excerpt = "\n".join(excerpt_lines)
        else:
            excerpt = "\n".join(content_lines[:50])

        commits = self._recent_commits(target)
        blame = self._blame(target, lines)

        evidence = "\n".join(
            [
                f"File: {target.relative_to(self.project_dir)}",
                f"Lines requested: {lines if lines else 'whole file (first 50 lines)'}",
                "",
                "Excerpt:",
                excerpt,
                "",
                "Recent commits:",
                "\n".join(commits) if commits else "(no git history available)",
                "",
                "Blame for requested lines:",
                "\n".join(blame[:20]) if blame else "(no blame available)",
            ]
        )

        prompt = (
            "You are Chesterton's Fence, a subagent that defends legacy code "
            "from uninformed removal. Given the file excerpt, recent commits, "
            "and blame below, write one concise paragraph giving the most "
            "plausible reason the code exists. If you cannot find a plausible "
            "reason, reply exactly with: no plausible reason found.\n\n"
            f"{evidence}"
        )

        try:
            result = self.provider.complete(
                [{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.4,
            )
        except Exception as exc:  # noqa: BLE001
            return Rooted(
                value="",
                assumption="Provider call for Chesterton's Fence succeeds.",
                confidence=0.0,
                provenance=["chestertons_fence.inspect"],
                error=f"Fence provider call failed: {exc}",
            )

        if not result.is_ok():
            return Rooted(
                value="",
                assumption="Provider call for Chesterton's Fence succeeds.",
                confidence=0.0,
                provenance=["chestertons_fence.inspect"],
                error=f"Fence provider call failed: {result.error}",
            )

        content_response = (
            result.unwrap()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content_response:
            return Rooted(
                value="",
                assumption="Provider returned a non-empty fence brief.",
                confidence=0.0,
                provenance=["chestertons_fence.inspect"],
                error="Fence received empty response from provider.",
            )

        low_confidence = "no plausible reason found" in content_response.lower()
        return Rooted(
            value=content_response,
            assumption="Provider returned a plausible reason or an explicit lack of one.",
            confidence=0.3 if low_confidence else 0.8,
            provenance=[
                "chestertons_fence.inspect",
                f"provider:{self.provider.name}",
            ],
            error=(content_response if low_confidence else None),
        )


# RACT 0.1.1 - Trust and tooling
