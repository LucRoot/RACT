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


# RACT 0.1.1 - Trust and Tooling
