from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from dataclasses import dataclass, replace


from rootact.executor import ExecutionReport
from rootact.artifact_diff_wiring import (
    _files_from_report,
    render_change_summary,
    render_file_diff,
)

_ROOT_KNOT = object()


@dataclass
class DiffExtension:
    """
    Utility class that attaches diff summaries and file-level diffs to an ExecutionReport.
    It uses the wiring layer to generate human-readable change descriptions without mutating shared state.
    """

    def attach_diff_summary(self, report: ExecutionReport) -> ExecutionReport:
        """
        Return a new ExecutionReport with ``change_summary`` and ``file_diff`` stored in ``artifacts``.
        If the report contains no step results, both fields are set to indicate "no changes".
        """
        new_files = _files_from_report(report)
        change_summary = render_change_summary(report)
        file_diff = render_file_diff({}, new_files)

        enriched_artifacts = dict(report.artifacts)
        enriched_artifacts["change_summary"] = change_summary
        enriched_artifacts["file_diff"] = file_diff

        return replace(report, artifacts=enriched_artifacts)


# RACT 0.1.0 - Initial Public Release
