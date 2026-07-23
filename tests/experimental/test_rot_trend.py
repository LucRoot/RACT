__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import pytest

from rootact.experimental.rot_trend import record_snapshot


def test_first_snapshot_graceful_case(tmp_path):
    history = tmp_path / "rot_history.jsonl"
    report = record_snapshot(
        {
            "duplication_ratio": 0.1,
            "novelty_score": 0.5,
            "dead_code_count": 2,
            "missing_knot_count": 1,
        },
        history,
    )
    assert report.snapshot["duplication_ratio"] == 0.1
    assert report.previous is None
    assert report.deltas is None
    assert report.direction == "stable"
    assert report.slope is None
    assert history.is_file()


def test_second_snapshot_deltas_and_direction(tmp_path):
    history = tmp_path / "rot_history.jsonl"
    record_snapshot(
        {
            "duplication_ratio": 0.2,
            "novelty_score": 0.5,
            "dead_code_count": 4,
            "missing_knot_count": 2,
        },
        history,
    )
    report = record_snapshot(
        {
            "duplication_ratio": 0.1,
            "novelty_score": 0.6,
            "dead_code_count": 2,
            "missing_knot_count": 1,
        },
        history,
    )
    assert report.previous is not None
    assert report.deltas is not None
    assert report.deltas["duplication_ratio"] == pytest.approx(-0.1)
    assert report.deltas["novelty_score"] == pytest.approx(0.1)
    assert report.deltas["dead_code_count"] == -2
    assert report.deltas["missing_knot_count"] == -1
    assert report.direction == "improving"


def test_rolling_slope_using_three_snapshots(tmp_path):
    history = tmp_path / "rot_history.jsonl"
    base = {
        "duplication_ratio": 0.3,
        "novelty_score": 0.4,
        "dead_code_count": 6,
        "missing_knot_count": 3,
    }
    record_snapshot(base, history)
    second = {
        "duplication_ratio": 0.2,
        "novelty_score": 0.5,
        "dead_code_count": 4,
        "missing_knot_count": 2,
    }
    record_snapshot(second, history)
    third = {
        "duplication_ratio": 0.1,
        "novelty_score": 0.6,
        "dead_code_count": 2,
        "missing_knot_count": 1,
    }
    report = record_snapshot(third, history, window=3)
    assert report.slope is not None
    assert report.slope["duplication_ratio"] == pytest.approx(-0.1)
    assert report.slope["novelty_score"] == pytest.approx(0.1)
    assert report.slope["dead_code_count"] == pytest.approx(-2.0)
    assert report.slope["missing_knot_count"] == pytest.approx(-1.0)
