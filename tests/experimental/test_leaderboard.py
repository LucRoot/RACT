__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.experimental.leaderboard import render_leaderboard


def test_leaderboard_headers():
    receipts = [
        {
            "model": "m1",
            "plan": "p1",
            "mutation_survival": "ms1",
            "test_pass_rate": "tp1",
            "diff_surgicality": "ds1",
        },
    ]
    html = render_leaderboard(receipts)
    assert "model" in html
    assert "plan" in html
    assert "mutation_survival" in html
    assert "test_pass_rate" in html
    assert "diff_surgicality" in html
