# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Run reporter — renders the last loop or session report for human review.

After a loop finishes, users need a structured summary of what changed, which
milestones completed, and which handshakes are pending. The reporter reads the
persisted JSON artifacts and prints them in a readable format.
"""

import json
from pathlib import Path
from typing import Any


class RunReporter:
    """Render the most recent RACT run report."""

    def __init__(self, project_dir: Path | str) -> None:
        self.project_dir = Path(project_dir)

    def _load_loop_report(self) -> dict[str, Any] | None:
        path = self.project_dir / ".rootact" / "loop_report.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _load_session_report(self, session_id: str) -> dict[str, Any] | None:
        path = self.project_dir / ".rootact" / "sessions" / f"{session_id}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _latest_session_id(self) -> str | None:
        """Return the most recently modified session id, or None if none exist."""
        sessions_dir = self.project_dir / ".rootact" / "sessions"
        if not sessions_dir.is_dir():
            return None
        candidates = [
            (path.stat().st_mtime, path.stem)
            for path in sessions_dir.glob("*.json")
            if path.is_file()
        ]
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    @staticmethod
    def _format_metrics_line(metrics: dict[str, Any] | None) -> str:
        """Render a metrics dict as a concise human-readable line."""
        if not metrics:
            return ""
        parts: list[str] = []
        total_tokens = metrics.get("total_tokens") or metrics.get(
            "total_input_tokens", 0
        ) + metrics.get("total_output_tokens", 0)
        if total_tokens:
            parts.append(f"tokens={total_tokens}")
        cost = metrics.get("total_cost")
        if cost is not None:
            parts.append(f"cost={cost:.6f}")
        latency = metrics.get("total_latency_ms")
        if latency:
            parts.append(f"latency={latency}ms")
        if not parts:
            return ""
        return " ".join(parts)

    def render_last_loop(self) -> str:
        """Return a human-readable summary of the last loop report.

        If no loop report exists but a session was saved more recently, fall back
        to the latest session report so `rootact report --last` is useful even
        when the loop controller has not written a loop report.
        """
        report = self._load_loop_report()
        if report is not None:
            return self._render_loop_report(report)

        session_id = self._latest_session_id()
        if session_id is not None:
            session_output = self.render_session(session_id)
            return (
                "No loop report found. Showing the most recent session instead.\n\n"
                + session_output
            )
        return "No loop report found. Run 'rootact ... --loop' first."

    def _render_loop_report(self, report: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append("RACT Loop Report")
        lines.append("================")
        lines.append(f"Final decision: {report.get('final_decision', 'unknown')}")
        lines.append(f"Summary: {report.get('summary', 'n/a')}")

        top_metrics = report.get("metrics")
        if top_metrics:
            metric_line = self._format_metrics_line(top_metrics)
            if metric_line:
                lines.append(f"Totals: {metric_line}")

        handshake_milestones = report.get("handshake_milestones", [])
        if handshake_milestones:
            lines.append("")
            lines.append("Operator Handshakes (review required):")
            for mid in handshake_milestones:
                lines.append(f"  - {mid}")

        iterations = report.get("iterations", [])
        if iterations:
            lines.append("")
            lines.append(f"Iterations ({len(iterations)}):")
            for it in iterations:
                status = "pass" if it.get("test_returncode") == 0 else "fail"
                line = (
                    f"  #{it.get('index')}: decision={it.get('decision')} "
                    f"tests={status} score={it.get('quality_score')}"
                )
                it_metrics = self._format_metrics_line(it.get("metrics"))
                if it_metrics:
                    line += f" {it_metrics}"
                lines.append(line)
                reflection = it.get("reflection", "")
                if reflection:
                    lines.append(f"    {reflection}")

        return "\n".join(lines)

    def render_session(self, session_id: str) -> str:
        """Return a human-readable summary of a saved session."""
        report = self._load_session_report(session_id)
        if report is None:
            return f"No session report found for '{session_id}'."

        lines: list[str] = [
            f"RACT Session Report: {session_id}",
            "========================",
            f"Intent: {report.get('intent', 'n/a')}",
            f"Assumption: {report.get('plan', {}).get('assumption', 'n/a')}",
            f"Confidence: {report.get('plan', {}).get('confidence', 'n/a')}",
        ]
        outcomes = report.get("outcomes", [])
        if outcomes:
            lines.append("")
            lines.append("Outcomes:")
            for outcome in outcomes:
                lines.append(f"  - {outcome}")
        return "\n".join(lines)

    def render_last_loop_json(self) -> dict[str, Any] | None:
        """Return the last loop report as a structured dictionary."""
        return self._load_loop_report()

    def render_session_json(self, session_id: str) -> dict[str, Any] | None:
        """Return a saved session report as a structured dictionary."""
        return self._load_session_report(session_id)


# RACT 0.1.1 - Trust and Tooling
