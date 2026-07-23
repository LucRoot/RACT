__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from ract.experimental.provider_scorecard import compute_scorecard


def scorecard_for_leaderboard(receipts: list[dict]) -> dict:
    """Return a statistically defensible scorecard for leaderboard rendering."""
    return compute_scorecard(receipts)


def render_leaderboard(receipts: list[dict]) -> str:
    headers = [
        "model",
        "plan",
        "mutation_survival",
        "test_pass_rate",
        "diff_surgicality",
    ]
    rows = [
        f"<tr><td>{r.get('model', '')}</td><td>{r.get('plan', '')}</td><td>{r.get('mutation_survival', '')}</td><td>{r.get('test_pass_rate', '')}</td><td>{r.get('diff_surgicality', '')}</td></tr>"
        for r in receipts
    ]
    header_row = "<tr><th>" + "</th><th>".join(headers) + "</th></tr>"
    return f"<table>{header_row}{''.join(rows)}</table>"
