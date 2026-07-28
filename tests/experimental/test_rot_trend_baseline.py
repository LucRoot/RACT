from pathlib import Path

from ract.experimental.rot_trend_baseline import compute_rot_trend_baseline


def test_first_baseline_is_stable(tmp_path: Path):
    history = tmp_path / "rot_history.jsonl"
    report = compute_rot_trend_baseline(tmp_path, history)
    assert report.direction == "stable"
    assert report.deltas is None
    assert report.slope is None
    assert "duplication_ratio" in report.snapshot
    assert "novelty_score" in report.snapshot
    assert "dead_code_count" in report.snapshot
    assert "missing_knot_count" in report.snapshot
    assert history.is_file()


def test_second_baseline_has_deltas_and_slope(tmp_path: Path):
    history = tmp_path / "rot_history.jsonl"
    compute_rot_trend_baseline(tmp_path, history)
    report = compute_rot_trend_baseline(tmp_path, history)
    assert report.previous is not None
    assert report.deltas is not None
    assert report.slope is not None
