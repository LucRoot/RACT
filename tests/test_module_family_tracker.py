# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for module-family tunneling detection."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

import pytest

from rootact.loop_planner import Milestone
from rootact.module_family_tracker import (
    build_diversity_prompt,
    classify_milestone,
    detect_tunneling,
)


@pytest.mark.parametrize(
    ("description", "expected_family"),
    [
        ("Add fixture registry for edge cases", "test-fixtures"),
        ("Implement CLI yolo toggle", "cli-ui"),
        ("Register a built-in skill template", "skills"),
        ("Update README and audit docs", "documentation"),
        ("Stage and commit changes via git mode", "git"),
        ("Add provider health check adapter", "providers"),
        ("Wire MCP tool registry", "integrations"),
        ("Improve milestone oracle thresholds", "loop-core"),
        ("Block error-mask patterns", "safety"),
        ("Run lint/format repair loop", "quality"),
        ("Generate OpenAPI client", "openapi"),
        ("Scaffold project from template", "project-templates"),
        ("Persist memory arena facts", "memory"),
        ("Snapshot rollback checkpoints", "rollback"),
        ("Refactor internal helpers", "quality"),
    ],
)
def test_classify_milestone(description, expected_family):
    milestone = Milestone(id="m1", description=description, acceptance="it works")
    assert classify_milestone(milestone) == expected_family


def test_detect_tunneling_returns_signal():
    families = ["test-fixtures", "test-fixtures", "test-fixtures"]
    signal = detect_tunneling(families, limit=3)
    assert signal is not None
    assert signal.family == "test-fixtures"


def test_detect_tunneling_ignores_short_sequence():
    assert detect_tunneling(["test-fixtures", "test-fixtures"], limit=3) is None


def test_detect_tunneling_ignores_general_family():
    families = ["general", "general", "general"]
    assert detect_tunneling(families, limit=3) is None


def test_detect_tunneling_resets_on_change():
    families = ["test-fixtures", "test-fixtures", "cli-ui"]
    assert detect_tunneling(families, limit=3) is None


def test_build_diversity_prompt_includes_alternative_cases(tmp_path):
    catalog = tmp_path / "rootact_use_cases.jsonl"
    cases = [
        {"status": "accepted", "title": "CLI Toggles", "value": "yolo/auto"},
        {"status": "accepted", "title": "Documentation Mode", "value": "docs first"},
        {"status": "rejected", "title": "Native GUI", "value": "nope"},
    ]
    catalog.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")

    from rootact.module_family_tracker import TunnelingSignal

    signal = TunnelingSignal(family="test-fixtures", consecutive_count=3, limit=3)
    prompt = build_diversity_prompt(signal, tmp_path, sample_count=4)
    assert "test-fixtures" in prompt
    assert "CLI Toggles" in prompt
    assert "Documentation Mode" in prompt
    assert "Native GUI" not in prompt


# RACT 0.1.0 - Initial Public Release
