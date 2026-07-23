__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.rot_report import find_duplicate_blocks, record_rot_trend_snapshot
from rootact.rot_trend import TrendReport


def test_find_duplicate_blocks(tmp_path):
    file1 = tmp_path / "a.py"
    file2 = tmp_path / "b.py"

    # Write identical code to both files
    code = """
def hello():
    return "world"
"""
    file1.write_text(code)
    file2.write_text(code)

    duplicates = find_duplicate_blocks([str(file1), str(file2)])
    assert len(duplicates) == 1
    assert duplicates[0][0] == str(file1)
    assert duplicates[0][1] == str(file2)


def test_record_rot_trend_snapshot_with_string_path(tmp_path):
    history = tmp_path / "rot_history.jsonl"
    metrics = {
        "duplication_ratio": 0.1,
        "novelty_score": 0.2,
        "dead_code_count": 0,
        "missing_knot_count": 0,
    }

    report = record_rot_trend_snapshot(metrics, str(history))

    assert isinstance(report, TrendReport)
    assert report.snapshot == metrics
    assert report.direction == "stable"
    assert history.is_file()
    assert history.read_text(encoding="utf-8").startswith("{")
