from __future__ import annotations


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
        path = self.project_dir / ".ract" / "loop_report.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _load_session_report(self, session_id: str) -> dict[str, Any] | None:
        path = self.project_dir / ".ract" / "sessions" / f"{session_id}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _latest_session_id(self) -> str | None:
        """Return the most recently modified session id, or None if none exist."""
        sessions_dir = self.project_dir / ".ract" / "sessions"
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
        to the latest session report so `ract report --last` is useful even
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
        return "No loop report found. Run 'ract ... --loop' first."

    def _render_loop_report(self, report: dict[str, Any]) -> str:
        lines: list[str] = []
        lines.append("RACT Loop Report")
        lines.append("================")
        lines.append(f"Final decision: {report.get('final_decision', 'unknown')}")
        termination_cause = report.get("termination_cause")
        if termination_cause:
            lines.append(f"Termination cause: {termination_cause}")
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
            trajectory: list[str] = []
            for it in iterations:
                status = "pass" if it.get("test_returncode") == 0 else "fail"
                score = it.get("quality_score")
                line = (
                    f"  #{it.get('index')}: decision={it.get('decision')} "
                    f"tests={status} score={score}"
                )
                if score is not None:
                    trajectory.append(str(score))
                it_metrics = self._format_metrics_line(it.get("metrics"))
                if it_metrics:
                    line += f" {it_metrics}"
                lines.append(line)
                reflection = it.get("reflection", "")
                if reflection:
                    lines.append(f"    {reflection}")
            if trajectory:
                lines.append("")
                lines.append(f"Score trajectory: {' -> '.join(trajectory)}")

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


def render_markdown(report: dict[str, Any]) -> str:
    """Convert a loop-report dict into a Markdown summary."""
    lines = ["# RACT Run Report", ""]
    lines.append(f"**Final decision:** {report.get('final_decision', 'unknown')}")
    termination_cause = report.get("termination_cause")
    if termination_cause:
        lines.append(f"**Termination cause:** {termination_cause}")
    lines.append(f"**Summary:** {report.get('summary', 'n/a')}")
    metrics = report.get("metrics")
    if metrics:
        lines.extend(["", "## Metrics", ""])
        for key, value in sorted(metrics.items()):
            lines.append(f"- **{key}:** {value}")
    handshakes = report.get("handshake_milestones", [])
    if handshakes:
        lines.extend(["", "## Operator Handshakes", ""])
        for item in handshakes:
            lines.append(f"- {item}")
    iterations = report.get("iterations", [])
    if iterations:
        lines.extend(["", "## Iterations", ""])
        trajectory: list[str] = []
        for it in iterations:
            status = "pass" if it.get("test_returncode") == 0 else "fail"
            score = it.get("quality_score")
            lines.append(
                f"- #{it.get('index')}: decision={it.get('decision')} "
                f"tests={status} score={score}"
            )
            if score is not None:
                trajectory.append(str(score))
        if trajectory:
            lines.extend(["", "## Score Trajectory", ""])
            lines.append(f"`{' -> '.join(trajectory)}`")
    return "\n".join(lines)


def render_html_report(report: dict[str, Any]) -> str:
    """Convert a loop-report dict into a self-contained HTML summary."""
    lines = [
        "<html><body>",
        "<h1>RACT Run Report</h1>",
        f"<p><strong>Final decision:</strong> {report.get('final_decision', 'unknown')}</p>",
    ]
    termination_cause = report.get("termination_cause")
    if termination_cause:
        lines.append(f"<p><strong>Termination cause:</strong> {termination_cause}</p>")
    lines.append(f"<p><strong>Summary:</strong> {report.get('summary', 'n/a')}</p>")
    metrics = report.get("metrics")
    if metrics:
        lines.extend(["<h2>Metrics</h2>", "<ul>"])
        for key, value in sorted(metrics.items()):
            lines.append(f"<li><strong>{key}:</strong> {value}</li>")
        lines.append("</ul>")
    handshakes = report.get("handshake_milestones", [])
    if handshakes:
        lines.extend(["<h2>Operator Handshakes</h2>", "<ul>"])
        for item in handshakes:
            lines.append(f"<li>{item}</li>")
        lines.append("</ul>")
    iterations = report.get("iterations", [])
    if iterations:
        lines.extend(["<h2>Iterations</h2>", "<ul>"])
        trajectory: list[str] = []
        for it in iterations:
            status = "pass" if it.get("test_returncode") == 0 else "fail"
            score = it.get("quality_score")
            lines.append(
                f"<li>#{it.get('index')}: decision={it.get('decision')} "
                f"tests={status} score={score}</li>"
            )
            if score is not None:
                trajectory.append(str(score))
        lines.append("</ul>")
        if trajectory:
            lines.extend(
                [
                    "<h2>Score Trajectory</h2>",
                    f"<p>{' -&gt; '.join(trajectory)}</p>",
                ]
            )
    lines.append("</body></html>")
    return "\n".join(lines)


def export_report(report: dict[str, Any], path: Path | str) -> None:
    """Write a run-report dict to a JSON file with indent=2."""
    Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")


# RACT 0.1.1 - Trust and tooling
