"""ALM Gate G4 — coverage delta over the touched surface.

After the model claims completion and before the ``StepTransaction``
commits, the coverage delta gate measures new-line coverage on the
touched Python files and cross-references the mutation-coverage delta
between parent and child snapshots.

- ``coverage_ratio = lines_new_covered / max(1, lines_new)``. Below
  ``tau_cov = 0.8`` rolls back with
  ``kind="coverage_delta_insufficient"``.
- ``mutation_coverage_delta = child_report.kill_rate - parent_report.
  kill_rate``. Below ``delta_mut = 0.1`` on a non-trivial change rolls
  back with the same kind.
- ``is_trivial_change`` bypasses the mutation-delta check. A change is
  trivial when its diff after normalization is whitespace / formatter-
  only, or when the added-line count is below a small floor. Details
  in ``_classify_triviality``.

Reference sources:

- ``coverage.py`` measurement library:
  ``https://coverage.readthedocs.io/``.
- ``pytest-cov`` runner: ``https://github.com/pytest-dev/pytest-cov``.
- ALM spec §3.4; §13 signal 4.

Design rationale in ``docs/ADRs/ADR-0020-antilazy-patchdiff-and-
coverage-delta.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ract.antilazy.mutation import MutationReport
    from ract.antilazy.patchdiff import Patch
    from ract.core.loop import WorkspaceSnapshot


DEFAULT_TAU_COV: float = 0.8
"""Coverage-ratio floor from ALM spec §3.4."""

DEFAULT_DELTA_MUT: float = 0.1
"""Mutation-coverage-delta floor for non-trivial changes."""

TRIVIAL_ADDED_LINE_FLOOR: int = 2
"""Under this many added lines a change is trivial by size alone.

