__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.run_reporter import render_markdown


def test_render_markdown_includes_sections():
    report = {
        "final_decision": "accepted",
        "summary": "all green",
        "metrics": {"total_tokens": 1234},
        "handshake_milestones": ["approve auth change"],
        "iterations": [
            {
                "index": 0,
                "decision": "accepted",
                "test_returncode": 0,
                "quality_score": 0.9,
            }
        ],
    }
    md = render_markdown(report)
    assert "# RACT Run Report" in md
    assert "accepted" in md
    assert "all green" in md
    assert "approve auth change" in md
    assert "#0" in md
