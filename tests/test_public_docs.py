"""Tests that public documentation files exist and contain expected sections."""

from __future__ import annotations


from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).parent.parent / "docs"


@pytest.mark.parametrize(
    "filename",
    [
        "QUICKSTART.md",
        "PROVIDER_SETUP.md",
        "SKILL_AUTHORING.md",
    ],
)
def test_public_doc_exists(filename: str) -> None:
    path = DOCS_DIR / filename
    assert path.is_file(), f"Public doc missing: {path}"
    assert path.stat().st_size > 0


def test_quickstart_covers_installation_and_first_run() -> None:
    text = (DOCS_DIR / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "pip install ract" in text
    assert "ract.yaml" in text
    assert "--dry-run" in text
    assert "--session" in text
    assert "--mode" in text


def test_provider_setup_covers_adapters_and_env_vars() -> None:
    text = (DOCS_DIR / "PROVIDER_SETUP.md").read_text(encoding="utf-8")
    assert "local_http" in text
    assert "openai" in text
    assert "OPENAI_API_KEY" in text
    assert "retry" in text.lower()
    assert "streaming" in text.lower()


def test_skill_authoring_covers_templates_and_variables() -> None:
    text = (DOCS_DIR / "SKILL_AUTHORING.md").read_text(encoding="utf-8")
    assert ".ract/skills/" in text
    assert "string.Template" in text
    assert "$intent" in text
    assert "$project_name" in text
    assert "$context" in text


# RACT 0.1.1 - Trust and tooling
