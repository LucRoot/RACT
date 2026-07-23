# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the earned-coverage gate."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

from rootact.coverage_delta import (
    CoverageSnapshot,
    compute_delta,
    export_delta,
    gate,
    read_snapshot,
)


def test_compute_delta_improvement_is_earn():
    before = CoverageSnapshot(
        percent_covered=90.0, covered_lines=90, missing_lines=10, total_lines=100
    )
    after = CoverageSnapshot(
        percent_covered=92.0, covered_lines=92, missing_lines=8, total_lines=100
    )
    delta = compute_delta(before, after)
    assert delta.verdict == "earn"
    assert delta.percent_delta == 2.0


def test_compute_delta_drop_is_regress():
    before = CoverageSnapshot(
        percent_covered=90.0, covered_lines=90, missing_lines=10, total_lines=100
    )
    after = CoverageSnapshot(
        percent_covered=88.0, covered_lines=88, missing_lines=12, total_lines=100
    )
    delta = compute_delta(before, after)
    assert delta.verdict == "regress"


def test_compute_delta_flat_with_new_missing_is_stagnant():
    before = CoverageSnapshot(
        percent_covered=90.0, covered_lines=90, missing_lines=10, total_lines=100
    )
    after = CoverageSnapshot(
        percent_covered=90.0, covered_lines=180, missing_lines=20, total_lines=200
    )
    delta = compute_delta(before, after)
    assert delta.verdict == "stagnant"


