# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Wiring module that exposes diff and summary rendering for ExecutionReports.

RootAct already ships DiffViewer and ChangeSummary utilities. This module
connects them to the Executor's ExecutionReport so callers can review what
changed after a plan run without importing multiple modules themselves.
"""

from rootact.artifact_diff_viewer import DiffViewer
from rootact.change_summary_generator import ChangeSummary
from rootact.executor import ExecutionReport


def render_change_summary(report: ExecutionReport) -> str:
    """Return a concise summary of the artifacts produced by ``report``."""
    new_files = _files_from_report(report)
    return ChangeSummary(old={}, new=new_files).summarize()


def render_file_diff(old_files: dict[str, str], new_files: dict[str, str]) -> str:
    """Return a line-level diff between two file snapshots."""
    return DiffViewer(old_files, new_files).render()


def _files_from_report(report: ExecutionReport) -> dict[str, str]:
    """Extract expected artifact names and their generated content."""
    files: dict[str, str] = {}
    for result in report.step_results:
        files[result.step.expected_artifact] = result.content
    return files


# RACT 0.1.1 - Trust and tooling
