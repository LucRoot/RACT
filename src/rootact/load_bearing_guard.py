# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Load-bearing weirdness guard.

Senior engineers know that some code looks wrong but is correct. The
``# load-bearing:`` annotation lets them mark those blocks so RACT refuses to
refactor or delete them without explicit override. This is institutional memory
codified in-line and machine-readable.

LR:: A load-bearing annotation is not a general "do not touch" flag. It is a
receipt that says "this pattern has been considered and judged load-bearing."
Without the reason, the guard should not be satisfied.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_LOAD_BEARING_RE = re.compile(r"^\s*#\s*load-bearing:\s*(?P<reason>.+)$")
_BLOCK_START_RE = re.compile(r"^\s*(def |class |async def |if __name__)")


@dataclass(frozen=True)
class LoadBearingRegion:
    """A protected region in a source file."""

    path: str
    start_line: int  # 1-based, inclusive
    end_line: int  # 1-based, inclusive
    reason: str
    annotation_line: int  # 1-based


@dataclass(frozen=True)
class LoadBearingViolation:
    """A modification that touches a load-bearing region."""

    path: str
    region: LoadBearingRegion
    modified_lines: list[int]


class LoadBearingGuard:
    """Scan files for ``# load-bearing:`` annotations and protect the blocks."""

    def __init__(self, project_dir: Path | str) -> None:
        self.project_dir = Path(project_dir)

    def scan_file(self, path: Path | str) -> list[LoadBearingRegion]:
        """Return all protected regions in *path*.

        A ``# load-bearing: <reason>`` comment marks the next block (function or
        class definition, or an ``if __name__ == "__main__":`` guard) as
        protected. The region extends from the annotation through the end of the
        indented block. If no block follows on a subsequent line, the annotation
        protects only itself.
        """
        target = Path(path)
        if not target.is_file():
            return []
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        regions: list[LoadBearingRegion] = []
        i = 0
        while i < len(lines):
            match = _LOAD_BEARING_RE.match(lines[i])
            if match:
                reason = match.group("reason").strip()
                annotation_line = i + 1
                block_start = self._find_block_start(lines, i + 1)
                if block_start is None:
                    # No following block; protect the annotation line only.
                    regions.append(
                        LoadBearingRegion(
                            path=str(target),
                            start_line=annotation_line,
                            end_line=annotation_line,
                            reason=reason,
                            annotation_line=annotation_line,
                        )
                    )
                    i += 1
                    continue
                block_end = self._find_block_end(lines, block_start)
                regions.append(
                    LoadBearingRegion(
                        path=str(target),
                        start_line=annotation_line,
                        end_line=block_end,
                        reason=reason,
                        annotation_line=annotation_line,
                    )
                )
                i = block_end
                continue
            i += 1
        return regions

    @staticmethod
    def _find_block_start(lines: list[str], start_index: int) -> int | None:
        """Return the 1-based line number of the block following *start_index*."""
        for idx in range(start_index, len(lines)):
            if _BLOCK_START_RE.match(lines[idx]):
                return idx + 1
        return None

    @staticmethod
    def _find_block_end(lines: list[str], block_start: int) -> int:
        """Return the 1-based last line of the indented block starting at *block_start*."""
        # block_start is 1-based.
        base_idx = block_start - 1
        if base_idx >= len(lines):
            return block_start
        base_indent = len(lines[base_idx]) - len(lines[base_idx].lstrip())
        end = block_start
        for idx in range(block_start, len(lines)):
            line = lines[idx]
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent and not line.strip().startswith(
                ("#", '"""', "'''")
            ):
                break
            end = idx + 1
        return end

    def check_modification(
        self,
        relative_path: str,
        old_text: str,
        new_text: str,
    ) -> list[LoadBearingViolation]:
        """Return violations if *new_text* modifies any load-bearing region.

        The comparison is line-oriented: a violation occurs when any line inside a
        protected region differs between *old_text* and *new_text*. Lines that are
        purely whitespace or comments are ignored unless the comment itself is the
        load-bearing annotation.
        """
        target = self.project_dir / relative_path
        regions = self.scan_file(target)
        if not regions:
            return []

        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()

        violations: list[LoadBearingViolation] = []
        for region in regions:
            modified: list[int] = []
            for line_no in range(region.start_line, region.end_line + 1):
                old_line = old_lines[line_no - 1] if line_no <= len(old_lines) else ""
                new_line = new_lines[line_no - 1] if line_no <= len(new_lines) else ""
                if old_line != new_line:
                    modified.append(line_no)
            if modified:
                violations.append(
                    LoadBearingViolation(
                        path=relative_path,
                        region=region,
                        modified_lines=modified,
                    )
                )
        return violations

    def scan_project(self) -> dict[str, list[LoadBearingRegion]]:
        """Return a mapping of relative path -> regions for the whole project."""
        result: dict[str, list[LoadBearingRegion]] = {}
        if not self.project_dir.is_dir():
            return result
        for path in self.project_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                rel = str(path.relative_to(self.project_dir))
            except ValueError:
                continue
            regions = self.scan_file(path)
            if regions:
                result[rel] = regions
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize the project scan as a JSON-friendly dict."""
        return {
            rel: [
                {
                    "path": r.path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "reason": r.reason,
                    "annotation_line": r.annotation_line,
                }
                for r in regions
            ]
            for rel, regions in self.scan_project().items()
        }