def test_read_snapshot_parses_pytest_cov_json(tmp_path):
    data = {
        "totals": {
            "percent_covered": 93.5,
            "covered_lines": 935,
            "missing_lines": 65,
            "num_statements": 1000,
        }
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    rooted = read_snapshot(path)

    assert rooted.is_ok()
    snap = rooted.unwrap()
    assert snap.percent_covered == 93.5
    assert snap.covered_lines == 935
    assert snap.missing_lines == 65
    assert snap.total_lines == 1000


def test_read_snapshot_fails_on_missing_file(tmp_path):
    rooted = read_snapshot(tmp_path / "missing.json")
    assert not rooted.is_ok()
    assert "not found" in (rooted.error or "").lower()


def test_compute_delta_floor_breach_forces_regress():
    before = CoverageSnapshot(
        percent_covered=92.0, covered_lines=92, missing_lines=8, total_lines=100
    )
    after = CoverageSnapshot(
        percent_covered=94.0, covered_lines=94, missing_lines=6, total_lines=100
    )
    delta = compute_delta(before, after, min_percent=95.0)
    assert delta.verdict == "regress"
    assert delta.floor_breached is True
    assert "95.0%" in delta.detail


def test_compute_delta_floor_no_breach_when_above():
    before = CoverageSnapshot(
        percent_covered=92.0, covered_lines=92, missing_lines=8, total_lines=100
    )
    after = CoverageSnapshot(
        percent_covered=96.0, covered_lines=96, missing_lines=4, total_lines=100
    )
    delta = compute_delta(before, after, min_percent=95.0)
    assert delta.verdict == "earn"
    assert delta.floor_breached is False


def test_gate_floor_breach_on_baseline(monkeypatch, tmp_path):
    low = CoverageSnapshot(
        percent_covered=92.0, covered_lines=92, missing_lines=8, total_lines=100
    )

    def _fake_run_snapshot(_project_dir, **kwargs):
        from rootact.rooted import Rooted

        return Rooted(value=low, assumption="mock", confidence=1.0)

    monkeypatch.setattr(
        "rootact.coverage_delta.run_snapshot",
        _fake_run_snapshot,
    )
    rooted = gate(tmp_path, min_percent=95.0)
    assert rooted.is_ok()
    delta = rooted.unwrap()
    assert delta.verdict == "regress"
    assert delta.floor_breached is True
    assert "baseline below 95.0%" in delta.detail


def test_gate_per_file_floor_breach_on_baseline(monkeypatch, tmp_path):
    snapshot = CoverageSnapshot(
        percent_covered=96.0,
        covered_lines=96,
        missing_lines=4,
        total_lines=100,
        per_file={
            "src/rootact/core.py": CoverageSnapshot(
                percent_covered=70.0,
                covered_lines=70,
                missing_lines=30,
                total_lines=100,
            )
        },
    )

    def _fake_run_snapshot(_project_dir, **kwargs):
        from rootact.rooted import Rooted

        return Rooted(value=snapshot, assumption="mock", confidence=1.0)

    monkeypatch.setattr(
        "rootact.coverage_delta.run_snapshot",
        _fake_run_snapshot,
    )
    rooted = gate(tmp_path, per_file_min_percent={"src/rootact/core.py": 80.0})
    assert rooted.is_ok()
    delta = rooted.unwrap()
    assert delta.verdict == "regress"
    assert delta.per_file_breaches
    assert "core.py: 70.0% < 80.0%" in delta.per_file_breaches[0]


def test_gate_per_file_missing_file_is_breach(monkeypatch, tmp_path):
    snapshot = CoverageSnapshot(
        percent_covered=96.0,
        covered_lines=96,
        missing_lines=4,
        total_lines=100,
        per_file={},
    )

    def _fake_run_snapshot(_project_dir, **kwargs):
        from rootact.rooted import Rooted

        return Rooted(value=snapshot, assumption="mock", confidence=1.0)

    monkeypatch.setattr(
        "rootact.coverage_delta.run_snapshot",
        _fake_run_snapshot,
    )
    rooted = gate(tmp_path, per_file_min_percent={"src/rootact/core.py": 80.0})
    assert rooted.is_ok()
    delta = rooted.unwrap()
    assert delta.verdict == "regress"
    assert "missing" in delta.per_file_breaches[0]


def test_save_and_load_baseline_round_trip_with_per_file(tmp_path):
    from rootact.coverage_delta import load_baseline, save_baseline

    snapshot = CoverageSnapshot(
        percent_covered=91.0,
        covered_lines=91,
        missing_lines=9,
        total_lines=100,
        per_file={
            "src/rootact/core.py": CoverageSnapshot(
                percent_covered=95.0,
                covered_lines=95,
                missing_lines=5,
                total_lines=100,
            )
        },
    )
    save_baseline(tmp_path, snapshot)
    loaded = load_baseline(tmp_path)
    assert loaded is not None
    assert loaded.percent_covered == 91.0
    assert loaded.per_file is not None
    assert loaded.per_file["src/rootact/core.py"].percent_covered == 95.0


def test_save_coverage_badge_writes_shields_json(tmp_path):
    from rootact.coverage_delta import save_coverage_badge

    snapshot = CoverageSnapshot(
        percent_covered=91.2, covered_lines=912, missing_lines=88, total_lines=1000
    )
    badge_path = tmp_path / "coverage-badge.json"
    save_coverage_badge(snapshot, badge_path)
    data = json.loads(badge_path.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == 1
    assert data["label"] == "coverage"
    assert data["message"] == "91.2%"
    assert data["color"] == "brightgreen"


def test_coverage_color_thresholds():
    from rootact.coverage_delta import _coverage_color

    assert _coverage_color(95.0) == "brightgreen"
    assert _coverage_color(85.0) == "green"
    assert _coverage_color(75.0) == "yellowgreen"
    assert _coverage_color(65.0) == "yellow"
    assert _coverage_color(55.0) == "orange"
    assert _coverage_color(45.0) == "red"


def test_export_delta_writes_json(tmp_path):
    delta = {"before": 90.0, "after": 92.0, "delta": 2.0}
    out = tmp_path / "delta.json"
    export_delta(delta, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == delta


def test_export_delta_uses_indent(tmp_path):
    delta = {"verdict": "earn"}
    out = tmp_path / "delta.json"
    export_delta(delta, out)
    text = out.read_text(encoding="utf-8")
    assert "{\n" in text
    assert '"verdict"' in text


# RACT 0.1.1 - Trust and Tooling
