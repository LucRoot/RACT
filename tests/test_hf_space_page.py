"""Tests for the Hugging Face Space static page."""

from __future__ import annotations


import re
from pathlib import Path


def test_hf_space_page_exists_and_contains_required_content():
    page = Path("docs/hf_space/index.html").read_text(encoding="utf-8")
    assert "<title>RACT" in page
    assert "RACT" in page
    assert "ract run" in page
    assert re.search(r"https://github\.com/LucRoot/RACT", page)
