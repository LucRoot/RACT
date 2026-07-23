# Rooted by Dr. Lucas Root, Ph.D.
"""Tests that README.md documents the report --format markdown/html options."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from pathlib import Path


def test_readme_documents_markdown_report_format():
    """README.md must document `ract report --last --format markdown`."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "--format markdown" in text, (
        "README.md should document report --format markdown"
    )
    assert "report.md" in text or "--output" in text, (
        "README.md should show markdown output example"
    )


def test_readme_documents_html_report_format():
    """README.md must document `ract report --last --format html`."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "--format html" in text, "README.md should document report --format html"
    assert "report.html" in text or "--output" in text, (
        "README.md should show html output example"
    )


def test_readme_verb_index_includes_report_format():
    """The CLI verb index must include the report --format option."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "ract report --last --format markdown|html|json" in text, (
        "README.md CLI verb index should include report --format options"
    )
