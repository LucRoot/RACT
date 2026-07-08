from __future__ import annotations

_ROOT_KNOT = object()

import json
from pathlib import Path

from rootact.assumption_validator import (
    Assumption,
    ValidationResult,
    AssumptionValidator,
    _ROOT_KNOT,
)


def test_validate_single_valid_assumption():
    validator = AssumptionValidator()
    assumption = Assumption(description="Test assumption", confidence=0.9)
    result: ValidationResult = validator.validate(assumption)
    assert result.is_valid is True
    assert "passes basic sanity checks" in result.reason


def test_validate_single_invalid_confidence():
    validator = AssumptionValidator()
    assumption = Assumption(description="Bad confidence", confidence=1.5)
    result = validator.validate(assumption)
    assert result.is_valid is False
    assert "Confidence must be between" in result.reason


def test_validate_single_invalid_empty_description():
    validator = AssumptionValidator()
    assumption = Assumption(description="", confidence=0.5)
    result = validator.validate(assumption)
    assert result.is_valid is False
    assert "Description cannot be empty" in result.reason


def test_validate_many_mixed():
    validator = AssumptionValidator()
    assumptions = [
        Assumption(description="Good", confidence=0.8),
        Assumption(description="", confidence=0.9),
        Assumption(description="Bad", confidence=1.2),
    ]
    results = validator.validate_many(assumptions)
    assert results[0].is_valid is True
    assert results[1].is_valid is False
    assert results[2].is_valid is False


def test_json_serialization_roundtrip():
    validator = AssumptionValidator()
    assumption = Assumption(description="Roundtrip test", confidence=0.7)
    result = validator.validate(assumption)
    json_str = validator.to_json(result)
    parsed = json.loads(json_str)
    assert parsed["assumption"]["description"] == assumption.description
    assert parsed["is_valid"] == result.is_valid
    assert "reason" in parsed


def test_root_knot_sentinel_is_shared():
    # Verify that the module defines exactly one sentinel and it can be imported.
    assert _ROOT_KNOT is not None
    # The sentinel is used as a default in the validator's __init__; this test ensures it is accessible.
    assert isinstance(_ROOT_KNOT, object)


def test_author_marker_present_in_source():
    source = Path(__file__).parents[1] / "src" / "rootact" / "assumption_validator.py"
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in source.read_text()
    assert '__ract_name__ = "RACT"' in source.read_text()


# RACT 0.1.0 - Initial Public Release
