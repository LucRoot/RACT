"""Lint tests that README.md documents eval/report surfaces."""

from __future__ import annotations

from pathlib import Path


def test_readme_documents_eval_runs():
    """README.md must point readers to committed eval run reports."""
    readme = Path(__file__).parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "evals/runs/" in text, "README.md should reference evals/runs/"
    assert "evals/README.md" in text, "README.md should reference evals/README.md"
