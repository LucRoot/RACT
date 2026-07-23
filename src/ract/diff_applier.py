from __future__ import annotations


"""DiffApplier — applies unified-diff hunks to existing files.

Whole-file rewrite is fine for scaffolding, but iterating on large files needs
surgical edits. DiffApplier takes model-generated unified diff hunks and applies
them to existing files, with a rollback snapshot before each apply.

LR:: Existing content is preserved by reading the original file and applying the
diff; only the requested hunks change.
"""

import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiffApplyResult:
    """Result of applying a diff hunk."""

    path: Path
    applied: bool
    backup: Path | None
    message: str


class DiffApplier:
    """Apply unified-diff hunks to files with optional rollback snapshots."""

    def __init__(
        self, project_dir: Path | str, snapshot_dir: Path | str | None = None
    ) -> None:
        self.project_dir = Path(project_dir)
        self.snapshot_dir = (
            Path(snapshot_dir)
            if snapshot_dir
            else self.project_dir / ".ract" / "diff_snapshots"
        )

    def _backup_path(self, target: Path) -> Path:
        """Return a unique backup path for *target*."""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        stem = target.name
        counter = 0
        while True:
            suffix = f".{counter}" if counter else ""
            candidate = self.snapshot_dir / f"{stem}{suffix}.bak"
            if not candidate.exists():
                return candidate
            counter += 1

    def _parse_hunk(self, hunk_lines: list[str]) -> tuple[int, list[tuple[str, str]]]:
        """Parse a unified-diff hunk and return (start_line, operations).

        Lines are 0-indexed. The hunk header looks like:
          @@ -l,s +l,s @@

        Each operation is a tuple of (op, text) where op is one of:
          ' ' context line, '-' removed line, '+' added line.
        """
        header = hunk_lines[0]
        match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
        if not match:
            raise ValueError(f"Invalid hunk header: {header}")
        start = int(match.group(2)) - 1

        ops: list[tuple[str, str]] = []
        for line in hunk_lines[1:]:
            if line.startswith("\\"):
                # "\ No newline at end of file" — ignore
                continue
            if line.startswith((" ", "-", "+")):
                ops.append((line[0], line[1:]))
            else:
                # Treat unexpected bare lines as context.
                ops.append((" ", line))
        return start, ops

    def apply_diff(self, diff_text: str) -> list[DiffApplyResult]:
        """Apply all hunks in *diff_text* and return per-file results."""
        results: list[DiffApplyResult] = []
        current_file: Path | None = None
        current_hunk: list[str] = []

        def flush_hunk() -> None:
            nonlocal current_hunk
            if current_file is not None and current_hunk:
                results.append(self._apply_hunk(current_file, current_hunk))
                current_hunk = []

        for raw_line in diff_text.splitlines():
            if raw_line.startswith("--- ") or raw_line.startswith("+++ "):
                flush_hunk()
                # Git-style headers prefix the old path with "a/" and the new
                # path with "b/"; strip those prefixes so the project-relative
                # path resolves correctly.
                if raw_line.startswith("--- "):
                    stripped = raw_line[4:].strip().removeprefix("a/")
                    current_file = self.project_dir / stripped
                elif raw_line.startswith("+++ "):
                    stripped = raw_line[4:].strip().removeprefix("b/")
                    current_file = self.project_dir / stripped
                continue
            if raw_line.startswith("diff --git") or raw_line.startswith("index "):
                flush_hunk()
                # Extract file path from "diff --git a/... b/..." or use next +++ line.
                match = re.search(r"diff --git a/(.+?) b/(.+?)$", raw_line)
                if match:
                    current_file = self.project_dir / match.group(2)
                continue
            if raw_line.startswith("@@"):
                if current_hunk:
                    flush_hunk()
                current_hunk.append(raw_line)
            elif current_hunk:
                current_hunk.append(raw_line)
        flush_hunk()
        return results

    def _apply_hunk(self, target: Path, hunk: list[str]) -> DiffApplyResult:
        """Apply a single hunk to *target* after verifying context."""
        if not target.is_file():
            return DiffApplyResult(
                path=target,
                applied=False,
                backup=None,
                message="Target file does not exist.",
            )
        try:
            start, ops = self._parse_hunk(hunk)
        except ValueError as exc:
            return DiffApplyResult(
                path=target,
                applied=False,
                backup=None,
                message=str(exc),
            )

        original_bytes = target.read_bytes()
        original_text = original_bytes.decode("utf-8")
        # Detect the file's newline convention so we preserve it exactly.
        newline = "\r\n" if b"\r\n" in original_bytes else "\n"
        original_lines = original_text.splitlines()

        # The original-file slice that this hunk expects to overwrite is made up
        # of context lines and removed lines, in order.
        expected_orig = [text for op, text in ops if op in (" ", "-")]
        if original_lines[start : start + len(expected_orig)] != expected_orig:
            return DiffApplyResult(
                path=target,
                applied=False,
                backup=None,
                message="Hunk context does not match target file.",
            )

        new_segment = [text for op, text in ops if op in (" ", "+")]
        merged = (
            original_lines[:start]
            + new_segment
            + original_lines[start + len(expected_orig) :]
        )
        merged_text = newline.join(merged)
        # Preserve the original file's trailing-newline convention so the diff
        # does not silently rewrite EOF when it is not supposed to.
        if original_text.endswith(newline):
            merged_text += newline

        backup = self._backup_path(target)
        shutil.copy2(target, backup)
        # Write without newline translation so the detected convention survives.
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(merged_text)

        return DiffApplyResult(
            path=target,
            applied=True,
            backup=backup,
            message="Hunk applied successfully.",
        )

    def restore(self, backup: Path, target: Path) -> bool:
        """Restore *target* from *backup*."""
        if not backup.is_file():
            return False
        shutil.copy2(backup, target)
        return True


# RACT 0.1.1 - Trust and tooling
