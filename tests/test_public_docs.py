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


def test_architecture_documents_failure_modes_and_concurrency() -> None:
    """ARCHITECTURE.md must describe what the system refuses to do silently.

    Each named failure must map to a real TerminationCause (T1-T7) or to the
    authorize_action gate, so a reader can grep the code and confirm.
    """
    text = (DOCS_DIR / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Failure modes and concurrency" in text
    # Each failure case the spec requires:
    assert "PlanValidator" in text or "validate_schema" in text
    assert "fallback_chain" in text
    assert "PROVIDER_TIMEOUT" in text  # T7
    assert "BUDGET_EXHAUSTED" in text  # T5
    assert "HANDSHAKE_BLOCKED" in text  # T6
    assert "serially" in text or "serial" in text  # concurrency claim
    assert "authorize_action" in text
    assert "REFUSE" in text  # T3 default policy


@pytest.mark.parametrize(
    "adr_filename",
    [
        "ADR-0008-ract-yaml-versioning.md",
        "ADR-0009-mcp-tool-execution-boundaries.md",
    ],
)
def test_new_adrs_have_canonical_shape(adr_filename: str) -> None:
    """Each ADR must carry Status, Decision, and Alternatives Considered.

    Rejected alternatives are the strongest signal that a decision was made
    rather than defaulted; their absence is a depth-signal failure.
    """
    path = DOCS_DIR / "ADRs" / adr_filename
    assert path.is_file(), f"ADR missing: {path}"
    text = path.read_text(encoding="utf-8")
    assert "## Status" in text
    assert "## Decision" in text
    assert "## Alternatives Considered" in text
    # Each rejected alternative must state it was rejected, not just named.
    assert "rejected" in text.lower()


# RACT 0.3.0
