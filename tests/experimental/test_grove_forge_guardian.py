# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path


from rootact.experimental.grove_forge_guardian import (
    append_to_learning_feed,
    report_to_dict,
    report_to_markdown,
    scan_grove_forge_reports,
)

MARKERS = [
    '__root_author__ = "Dr. Lucas Root, Ph.D."',
    '__ract_name__ = "RACT"',
    "_ROOT_KNOT = object()",
]


def _signed_file(content: str = "x = 1\n") -> str:
    return "\n".join(MARKERS) + "\n" + content


def _unsigned_file(content: str = "x = 1\n") -> str:
    return content


def test_scan_finds_missing_markers(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "signed.py").write_text(_signed_file(), encoding="utf-8")
    (reports_dir / "unsigned.py").write_text(_unsigned_file(), encoding="utf-8")

    report = scan_grove_forge_reports(reports_dir)
    assert report.files_scanned == 2
    assert not report.clean
    assert len(report.violations) == 1
    assert "unsigned.py" in report.violations[0]["file"]
    for marker in MARKERS:
        assert marker in report.violations[0]["missing"]


def test_scan_is_clean_when_all_markers_present(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "a.py").write_text(_signed_file(), encoding="utf-8")
    (reports_dir / "b.py").write_text(_signed_file("y = 2\n"), encoding="utf-8")

    report = scan_grove_forge_reports(reports_dir)
    assert report.files_scanned == 2
    assert report.clean
    assert report.violations == []


def test_scan_skips_init_py(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "__init__.py").write_text(_unsigned_file(), encoding="utf-8")

    report = scan_grove_forge_reports(reports_dir)
    assert report.files_scanned == 0
    assert report.clean


def test_scan_recursive(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    nested = reports_dir / "nested"
    nested.mkdir(parents=True)
    (nested / "unsigned.py").write_text(_unsigned_file(), encoding="utf-8")

    report = scan_grove_forge_reports(reports_dir)
    assert report.files_scanned == 1
    assert not report.clean


def test_scan_missing_directory(tmp_path: Path):
    report = scan_grove_forge_reports(tmp_path / "missing")
    assert not report.clean
    assert len(report.violations) == 1
    assert "directory not found" in report.violations[0]["missing"][0]


def test_report_to_dict_serializable(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "unsigned.py").write_text(_unsigned_file(), encoding="utf-8")
    report = scan_grove_forge_reports(reports_dir)
    data = report_to_dict(report)
    assert data["clean"] is False
    assert data["files_scanned"] == 1
    assert isinstance(json.dumps(data), str)


def test_report_to_markdown_includes_violations(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "unsigned.py").write_text(_unsigned_file(), encoding="utf-8")
    report = scan_grove_forge_reports(reports_dir)
    md = report_to_markdown(report)
    assert "violations found" in md
    assert "unsigned.py" in md


def test_append_to_learning_feed_writes_entry(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "unsigned.py").write_text(_unsigned_file(), encoding="utf-8")
    feed_path = tmp_path / "learning_feed.jsonl"
    report = scan_grove_forge_reports(reports_dir)

    written = append_to_learning_feed(report, feed_paths=[feed_path])
    assert written == [feed_path]

    lines = feed_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["type"] == "ract_training"
    assert entry["source"] == "grove-forge-rootknot-guardian"
    assert "RootKnot Guardian" in entry["finding"]