Two lines is the outer bound of a one-off correction / typo fix that
does not warrant demanding meaningful new coverage.
"""


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageDeltaReport:
    """G4 result — per-touched-file coverage delta plus mutation delta."""

    touched_files: tuple[str, ...]
    lines_new: int
    lines_new_covered: int
    coverage_ratio: float
    tau_cov: float
    mutation_coverage_delta: float
    delta_mut: float
    is_trivial_change: bool
    non_python_files: tuple[str, ...] = field(default_factory=tuple)
    moved_lines: int = 0
    added_lines: int = 0

    def coverage_ok(self) -> bool:
        """True iff ``coverage_ratio >= tau_cov`` OR the change is trivial
        AND there are no new lines to cover.
        """
        if self.lines_new == 0 and self.is_trivial_change:
            return True
        return self.coverage_ratio >= self.tau_cov

    def mutation_ok(self) -> bool:
        """True iff the mutation-delta check passes.

        A trivial change bypasses the check. Otherwise the child's
        mutation coverage must exceed the parent's by ``delta_mut``.
        """
        if self.is_trivial_change:
            return True
        return self.mutation_coverage_delta >= self.delta_mut

    def passed(self) -> bool:
        return self.coverage_ok() and self.mutation_ok()

    def to_canonical(self) -> dict[str, object]:
        return {
            "touched_files": list(self.touched_files),
            "lines_new": self.lines_new,
            "lines_new_covered": self.lines_new_covered,
            "coverage_ratio": self.coverage_ratio,
            "tau_cov": self.tau_cov,
            "mutation_coverage_delta": self.mutation_coverage_delta,
            "delta_mut": self.delta_mut,
            "is_trivial_change": self.is_trivial_change,
            "non_python_files": list(self.non_python_files),
            "moved_lines": self.moved_lines,
            "added_lines": self.added_lines,
        }


# ---------------------------------------------------------------------------
# Triviality classification (lateral chain branch C flowed forward)
# ---------------------------------------------------------------------------


_WHITESPACE_ONLY = re.compile(r"^\s*$")
_COMMENT_ONLY = re.compile(r"^\s*#")


def _line_is_substantive(line: str) -> bool:
    """Return True iff ``line`` carries executable / declarative code.

    Blank lines and comment-only lines are formatter noise; a diff that
    consists entirely of them is a trivial change (per ADR-0020 the
    trivial-change bypass exists precisely for this shape, not to be
    a broad escape hatch).
    """
    if _WHITESPACE_ONLY.match(line):
        return False
    if _COMMENT_ONLY.match(line):
        return False
    return True


def _classify_triviality(
    added: tuple[str, ...], removed: tuple[str, ...]
) -> bool:
    """Return True when the (added, removed) pair is a trivial change.

    A change is trivial iff:

    - The count of substantive added lines is at or below
      ``TRIVIAL_ADDED_LINE_FLOOR``, AND
    - Every added line has a matching removed line up to whitespace
      normalization (a pure reformat), OR the substantive added-line
      count is zero.

    The Second Pass adversarial question 2 flags this determination
    as gameable — a mixed diff that adds a substantive change plus a
    long formatter-only section is not trivial by this rule because
    the substantive count exceeds the floor. Callers that want a
    stricter per-file rule can compose ``_classify_triviality`` per
    hunk. See module_02 Flagged gaps for the harder problem: a model
    that splits the transaction across steps so each step looks
    trivial. That is a cross-step attack the per-step gate cannot
    catch alone.
    """
    substantive_added = tuple(ln for ln in added if _line_is_substantive(ln))
    substantive_removed = tuple(ln for ln in removed if _line_is_substantive(ln))
    if len(substantive_added) > TRIVIAL_ADDED_LINE_FLOOR:
        return False
    if not substantive_added:
        return True
    # Whitespace-normalized match: every substantive added line has a
    # substantive removed line whose whitespace-collapsed form is equal.
    norm = lambda s: re.sub(r"\s+", " ", s.strip())  # noqa: E731
    removed_norms = [norm(ln) for ln in substantive_removed]
    for ln in substantive_added:
        if norm(ln) not in removed_norms:
            return False
    return True


# ---------------------------------------------------------------------------
# Line accounting — added vs moved (lateral chain branch C)
# ---------------------------------------------------------------------------


def _count_added_vs_moved(
    added: tuple[str, ...], removed: tuple[str, ...]
) -> tuple[int, int]:
    """Return ``(added_lines, moved_lines)`` for one hunk.

    A moved line appears in both ``added`` and ``removed`` (line-for-
    line equal). ``added_lines`` is the count of added lines that are
    not also in ``removed``. ``moved_lines`` is the intersection.
    """
    removed_multiset = list(removed)
    added_novel = 0
    moved = 0
    for line in added:
        if line in removed_multiset:
            moved += 1
            removed_multiset.remove(line)
        else:
            added_novel += 1
    return added_novel, moved


# ---------------------------------------------------------------------------
# Line-coverage runner
# ---------------------------------------------------------------------------


def _lines_in_snapshot(
    snapshot: "WorkspaceSnapshot", path: str
) -> tuple[str, ...]:
    """Return the lines of ``path`` in ``snapshot`` (or empty tuple)."""
    src = snapshot.files.get(path)
    if src is None:
        return ()
    return tuple(src.splitlines())


def _covered_line_numbers(
    snapshot: "WorkspaceSnapshot", path: str
) -> frozenset[int]:
    """Return the 1-indexed lines of ``path`` that ``snapshot`` marks covered.

    The workspace snapshot's ``metadata`` may carry a
    ``coverage.<path>`` entry produced by a prior ``coverage.py`` run
    (see ``pytest-cov`` invocation contract). Absent metadata means
    zero covered lines; the gate uses ``lines_new`` as the denominator
    so a snapshot without coverage produces a ratio of 0.
    """
    key = f"coverage.{path}"
    raw = snapshot.metadata.get(key)
    if raw is None:
        return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        try:
            return frozenset(int(n) for n in raw)
        except (TypeError, ValueError):
            return frozenset()
    return frozenset()


def _hunk_added_line_numbers(
    child: "WorkspaceSnapshot", path: str, added: tuple[str, ...]
) -> tuple[int, ...]:
    """Return 1-indexed line numbers in ``child`` matching ``added`` lines.

    Best-effort: for each added line find its first occurrence in the
    child snapshot. Duplicate matches consume separate positions so
    a repeated added line does not collapse into one covered position.
    """
    lines = _lines_in_snapshot(child, path)
    used: set[int] = set()
    positions: list[int] = []
    for target in added:
        for idx, line in enumerate(lines, start=1):
            if idx in used:
                continue
            if line == target:
                used.add(idx)
                positions.append(idx)
                break
    return tuple(positions)


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------


def run_coverage_delta(
    parent_snapshot: "WorkspaceSnapshot",
    child_snapshot: "WorkspaceSnapshot",
    patch: "Patch",
    mutation_report_parent: "MutationReport | None" = None,
    mutation_report_child: "MutationReport | None" = None,
    *,
    tau_cov: float = DEFAULT_TAU_COV,
    delta_mut: float = DEFAULT_DELTA_MUT,
) -> CoverageDeltaReport:
    """Return the ``CoverageDeltaReport`` for the transaction.

    Lateral chain branches folded in: (C) added vs moved distinction
    via per-hunk multiset intersection; (E) non-Python files are
    logged rather than gating (extension to Rust/TypeScript is v0.5
    backlog). See ADR-0020.
    """
    touched_all = list(patch.touched_files)
    python_files: list[str] = []
    non_python: list[str] = []
    for path in touched_all:
        if path.endswith(".py"):
            python_files.append(path)
        else:
            non_python.append(path)

    total_added = 0
    total_moved = 0
    lines_new_covered = 0
    all_added: list[str] = []
    all_removed: list[str] = []
    for hunk in patch.hunks:
        if hunk.path not in python_files:
            continue
        added_novel, moved = _count_added_vs_moved(
            hunk.added_lines, hunk.removed_lines
        )
        total_added += added_novel
        total_moved += moved
        all_added.extend(hunk.added_lines)
        all_removed.extend(hunk.removed_lines)
        # Determine which added-line positions the child snapshot marks
        # covered. Only novel added lines count — a moved line is
        # already covered on the parent side by assumption.
        novel_lines = _novel_added(hunk.added_lines, hunk.removed_lines)
        positions = _hunk_added_line_numbers(
            child_snapshot, hunk.path, novel_lines
        )
        covered = _covered_line_numbers(child_snapshot, hunk.path)
        for pos in positions:
            if pos in covered:
                lines_new_covered += 1

    lines_new = total_added
    coverage_ratio = (
        (lines_new_covered / lines_new) if lines_new > 0 else 1.0
    )

    is_trivial = _classify_triviality(tuple(all_added), tuple(all_removed))

    mutation_delta = 0.0
    if mutation_report_child is not None and mutation_report_parent is not None:
        mutation_delta = (
            mutation_report_child.kill_rate - mutation_report_parent.kill_rate
        )
    elif mutation_report_child is not None:
        mutation_delta = mutation_report_child.kill_rate

    report = CoverageDeltaReport(
        touched_files=tuple(touched_all),
        lines_new=lines_new,
        lines_new_covered=lines_new_covered,
        coverage_ratio=coverage_ratio,
        tau_cov=tau_cov,
        mutation_coverage_delta=mutation_delta,
        delta_mut=delta_mut,
        is_trivial_change=is_trivial,
        non_python_files=tuple(non_python),
        moved_lines=total_moved,
        added_lines=total_added,
    )
    # Emit predicate.evaluated for the trace channel.
    try:  # local import breaks the trace→antilazy cycle
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "predicate.evaluated",
            {
                "kind": "coverage_delta",
                "touched_files": list(report.touched_files),
                "lines_new": report.lines_new,
                "lines_new_covered": report.lines_new_covered,
                "coverage_ratio": report.coverage_ratio,
                "tau_cov": report.tau_cov,
                "mutation_coverage_delta": report.mutation_coverage_delta,
                "delta_mut": report.delta_mut,
                "is_trivial_change": report.is_trivial_change,
                "ok": report.passed(),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return report


def _novel_added(
    added: tuple[str, ...], removed: tuple[str, ...]
) -> tuple[str, ...]:
    """Return the subset of ``added`` that are not moved (present in
    ``removed``)."""
    removed_multiset = list(removed)
    novel: list[str] = []
    for line in added:
        if line in removed_multiset:
            removed_multiset.remove(line)
            continue
        novel.append(line)
    return tuple(novel)


# ---------------------------------------------------------------------------
# On-disk snapshot writer for evals/runs/<run_id>/coverage_delta.json
# ---------------------------------------------------------------------------


def write_coverage_delta_snapshot(
    run_dir: Path, report: CoverageDeltaReport
) -> Path:
    """Persist the report to ``<run_dir>/coverage_delta.json`` and return the path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "coverage_delta.json"
    path.write_text(
        json.dumps(report.to_canonical(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


# RACT 0.4.0
