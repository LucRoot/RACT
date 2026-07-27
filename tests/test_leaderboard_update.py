"""module_07 (v0.4.0) — leaderboard update script tests.

Verifies:

- Running the script with no new reports produces byte-identical
  output (idempotent — Lateral Chain branch D, module_07).
- Running the script regenerates a row from the latest report per
  provider.
- A conformance/security ``RESULTS.md`` file, when present, is
  reflected in the row (Lateral Chain branch E).
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.leaderboard.update import update


def _write_polyglot_report(
    runs_root: Path,
    date: str,
    provider: str,
    passed: int,
    failed: int,
    skipped: int,
) -> Path:
    payload = {
        "corpus": "aider_polyglot",
        "provider": provider,
        "subset_size": passed + failed + skipped,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": (passed / (passed + failed)) if (passed + failed) else 0.0,
        "generated_on": date,
        "results": [],
    }
    path = runs_root / f"{date}-polyglot-{provider}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_swebench_report(
    runs_root: Path,
    date: str,
    provider: str,
    passed: int,
    failed: int,
    skipped: int,
) -> Path:
    payload = {
        "corpus": "swebench_lite",
        "provider": provider,
        "subset_size": passed + failed + skipped,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": (passed / (passed + failed)) if (passed + failed) else 0.0,
        "generated_on": date,
        "results": [],
    }
    path = runs_root / f"{date}-swebench_lite-{provider}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_update_writes_when_new_reports_land(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    leaderboard = tmp_path / "LEADERBOARD.md"
    _write_polyglot_report(runs_root, "2026-07-26", "fake", 3, 5, 2)
    _write_swebench_report(runs_root, "2026-07-26", "fake", 1, 2, 2)

    outcome = update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=tmp_path / "no-conformance.md",
        security_results=tmp_path / "no-security.md",
    )
    assert outcome.written is True
    assert outcome.provider_count == 1
    text = leaderboard.read_text(encoding="utf-8")
    assert "| `fake` | 3 of 10 | 1 of 5 |" in text


def test_update_idempotent_with_no_new_reports(tmp_path: Path) -> None:
    """Second call with the same disk state does not rewrite the file."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    leaderboard = tmp_path / "LEADERBOARD.md"
    _write_polyglot_report(runs_root, "2026-07-26", "fake", 3, 5, 2)

    first = update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=tmp_path / "none.md",
        security_results=tmp_path / "none.md",
    )
    mtime_after_first = leaderboard.stat().st_mtime_ns
    first_text = leaderboard.read_text(encoding="utf-8")
    assert first.written is True

    second = update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=tmp_path / "none.md",
        security_results=tmp_path / "none.md",
    )
    assert second.written is False
    assert leaderboard.stat().st_mtime_ns == mtime_after_first, (
        "idempotent update must not touch the file when the content is unchanged"
    )
    assert leaderboard.read_text(encoding="utf-8") == first_text


def test_update_regenerates_row_from_latest_report_per_provider(
    tmp_path: Path,
) -> None:
    """When a newer report lands, the row updates to the latest numbers."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    leaderboard = tmp_path / "LEADERBOARD.md"
    _write_polyglot_report(runs_root, "2026-07-20", "fake", 1, 9, 0)

    update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=tmp_path / "none.md",
        security_results=tmp_path / "none.md",
    )
    older_text = leaderboard.read_text(encoding="utf-8")
    assert "1 of 10" in older_text

    _write_polyglot_report(runs_root, "2026-07-26", "fake", 4, 6, 0)
    outcome = update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=tmp_path / "none.md",
        security_results=tmp_path / "none.md",
    )
    assert outcome.written is True
    newer_text = leaderboard.read_text(encoding="utf-8")
    assert "4 of 10" in newer_text
    assert "1 of 10" not in newer_text
    assert "2026-07-26" in newer_text


def test_update_reads_conformance_and_security_results(tmp_path: Path) -> None:
    """When RESULTS.md files exist, their pass rates land in the row."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    leaderboard = tmp_path / "LEADERBOARD.md"
    _write_polyglot_report(runs_root, "2026-07-26", "fake", 5, 5, 0)

    conformance = tmp_path / "conformance-RESULTS.md"
    conformance.write_text(
        "# Conformance RESULTS\n\n* provider=fake overall_pass_rate=0.94\n",
        encoding="utf-8",
    )
    security = tmp_path / "security-RESULTS.md"
    security.write_text(
        "# Security RESULTS\n\n* provider=fake overall_pass_rate=1.0\n",
        encoding="utf-8",
    )

    update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=conformance,
        security_results=security,
    )
    text = leaderboard.read_text(encoding="utf-8")
    assert "94.0%" in text
    assert "100.0%" in text


def test_update_handles_no_reports_gracefully(tmp_path: Path) -> None:
    """An empty runs/ directory produces a placeholder row, not a crash."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    leaderboard = tmp_path / "LEADERBOARD.md"

    outcome = update(
        leaderboard_path=leaderboard,
        runs_root=runs_root,
        conformance_results=tmp_path / "none.md",
        security_results=tmp_path / "none.md",
    )
    assert outcome.written is True
    assert outcome.provider_count == 0
    text = leaderboard.read_text(encoding="utf-8")
    assert "_no reports yet_" in text


# RACT 0.4.0
