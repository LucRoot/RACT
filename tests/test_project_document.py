from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

from rootact.manager import Step
from rootact.project_document import ProjectDocument


def test_load_save_roundtrip(tmp_path):
    """Verify ProjectDocument can be loaded from JSON and saved back."""
    doc = ProjectDocument(
        goal="Test Goal",
        plan=[Step(action="do", provider_hint="A", expected_artifact="B")],
    )
    file_path = tmp_path / "doc.json"
    doc.save(file_path)
    loaded = ProjectDocument.load(file_path)
    assert loaded.sections() == doc.sections()


def test_required_sections_validation(tmp_path):
    """Ensure missing required sections raise ValueError during initialization."""
    try:
        ProjectDocument(goal="Goal")  # plan missing
    except ValueError as e:
        assert "Required section 'plan' is missing" in str(e)


def test_defaults_and_optional_sections(tmp_path):
    """Check that defaults are applied and optional sections are preserved."""
    doc = ProjectDocument(
        goal="Goal",
        plan=[Step(action="step", provider_hint="H", expected_artifact="A")],
    )
    assert "goal" in doc.sections()
    assert "plan" in doc.sections()
    assert "notes" in doc.sections()
    assert doc.sections()["notes"] == []
    file_path = tmp_path / "doc.json"
    doc.save(file_path)
    loaded = ProjectDocument.load(file_path)
    assert "notes" in loaded.sections()
    assert loaded.sections()["notes"] == []


def test_save_serializes_all_sections(tmp_path):
    """Verify that save includes non-required sections in the JSON output."""
    doc = ProjectDocument(
        goal="Goal",
        plan=[Step(action="a", provider_hint="H", expected_artifact="A")],
        sections={
            "custom": [Step(action="c", provider_hint="H", expected_artifact="C")]
        },
    )
    file_path = tmp_path / "doc.json"
    doc.save(file_path)
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert "custom" in data
    assert data["custom"] == [
        {"action": "c", "provider_hint": "H", "expected_artifact": "C"}
    ]
