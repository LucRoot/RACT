from ract.dead_code_auction import render_html_report


def test_dead_code_auction_html():
    candidates = [{"symbol": "Candidate1"}, {"symbol": "Candidate2"}]
    html = render_html_report(candidates)
    assert "Dead Code" in html
    assert "Candidate1" in html
    assert "Candidate2" in html
