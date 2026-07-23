__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.plan_validator import PlanValidator, ValidationResult
from rootact.manager import Plan, Step


def test_validate_valid_plan():
    plan = Plan(
        assumption="Test assumption",
        confidence=0.9,
        steps=[
            Step(
                action="do_something",
                provider_hint="dummy",
                expected_artifact="artifact",
            )
        ],
    )
    result: ValidationResult = PlanValidator.validate(plan)
    assert result.is_valid is True
    assert "valid" in result.message.lower()


def test_validate_invalid_assumption():
    plan = Plan(
        assumption="",
        confidence=0.5,
        steps=[
            Step(
                action="do_something",
                provider_hint="dummy",
                expected_artifact="artifact",
            )
        ],
    )
    result = PlanValidator.validate(plan)
    assert result.is_valid is False
    assert "assumption is empty" in result.message.lower()


def test_validate_invalid_confidence():
    plan = Plan(
        assumption="Test",
        confidence=1.5,
        steps=[
            Step(
                action="do_something",
                provider_hint="dummy",
                expected_artifact="artifact",
            )
        ],
    )
    result = PlanValidator.validate(plan)
    assert result.is_valid is False
    assert "invalid confidence" in result.message.lower()


def test_validate_invalid_steps():
    plan = Plan(
        assumption="Test",
        confidence=0.5,
        steps=[],
    )
    result = PlanValidator.validate(plan)
    assert result.is_valid is False
    assert "must contain at least one step" in result.message.lower()


def test_validate_invalid_step_action():
    plan = Plan(
        assumption="Test",
        confidence=0.5,
        steps=[Step(action="", provider_hint="dummy", expected_artifact="artifact")],
    )
    result = PlanValidator.validate(plan)
    assert result.is_valid is False
    assert "step action cannot be empty" in result.message.lower()


def test_validate_invalid_step_artifact():
    plan = Plan(
        assumption="Test",
        confidence=0.5,
        steps=[
            Step(action="do_something", provider_hint="dummy", expected_artifact="")
        ],
    )
    result = PlanValidator.validate(plan)
    assert result.is_valid is False
    assert "expected_artifact cannot be empty" in result.message.lower()


def test_validate_valid_step_multiple():
    plan = Plan(
        assumption="Test multiple steps",
        confidence=0.8,
        steps=[
            Step(action="step1", provider_hint="dummy", expected_artifact="out1"),
            Step(action="step2", provider_hint="dummy", expected_artifact="out2"),
        ],
    )
    result = PlanValidator.validate(plan)
    assert result.is_valid is True
    assert "valid" in result.message.lower()


def _plan_dict(version: str = "1.0.0") -> dict:
    return {
        "schema_version": version,
        "assumption": "test",
        "confidence": 0.9,
        "steps": [
            {
                "step_id": "s1",
                "action": "write file",
                "expected_artifact": "src/foo.py",
                "tier": "T1",
            }
        ],
    }


def test_validate_schema_accepts_current_version():
    result = PlanValidator.validate_schema(_plan_dict("1.0.0"))
    assert result.is_valid is True


def test_validate_schema_rejects_unknown_version():
    result = PlanValidator.validate_schema(_plan_dict("9.9.9"))
    assert result.is_valid is False
    assert "unknown schema version" in result.message.lower()


def test_validate_schema_rejects_missing_version():
    data = _plan_dict("1.0.0")
    del data["schema_version"]
    result = PlanValidator.validate_schema(data)
    assert result.is_valid is False
    assert "missing schema_version" in result.message.lower()


def test_migrate_plan_v090_to_v100():
    from rootact.plan_validator import migrate_plan

    data = {
        "schema_version": "0.9.0",
        "assumption": "test",
        "confidence": 0.9,
        "steps": [
            {
                "step_id": "s1",
                "action": "write file",
                "artifact": "src/foo.py",
            }
        ],
    }
    migrated = migrate_plan(data, "1.0.0")
    assert migrated is not None
    assert migrated["schema_version"] == "1.0.0"
    assert migrated["steps"][0]["expected_artifact"] == "src/foo.py"
    assert migrated["steps"][0]["tier"] == "T1"
    assert "budget" in migrated


def test_migrate_plan_unsupported_returns_none():
    from rootact.plan_validator import migrate_plan

    data = _plan_dict("0.8.0")
    assert migrate_plan(data, "1.0.0") is None


def test_migrate_plan_noop_when_already_target():
    from rootact.plan_validator import migrate_plan

    data = _plan_dict("1.0.0")
    migrated = migrate_plan(data, "1.0.0")
    assert migrated is not None
    assert migrated["schema_version"] == "1.0.0"


# RACT 0.2.0
